from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from multipane_commander.platform import build_cd_command, is_windows, pick_shell, shell_line_ending


class TerminalBackend(QObject):
    output_received = Signal(str)
    started = Signal()

    def __init__(self, *, initial_directory: Path) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self.shell = pick_shell()

    @property
    def backend_name(self) -> str:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def write_bytes(self, data: bytes) -> None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def resize(self, cols: int, rows: int) -> None:
        return None

    def interrupt_current_program(self) -> None:
        if self.is_running():
            self.write_bytes(b"\x03")

    def force_kill_current_program(self) -> None:
        self.stop()
        self.output_received.emit("\nKilled terminal process. Shell restarted.\n")
        self.start()

    def change_directory(self, path: Path) -> None:
        self.initial_directory = path
        if not self.is_running():
            return
        self.write_text(build_cd_command(path, self.shell.kind) + shell_line_ending(self.shell.kind))

    def send_command(self, command: str) -> None:
        self.write_text(command.rstrip() + shell_line_ending(self.shell.kind))

    def write_text(self, text: str) -> None:
        self.write_bytes(text.encode("utf-8", errors="replace"))


class QProcessBackend(TerminalBackend):
    def __init__(self, *, initial_directory: Path) -> None:
        super().__init__(initial_directory=initial_directory)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.started.connect(self.started.emit)

    @property
    def backend_name(self) -> str:
        return "qprocess"

    def start(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.process.setWorkingDirectory(str(self.initial_directory))
        self.process.start(self.shell.program, self.shell.args)

    def stop(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.process.terminate()
        self.process.waitForFinished(2000)

    def write_bytes(self, data: bytes) -> None:
        if self.process.state() != QProcess.ProcessState.Running:
            self.start()
        self.process.write(data)

    def is_running(self) -> bool:
        return self.process.state() == QProcess.ProcessState.Running

    def interrupt_current_program(self) -> None:
        if not self.is_running():
            return
        if is_windows():
            self._kill_windows_process_tree()
            return
        self.write_bytes(b"\x03")

    def force_kill_current_program(self) -> None:
        if is_windows():
            self._kill_windows_process_tree()
            return
        super().force_kill_current_program()

    def _read_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.output_received.emit(data)

    def _kill_windows_process_tree(self) -> None:
        process_id = int(self.process.processId())
        if process_id <= 0:
            self.stop()
            self.output_received.emit("\nKilled terminal process. Shell restarted.\n")
            self.start()
            return

        subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.process.waitForFinished(2000)
        self.output_received.emit("\nKilled terminal process. Shell restarted.\n")
        self.start()


class PosixPtyBackend(TerminalBackend):
    def __init__(self, *, initial_directory: Path) -> None:
        super().__init__(initial_directory=initial_directory)
        self._master_fd: int | None = None
        self._slave_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

    @property
    def backend_name(self) -> str:
        return "posix-pty"

    def start(self) -> None:
        if self.is_running():
            return

        import pty

        self._master_fd, self._slave_fd = pty.openpty()
        self._stop_reader.clear()
        self._process = subprocess.Popen(
            [self.shell.program, *self.shell.args],
            stdin=self._slave_fd,
            stdout=self._slave_fd,
            stderr=self._slave_fd,
            cwd=str(self.initial_directory),
            close_fds=True,
        )
        os.close(self._slave_fd)
        self._slave_fd = None
        self._reader_thread = threading.Thread(target=self._read_loop, name="posix-pty-reader", daemon=True)
        self._reader_thread.start()
        self.started.emit()

    def stop(self) -> None:
        self._stop_reader.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        self._close_fds()

    def write_bytes(self, data: bytes) -> None:
        if not self.is_running():
            self.start()
        if self._master_fd is not None:
            os.write(self._master_fd, data)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def resize(self, cols: int, rows: int) -> None:
        master_fd = self._master_fd
        if master_fd is None or cols <= 0 or rows <= 0:
            return
        try:
            import fcntl
            import struct
            import termios

            size = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            return

    def _read_loop(self) -> None:
        while not self._stop_reader.is_set():
            master_fd = self._master_fd
            if master_fd is None:
                break
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self.output_received.emit(chunk.decode("utf-8", errors="replace"))
        self._close_fds()

    def _close_fds(self) -> None:
        for attribute_name in ("_master_fd", "_slave_fd"):
            fd = getattr(self, attribute_name)
            if fd is None:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
            setattr(self, attribute_name, None)


class WinPtyBackend(TerminalBackend):
    def __init__(self, *, initial_directory: Path) -> None:
        super().__init__(initial_directory=initial_directory)
        from winpty import Backend, PtyProcess

        self._pty_process_class = PtyProcess
        self._pty_backend = getattr(Backend, "WinPTY", None)
        self._process = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

    @property
    def backend_name(self) -> str:
        return "winpty"

    def start(self) -> None:
        if self.is_running():
            return

        argv = [self.shell.program, *self.shell.args]
        spawn_options = {"cwd": str(self.initial_directory)}
        if self._pty_backend is not None:
            spawn_options["backend"] = self._pty_backend
        try:
            self._process = self._pty_process_class.spawn(argv, **spawn_options)
        except Exception:
            if self._pty_backend is None:
                raise
            self._process = self._pty_process_class.spawn(argv, cwd=str(self.initial_directory))
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._read_loop, name="winpty-reader", daemon=True)
        self._reader_thread.start()
        self.started.emit()

    def stop(self) -> None:
        self._stop_reader.set()
        process = self._process
        if process is None:
            return
        for method_name in ("terminate", "kill", "close"):
            method = getattr(process, method_name, None)
            if callable(method):
                try:
                    method()
                except TypeError:
                    method(True)
                except Exception:
                    continue
                break
        self._process = None

    def write_bytes(self, data: bytes) -> None:
        if not self.is_running():
            self.start()
        if self._process is not None:
            self._process.write(data.decode("utf-8", errors="replace"))

    def is_running(self) -> bool:
        process = self._process
        return process is not None and bool(process.isalive())

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
            break

    def interrupt_current_program(self) -> None:
        process = self._process
        if process is None or not self.is_running():
            return
        send_interrupt = getattr(process, "sendintr", None)
        if callable(send_interrupt):
            try:
                send_interrupt()
                return
            except Exception:
                pass
        self.write_bytes(b"\x03")

    def _read_loop(self) -> None:
        while not self._stop_reader.is_set():
            process = self._process
            if process is None:
                break
            try:
                chunk = process.read()
            except EOFError:
                break
            except Exception:
                if not self.is_running():
                    break
                continue
            if not chunk:
                if not self.is_running():
                    break
                continue
            if isinstance(chunk, bytes):
                text = chunk.decode("utf-8", errors="replace")
            else:
                text = str(chunk)
            if text:
                self.output_received.emit(text)


def create_terminal_backend(*, initial_directory: Path, experimental_pty: bool = False) -> TerminalBackend:
    if not experimental_pty and os.environ.get("MPC_EXPERIMENTAL_PTY", "").strip() != "1":
        return QProcessBackend(initial_directory=initial_directory)

    if is_windows():
        try:
            return WinPtyBackend(initial_directory=initial_directory)
        except Exception:
            return QProcessBackend(initial_directory=initial_directory)

    try:
        return PosixPtyBackend(initial_directory=initial_directory)
    except Exception:
        return QProcessBackend(initial_directory=initial_directory)
