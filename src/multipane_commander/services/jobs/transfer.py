"""Transfer execution independent of window widgets and Qt threads."""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Event

from multipane_commander.services.fs.archive_fs import ArchiveFileSystem, inside_archive
from multipane_commander.services.fs.local_fs import LocalFileSystem, OperationCancelled
from multipane_commander.services.jobs.model import FileJobAction, TransferProgress


class TransferExecutor:
    def __init__(self, cancelled: Event, publish) -> None:
        self.cancelled = cancelled
        self.publish = publish
        self.fs = LocalFileSystem(check_cancel=self.check_cancel, on_bytes=self.advance)
        self.archive = ArchiveFileSystem(check_cancel=self.check_cancel, on_bytes=self.advance)
        self.done = 0
        self.total = 0
        self.started = self.last_update = 0.0
        self.label = ""

    def check_cancel(self) -> None:
        if self.cancelled.is_set():
            raise OperationCancelled()

    def advance(self, count: int) -> None:
        self.done += count
        self.report()

    def report(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_update < 0.1:
            return
        elapsed = now - self.started
        speed = self.done / elapsed if elapsed > 0 else 0
        self.publish(
            TransferProgress(
                self.done,
                self.total,
                speed,
                max(0, self.total - self.done) / speed if speed else None,
                self.label,
            )
        )
        self.last_update = now

    def _measure(self, source: Path) -> int:
        context = inside_archive(source)
        if context is not None and context[0] != source:
            import libarchive

            root, inner = context
            prefix = str(inner).rstrip("/")
            total = 0
            with libarchive.file_reader(str(root)) as reader:
                for entry in reader:
                    self.check_cancel()
                    name = str(entry.pathname or "").removeprefix("./").rstrip("/")
                    if name == prefix or name.startswith(prefix + "/"):
                        total += entry.size or 0
            return total
        if source.is_symlink():
            return 0
        if not source.is_dir():
            return source.stat().st_size
        total = 0
        for root, dirs, files in os.walk(source, followlinks=False, onerror=self._walk_error):
            self.check_cancel()
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                self.check_cancel()
                path = Path(root) / name
                if not path.is_symlink():
                    total += path.stat().st_size
        return total

    @staticmethod
    def _walk_error(error):
        raise error

    def execute(self, action: FileJobAction) -> None:
        self.check_cancel()
        source, destination = action.source, action.destination
        if action.operation == "delete":
            self.fs.delete_entry(source, bypass_trash=action.bypass_trash)
            return
        if action.operation not in {"copy", "move"} or destination is None:
            raise ValueError(f"Unsupported action: {action}")
        if os.path.lexists(destination) and not action.replace_existing:
            raise FileExistsError(f"Destination already exists: {destination}")
        if source.resolve() == destination.resolve():
            raise ValueError("Source and destination are the same")
        if source.is_dir() and destination.resolve().is_relative_to(source.resolve()):
            raise ValueError("Cannot transfer a folder into itself")
        self.done = self.total = 0
        self.started = time.monotonic()
        self.label = f"Scanning {source.name}…"
        self.report(force=True)
        self.total = self._measure(source)
        self.check_cancel()
        self.started = time.monotonic()
        self.label = source.name
        self.report(force=True)
        context = inside_archive(source)
        if context is not None and context[0] != source:
            if action.operation == "move":
                raise ValueError("Archives are read-only; use copy (F5) instead")
            self.archive.extract_entry_to(source, destination)
        else:
            action.undo_backup = self.fs.replace_entry(
                source,
                destination,
                operation=action.operation,
                retain_backup=action.operation == "move",
                replace_existing=action.replace_existing,
            )
        self.done = max(self.done, self.total)
        self.report(force=True)
