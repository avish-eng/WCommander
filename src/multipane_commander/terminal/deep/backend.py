from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from multipane_commander.platform import ShellSpec, is_windows, pick_shell, shell_line_ending
from multipane_commander.terminal.backends import (
    clean_child_process_environment_map,
    clean_windows_dll_directory_for_child_process,
)

_READ_SIZE = 65_536
_FORCE_KILL_GRACE_SECONDS = 1.5


class _Strategy(Protocol):
    name: str
    is_pty: bool

    @property
    def process(self) -> object | None: ...

    def spawn(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None: ...

    def read(self) -> bytes: ...

    def write(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def terminate(self, *, force: bool) -> None: ...

    def is_alive(self) -> bool: ...

    def exit_code(self) -> int: ...


class _PosixPtyStrategy:
    name = "posix-pty"
    is_pty = True

    def __init__(self) -> None:
        self._master_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def process(self) -> object | None:
        return self._process

    def spawn(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None:
        import pty

        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        self._master_fd = master_fd
        self._process = process
        self.resize(cols, rows)

    def read(self) -> bytes:
        master_fd = self._master_fd
        if master_fd is None:
            return b""
        try:
            return os.read(master_fd, _READ_SIZE)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        master_fd = self._master_fd
        if master_fd is not None:
            os.write(master_fd, data)

    def resize(self, cols: int, rows: int) -> None:
        master_fd = self._master_fd
        if master_fd is None or cols <= 0 or rows <= 0:
            return
        try:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except (ImportError, OSError):
            return

    def terminate(self, *, force: bool) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                if force:
                    process.kill()
                else:
                    process.terminate()
            except OSError:
                pass
        master_fd, self._master_fd = self._master_fd, None
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass

    def is_alive(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def exit_code(self) -> int:
        process = self._process
        if process is None or process.returncode is None:
            return 0
        return int(process.returncode)


class _PipeStrategy:
    name = "pipe"
    is_pty = False

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def process(self) -> object | None:
        return self._process

    def spawn(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None:
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
            bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def read(self) -> bytes:
        process = self._process
        if process is None or process.stdout is None:
            return b""
        return os.read(process.stdout.fileno(), _READ_SIZE)

    def write(self, data: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        process.stdin.write(data)
        process.stdin.flush()

    def resize(self, cols: int, rows: int) -> None:
        return

    def terminate(self, *, force: bool) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if force:
                process.kill()
            else:
                process.terminate()
        except OSError:
            pass

    def is_alive(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def exit_code(self) -> int:
        process = self._process
        if process is None or process.returncode is None:
            return 0
        return int(process.returncode)


class _WinPtyStrategy:
    is_pty = True

    def __init__(self) -> None:
        from winpty import Backend, PtyProcess

        self._process_class = PtyProcess
        candidates = [
            ("conpty", getattr(Backend, "ConPTY", None)),
            ("winpty", getattr(Backend, "WinPTY", None)),
        ]
        self._candidates = [(name, backend) for name, backend in candidates if backend is not None]
        self._active_name = self._candidates[0][0] if self._candidates else "pty"
        self._process = None

    @property
    def name(self) -> str:
        return self._active_name

    @property
    def process(self) -> object | None:
        return self._process

    def spawn(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None:
        candidates = self._candidates or [("pty", None)]
        last_error: Exception | None = None
        for name, backend in candidates:
            options: dict[str, object] = {
                "cwd": cwd,
                "env": env,
                "dimensions": (rows, cols),
            }
            if backend is not None:
                options["backend"] = backend
            try:
                with clean_windows_dll_directory_for_child_process():
                    self._process = self._process_class.spawn(argv, **options)
            except Exception as exc:
                last_error = exc
                continue
            self._active_name = name
            return
        if last_error is not None:
            raise last_error
        raise RuntimeError("winpty has no usable backend")

    def read(self) -> bytes:
        process = self._process
        if process is None:
            return b""
        try:
            chunk = process.read()
        except EOFError:
            return b""
        except Exception:
            if not self.is_alive():
                return b""
            return b""
        if isinstance(chunk, bytes):
            return chunk
        return str(chunk).encode("utf-8", errors="replace")

    def write(self, data: bytes) -> None:
        process = self._process
        if process is not None:
            process.write(data.decode("utf-8", errors="replace"))

    def resize(self, cols: int, rows: int) -> None:
        process = self._process
        if process is None or cols <= 0 or rows <= 0:
            return
        for method_name in ("setwinsize", "set_size"):
            method = getattr(process, method_name, None)
            if not callable(method):
                continue
            try:
                method(rows, cols)
            except TypeError:
                try:
                    method(cols, rows)
                except Exception:
                    continue
            except Exception:
                continue
            return

    def terminate(self, *, force: bool) -> None:
        process = self._process
        if process is None:
            return
        order = ("kill", "terminate", "close") if force else ("terminate", "close", "kill")
        for method_name in order:
            method = getattr(process, method_name, None)
            if not callable(method):
                continue
            try:
                method()
            except TypeError:
                try:
                    method(True)
                except Exception:
                    continue
            except Exception:
                continue
            return

    def is_alive(self) -> bool:
        process = self._process
        if process is None:
            return False
        try:
            return bool(process.isalive())
        except Exception:
            return False

    def exit_code(self) -> int:
        process = self._process
        code = getattr(process, "exitstatus", 0) if process is not None else 0
        return code if isinstance(code, int) else 0

    def send_interrupt(self) -> None:
        process = self._process
        if process is None:
            return
        send_interrupt = getattr(process, "sendintr", None)
        if callable(send_interrupt):
            send_interrupt()


class DeepTerminalBackend(QObject):
    """Cross-platform PTY backend with non-blocking lifecycle and raw byte output.

    Spawning, termination and forced cleanup all happen off the GUI thread, so
    showing, hiding or restarting the terminal never freezes the app. Output is
    delivered as raw bytes in large reads; the surface coalesces it for the
    renderer. The PTY size is de-duplicated so repeated layout passes do not
    trigger a reflow storm.
    """

    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)

    def __init__(
        self,
        *,
        initial_directory: Path,
        shell: ShellSpec | None = None,
        prefer_pty: bool = True,
    ) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self.shell = shell or pick_shell()
        self.prefer_pty = prefer_pty
        self._lock = threading.RLock()
        self._strategy: _Strategy | None = None
        self._spawn_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._input_queue = bytearray()
        self._cols = 80
        self._rows = 24
        self._candidate_name = self._initial_candidate_name()

    @property
    def backend_name(self) -> str:
        strategy = self._strategy
        if strategy is not None:
            return strategy.name
        return self._candidate_name

    @property
    def is_pty(self) -> bool:
        strategy = self._strategy
        if strategy is not None:
            return strategy.is_pty
        return self._candidate_name in {"conpty", "winpty", "posix-pty"}

    @property
    def process(self) -> object | None:
        strategy = self._strategy
        return strategy.process if strategy is not None else None

    def pid(self) -> int | None:
        process = self.process
        if process is None:
            return None
        pid = getattr(process, "pid", None)
        if pid is None:
            pid = getattr(process, "processId", None)
        return int(pid) if isinstance(pid, int) else None

    def is_running(self) -> bool:
        strategy = self._strategy
        return strategy is not None and strategy.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._spawn_thread is not None and self._spawn_thread.is_alive():
                return
            if self._strategy is not None and self._strategy.is_alive():
                return
            self._stop_event.clear()
            self._spawn_thread = threading.Thread(
                target=self._spawn_worker,
                name="deep-terminal-spawn",
                daemon=True,
            )
            self._spawn_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            strategy = self._strategy
        if strategy is None:
            return
        try:
            strategy.terminate(force=False)
        except Exception:
            pass
        threading.Thread(
            target=self._force_terminate_after_grace,
            args=(strategy,),
            name="deep-terminal-stop",
            daemon=True,
        ).start()

    def write_bytes(self, data: bytes) -> None:
        if not data:
            return
        strategy = self._live_strategy()
        if strategy is not None:
            try:
                strategy.write(data)
                return
            except OSError:
                pass
        with self._lock:
            self._input_queue.extend(data)
            spawning = self._spawn_thread is not None and self._spawn_thread.is_alive()
        if not spawning and not self._stop_event.is_set():
            self.start()

    def write_text(self, text: str) -> None:
        self.write_bytes(text.encode("utf-8", errors="replace"))

    def send_command(self, command: str) -> None:
        self.write_text(command.rstrip() + shell_line_ending(self.shell.kind))

    def resize(self, cols: int, rows: int) -> None:
        cols = max(1, cols)
        rows = max(1, rows)
        with self._lock:
            if (cols, rows) == (self._cols, self._rows):
                return
            self._cols = cols
            self._rows = rows
            strategy = self._strategy
        if strategy is not None:
            try:
                strategy.resize(cols, rows)
            except Exception:
                pass

    def interrupt_current_program(self) -> None:
        strategy = self._live_strategy()
        if strategy is None:
            return
        if strategy.is_pty:
            send_interrupt = getattr(strategy, "send_interrupt", None)
            if callable(send_interrupt):
                try:
                    send_interrupt()
                    return
                except Exception:
                    pass
            try:
                strategy.write(b"\x03")
                return
            except OSError:
                pass
        try:
            strategy.terminate(force=True)
        except Exception:
            pass

    def terminate_process_tree(self) -> None:
        strategy = self._live_strategy()
        if strategy is None:
            return
        try:
            strategy.terminate(force=True)
        except Exception:
            pass

    def _initial_candidate_name(self) -> str:
        if not self.prefer_pty:
            return "pipe"
        if is_windows():
            return "conpty"
        return "posix-pty"

    def _live_strategy(self) -> _Strategy | None:
        with self._lock:
            strategy = self._strategy
        if strategy is not None and strategy.is_alive():
            return strategy
        return None

    def _strategy_factories(self) -> list[type]:
        pty_factory = _WinPtyStrategy if is_windows() else _PosixPtyStrategy
        if not self.prefer_pty:
            return [_PipeStrategy, pty_factory]
        return [pty_factory, _PipeStrategy]

    def _spawn_worker(self) -> None:
        argv = [self.shell.program, *self.shell.args]
        env = self._child_environment()
        errors: list[str] = []
        strategy: _Strategy | None = None
        for factory in self._strategy_factories():
            candidate = factory()
            try:
                with self._lock:
                    rows, cols = self._rows, self._cols
                candidate.spawn(
                    argv,
                    cwd=str(self.initial_directory),
                    env=env,
                    rows=rows,
                    cols=cols,
                )
            except Exception as exc:
                errors.append(f"{factory.__name__}: {exc}")
                continue
            strategy = candidate
            break

        if strategy is None:
            self.failed.emit("; ".join(errors) or "no terminal backend available")
            return

        with self._lock:
            if self._stop_event.is_set():
                strategy.terminate(force=True)
                return
            self._strategy = strategy
            queued = bytes(self._input_queue)
            self._input_queue.clear()

        self.started.emit()
        if queued:
            try:
                strategy.write(queued)
            except OSError:
                pass

        exit_code = self._read_loop(strategy)

        with self._lock:
            if self._strategy is strategy:
                self._strategy = None
        self.exited.emit(exit_code)

    def _read_loop(self, strategy: _Strategy) -> int:
        while not self._stop_event.is_set():
            try:
                chunk = strategy.read()
            except OSError:
                break
            except Exception:
                break
            if not chunk:
                if not strategy.is_alive():
                    break
                continue
            self.output_received.emit(chunk)
        return strategy.exit_code()

    def _child_environment(self) -> dict[str, str]:
        env = clean_child_process_environment_map()
        env["MPC_TERMINAL"] = "deep"
        if not is_windows():
            env.setdefault("TERM", "xterm-256color")
            env.setdefault("COLORTERM", "truecolor")
        return env

    def _force_terminate_after_grace(self, strategy: _Strategy) -> None:
        import time

        time.sleep(_FORCE_KILL_GRACE_SECONDS)
        if strategy.is_alive():
            try:
                strategy.terminate(force=True)
            except Exception:
                pass


def create_deep_backend(
    *,
    initial_directory: Path,
    shell: ShellSpec | None = None,
    prefer_pty: bool = True,
) -> DeepTerminalBackend:
    return DeepTerminalBackend(
        initial_directory=initial_directory,
        shell=shell,
        prefer_pty=prefer_pty,
    )
