from __future__ import annotations

import shutil
import errno
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from send2trash import send2trash

from multipane_commander.domain.entries import EntryInfo


class OperationCancelled(Exception):
    """A cooperative cancellation before a transfer commits."""


class RecoveryRequired(OSError):
    """A complete recovery copy must be retained after partial source cleanup."""


class LocalFileSystem:
    def __init__(
        self,
        *,
        check_cancel: Callable[[], None] = lambda: None,
        on_bytes: Callable[[int], None] = lambda count: None,
    ) -> None:
        self.check_cancel = check_cancel
        self.on_bytes = on_bytes

    def list_dir(self, path: Path) -> list[EntryInfo]:
        entries: list[EntryInfo] = []
        with os.scandir(path) as children:
            for child in children:
                self.check_cancel()
                try:
                    stat = child.stat()
                    is_dir = child.is_dir()
                except OSError:
                    continue
                child_path = Path(child.path)
                entries.append(
                    EntryInfo(
                        name=child.name,
                        path=child_path,
                        is_dir=is_dir,
                        size=0 if is_dir else stat.st_size,
                        extension="" if is_dir else child_path.suffix.lstrip(".").upper(),
                        modified_at=datetime.fromtimestamp(stat.st_mtime),
                    )
                )

        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.lower()))

    def copy_entry(self, src: Path, dst: Path) -> None:
        self.check_cancel()
        if src.is_symlink():
            dst.symlink_to(os.readlink(src), target_is_directory=src.is_dir())
            return
        if src.is_dir():
            if dst.resolve().is_relative_to(src.resolve()):
                raise ValueError("Cannot copy a folder into itself")
            shutil.copytree(
                src,
                dst,
                symlinks=True,
                copy_function=self._copy_file,
                ignore=lambda directory, names: self.check_cancel() or [],
            )
            return
        self._copy_file(src, dst)

    def _copy_file(self, src, dst):
        self.check_cancel()
        if Path(src).resolve() == Path(dst).resolve():
            raise shutil.SameFileError(f"Source and destination are the same: {src}")
        with open(src, "rb") as source, open(dst, "wb") as target:
            while True:
                self.check_cancel()
                block = source.read(1024 * 1024)
                if not block:
                    break
                target.write(block)
                self.on_bytes(len(block))
        shutil.copystat(src, dst)
        return str(dst)

    def move_entry(self, src: Path, dst: Path) -> None:
        self.check_cancel()
        try:
            src.rename(dst)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            self.copy_entry(src, dst)
            self.check_cancel()
            # Once source removal begins it must finish without cancellation.
            try:
                self.remove_existing(src)
            except OSError as cleanup_error:
                raise RecoveryRequired(
                    f"Full copy preserved at {dst}; source cleanup incomplete: {src}"
                ) from cleanup_error

    @staticmethod
    def _cross_device(src: Path, dst: Path) -> bool:
        return src.lstat().st_dev != dst.parent.stat().st_dev

    def replace_entry(
        self,
        src: Path,
        dst: Path,
        *,
        operation: str,
        retain_backup: bool = False,
        replace_existing: bool = True,
    ) -> Path | None:
        """Stage replacement beside the target and keep the old target restorable."""
        if src.resolve() == dst.resolve():
            return

        if src.is_dir() and dst.resolve().is_relative_to(src.resolve()):
            raise ValueError("Cannot transfer a folder into itself")
        if dst.is_dir() and src.resolve().is_relative_to(dst.resolve()):
            raise ValueError("Cannot replace a folder with one of its children")
        temporary_destination = self._temporary_sibling(dst)
        backup_destination = self._temporary_sibling(dst, prefix=".mpc-bak")
        source_staged = False
        committed = False
        copied_move = operation == "move" and self._cross_device(src, dst)
        try:
            if operation == "copy":
                self.copy_entry(src, temporary_destination)
            elif operation == "move":
                if copied_move:
                    self.copy_entry(src, temporary_destination)
                else:
                    self.move_entry(src, temporary_destination)
                    source_staged = True
            else:
                raise ValueError(f"Unsupported replace operation: {operation}")

            self.check_cancel()
            if os.path.lexists(dst):
                if not replace_existing:
                    raise FileExistsError(f"Destination already exists: {dst}")
                self.move_entry(dst, backup_destination)

            try:
                self.move_entry(temporary_destination, dst)
                committed = True
            except Exception:
                if os.path.lexists(backup_destination) and not os.path.lexists(dst):
                    # Recovery must not itself be interrupted by Cancel.
                    backup_destination.rename(dst)
                raise

            if copied_move:
                self.remove_existing(src)
            if os.path.lexists(backup_destination) and not retain_backup:
                self.remove_existing(backup_destination)
            return backup_destination if os.path.lexists(backup_destination) else None
        except RecoveryRequired:
            raise
        except Exception:
            if not committed and os.path.lexists(temporary_destination):
                if source_staged or (operation == "move" and not os.path.lexists(src)):
                    # Never delete the only remaining copy. If rollback fails,
                    # leave the staged data in place and report its location.
                    try:
                        if os.path.lexists(src):
                            raise FileExistsError(f"Source path now occupied: {src}")
                        LocalFileSystem().move_entry(temporary_destination, src)
                    except Exception as recovery_error:
                        raise OSError(
                            f"Recovery required: source preserved at {temporary_destination}"
                        ) from recovery_error
                else:
                    self.remove_existing(temporary_destination)
            raise

    def rename_entry(self, src: Path, dst: Path) -> None:
        src.rename(dst)

    def mkdir(self, path: Path) -> None:
        path.mkdir()

    def delete_entry(self, path: Path, *, bypass_trash: bool = False) -> None:
        if bypass_trash:
            self.remove_existing(path)
            return
        send2trash(str(path))

    def remove_existing(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
            return
        path.unlink()

    def _temporary_sibling(self, path: Path, *, prefix: str = ".mpc-tmp") -> Path:
        for _attempt in range(100):
            candidate = path.with_name(f".{path.name}{prefix}-{uuid4().hex}")
            if not os.path.lexists(candidate):
                return candidate
        raise FileExistsError(f"Could not create temporary sibling for {path}")
