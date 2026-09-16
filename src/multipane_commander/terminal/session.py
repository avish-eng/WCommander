"""Compatibility adapter for the shared shell session and process backend."""
from pathlib import Path
from multipane_commander.terminal.deep.session import DeepTerminalSession


class TerminalSession(DeepTerminalSession):
    def __init__(self, *, initial_directory: Path, experimental_pty: bool = False, backend=None):
        super().__init__(initial_directory=initial_directory, prefer_pty=experimental_pty,
                         backend=backend)
        self.experimental_pty = experimental_pty
