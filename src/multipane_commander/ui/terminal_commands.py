"""Shared command dispatch and history for both shell terminal views."""
from pathlib import Path
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import QListWidgetItem, QMenu
from multipane_commander.ui.command_history import PINNED_COMMAND_ROLE, MAX_HISTORY_ITEMS, trim_history


class TerminalCommands:
    def inject_command(self, cwd: str, command: str) -> bool:
        self.setVisible(True)
        return self._dispatch_command(command, cwd=Path(cwd))

    def _dispatch_command(self, command: str, *, cwd: Path | None = None, run: bool = True) -> bool:
        if not command.strip():
            return False
        self._ensure_session_started()
        if cwd is not None and not cwd.is_dir():
            self._show_action_status("Choose an existing local folder before running a command")
            return False
        if self.output.current_draft() or not self.session.can_inject:
            self._show_action_status("Finish or cancel the current input and wait for the shell prompt")
            self.focus_input()
            return False
        if not run:
            self.output.inject_command(command, run=False)
            self.focus_input()
            return True
        accepted = self.session.submit_command(command, cwd=cwd)
        if accepted and not self.session.is_pty:
            self.output.append_output(command + "\r\n")
        self.focus_input()
        return accepted

    def recent_commands(self) -> list[str]:
        return list(self._recent_commands)

    def bookmarked_commands(self) -> list[str]:
        return list(self._bookmarked_commands)

    def _run_clicked_command(self, item: QListWidgetItem) -> None:
        self._run_command(item.text())

    def _remember_command(self, command: str) -> None:
        cleaned = command.strip()
        if not cleaned:
            return
        command_key = self._command_key(cleaned)
        self._recent_commands = [
            existing
            for existing in self._recent_commands
            if self._command_key(existing) != command_key
        ]
        self._recent_commands.insert(0, cleaned)
        self._trim_recent_commands()
        self._refresh_command_lists()
        self._update_rerun_button()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _trim_recent_commands(self) -> None:
        self._recent_commands = trim_history(
            self._recent_commands,
            self._bookmarked_commands,
            self._command_key,
            MAX_HISTORY_ITEMS,
        )

    def _refresh_command_lists(self) -> None:
        self.command_list.clear()
        pinned_keys = {self._command_key(command) for command in self._bookmarked_commands}
        ordered_commands = [(command, True) for command in self._bookmarked_commands] + [
            (command, False)
            for command in self._recent_commands
            if self._command_key(command) not in pinned_keys
        ]
        for command, pinned in ordered_commands:
            item = QListWidgetItem(command)
            item.setSizeHint(QSize(0, 24))
            item.setData(PINNED_COMMAND_ROLE, pinned)
            item.setToolTip(command)
            self.command_list.addItem(item)

    def _selected_command(self) -> str | None:
        current_item = self.command_list.currentItem()
        if current_item is not None:
            return current_item.text()
        text = self.output.current_draft().strip()
        return text or None

    def _selected_command_is_pinned(self) -> bool:
        current_item = self.command_list.currentItem()
        return bool(current_item is not None and current_item.data(PINNED_COMMAND_ROLE))

    def _show_command_context_menu(self, position: QPoint) -> None:
        item = self.command_list.itemAt(position)
        if item is None:
            menu = self._build_command_context_menu(None, pinned=False)
        else:
            self.command_list.setCurrentItem(item)
            self.command_list.setFocus(Qt.FocusReason.MouseFocusReason)
            menu = self._build_command_context_menu(
                item.text(),
                pinned=bool(item.data(PINNED_COMMAND_ROLE)),
            )
        menu.exec(self.command_list.viewport().mapToGlobal(position))

    def _build_command_context_menu(self, command: str | None, *, pinned: bool) -> QMenu:
        menu = QMenu(self)
        if command is not None:
            use_action = menu.addAction("Use command")
            use_action.triggered.connect(
                lambda _checked=False, value=command: self._use_command(value)
            )
            run_action = menu.addAction("Run command")
            run_action.triggered.connect(
                lambda _checked=False, value=command: self._run_command(value)
            )
            menu.addSeparator()
            if pinned:
                unpin_action = menu.addAction("Unpin command")
                unpin_action.triggered.connect(
                    lambda _checked=False, value=command: self._remove_bookmark(value)
                )
            else:
                pin_action = menu.addAction("Pin command")
                pin_action.setEnabled(command not in self._bookmarked_commands)
                pin_action.triggered.connect(
                    lambda _checked=False, value=command: self._pin_command(value)
                )
            menu.addSeparator()
        clear_action = menu.addAction("Clear history (keeps pinned)")
        clear_action.setEnabled(bool(self._recent_commands))
        clear_action.triggered.connect(lambda _checked=False: self._clear_command_history())
        return menu

    def _clear_command_history(self) -> None:
        if not self._recent_commands:
            return
        self._recent_commands = []
        self._refresh_command_lists()
        self._update_rerun_button()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _use_selected_command(self) -> None:
        command = self._selected_command()
        if command is not None:
            self._use_command(command)

    def _run_selected_command(self) -> None:
        command = self._selected_command()
        if command is not None:
            self._run_command(command)

    def _use_command(self, command: str) -> None:
        self._dispatch_command(command, run=False)

    def _run_command(self, command: str) -> None:
        self._dispatch_command(command)

    def _rerun_last_command(self) -> None:
        if not self._recent_commands:
            return
        self._run_command(self._recent_commands[0])

    def _pin_command(self, command: str) -> None:
        if command in self._bookmarked_commands:
            return
        self._bookmarked_commands.append(command)
        self._trim_recent_commands()
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _remove_selected_bookmark(self) -> None:
        current_item = self.command_list.currentItem()
        if current_item is None or not current_item.data(PINNED_COMMAND_ROLE):
            return
        self._remove_bookmark(current_item.text())

    def _remove_bookmark(self, command: str) -> None:
        if command not in self._bookmarked_commands:
            return
        self._bookmarked_commands.remove(command)
        self._trim_recent_commands()
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _update_rerun_button(self) -> None:
        self.rerun_action.setEnabled(bool(self._recent_commands))

    def _unique_commands(self, commands: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for command in commands:
            cleaned = command.strip()
            command_key = self._command_key(cleaned)
            if not cleaned or command_key in seen:
                continue
            unique.append(cleaned)
            seen.add(command_key)
        return unique

    @staticmethod
    def _command_key(command: str) -> str:
        return command.strip()
