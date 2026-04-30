from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from send2trash import send2trash

from multipane_commander.domain.entries import EntryInfo


class LocalFileSystem:
    def list_dir(self, path: Path) -> list[EntryInfo]:
        entries: list[EntryInfo] = []
        for child in path.iterdir():
            try:
                stat = child.stat()
            except OSError:
                continue

            entries.append(
                EntryInfo(
                    name=child.name,
                    path=child,
                    is_dir=child.is_dir(),
                    size=0 if child.is_dir() else stat.st_size,
                    extension="" if child.is_dir() else child.suffix.lstrip(".").upper(),
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )

        return sorted(entries, key=lambda entry: (not entry.is_dir, entry.name.lower()))

    def copy_entry(self, src: Path, dst: Path) -> None:
        if src.is_dir():
            shutil.copytree(src, dst)
            return
        shutil.copy2(src, dst)

    def move_entry(self, src: Path, dst: Path) -> None:
        shutil.move(str(src), str(dst))

    def replace_entry(self, src: Path, dst: Path, *, operation: str) -> None:
        """Stage replacement beside the target and keep the old target restorable."""
        if src.resolve() == dst.resolve():
            return

        temporary_destination = self._temporary_sibling(dst)
        backup_destination = self._temporary_sibling(dst, prefix=".mpc-bak")
        try:
            if operation == "copy":
                self.copy_entry(src, temporary_destination)
            elif operation == "move":
                self.move_entry(src, temporary_destination)
            else:
                raise ValueError(f"Unsupported replace operation: {operation}")

            if dst.exists():
                self.move_entry(dst, backup_destination)

            try:
                self.move_entry(temporary_destination, dst)
            except Exception:
                if backup_destination.exists() and not dst.exists():
                    self.move_entry(backup_destination, dst)
                raise

            if backup_destination.exists():
                self.remove_existing(backup_destination)
        except Exception:
            if temporary_destination.exists():
                self.remove_existing(temporary_destination)
            raise

    def rename_entry(self, src: Path, dst: Path) -> None:
        src.rename(dst)

    def mkdir(self, path: Path) -> None:
        path.mkdir()

    def delete_entry(self, path: Path) -> None:
        send2trash(str(path))

    def remove_existing(self, path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
            return
        path.unlink()

    def _temporary_sibling(self, path: Path, *, prefix: str = ".mpc-tmp") -> Path:
        for _attempt in range(100):
            candidate = path.with_name(f".{path.name}{prefix}-{uuid4().hex}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Could not create temporary sibling for {path}")
