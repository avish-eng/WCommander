from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.ui.dialogs import TextEntryDialog, ask_confirmation, show_message
from multipane_commander.bootstrap import AppContext, persist_app_context
from multipane_commander.services.ai import AgentRunner, PaneRoots
from multipane_commander.services.bookmarks import BookmarkStore
from multipane_commander.services.fs.local_fs import LocalFileSystem
from multipane_commander.services.jobs.manager import JobManager
from multipane_commander.services.jobs.model import FileJobAction, FileJobResult
from multipane_commander.services.undo import UndoRecord, UndoStack
from multipane_commander.platform import root_paths, root_section_label, same_filesystem
from multipane_commander.ui.function_key_bar import build_function_key_bar
from multipane_commander.ui.jobs_view import JobsView
from multipane_commander.ui.pane_view import PaneView
from multipane_commander.ui.terminal_dock import TerminalDock
from multipane_commander.ui.theme_editor import ThemeEditorDialog
from multipane_commander.ui.themes import (
    available_themes,
    build_palette,
    build_stylesheet,
    builtin_themes,
    resolve_theme_definition,
)
from multipane_commander.ui.find_files_dialog import FindFilesDialog
from multipane_commander.ui.multi_rename_dialog import MultiRenameDialog, apply_renames
from multipane_commander.ui.transfer_dialog import TransferDialog


_BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".heic",
    ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac", ".ogg", ".m4a", ".webm",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".sqlite", ".sqlite3", ".db",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".class", ".jar", ".pyc", ".o", ".a",
})


def _path_is_binary(path: Path) -> bool:
    """Decide whether ``path`` should be opened by the OS-default app, not a text editor.

    Extension first, then a null-byte sniff on the first 4 KB. Errors fall through
    to the text path so unreadable files still hit the existing editor chain.
    """
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return True
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(4096)
    except OSError:
        return False


def launch_editor(path: Path) -> str:
    """Launch a text editor (or OS-default for binaries) for ``path`` per SPEC §19.5.

    Routing:

    * Binary files (extension in the binary set, or a null byte in the first 4 KB)
      skip ``$VISUAL`` / ``$EDITOR`` (they are text editors) and go straight to the
      OS default association — Preview for images, the system PDF viewer, etc.
      Returns ``"desktop-binary"``.
    * Text-like files use the legacy chain: ``$VISUAL``, ``$EDITOR``, ``code`` on
      PATH, then ``QDesktopServices``. Returns ``"visual"``, ``"editor"``, ``"code"``,
      or ``"desktop"`` so callers and tests can verify the path taken.
    """
    if _path_is_binary(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return "desktop-binary"
    for env_var, label in (("VISUAL", "visual"), ("EDITOR", "editor")):
        value = os.environ.get(env_var)
        if value:
            subprocess.Popen([value, str(path)])
            return label
    code_bin = shutil.which("code")
    if code_bin:
        subprocess.Popen([code_bin, str(path)])
        return "code"
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    return "desktop"


def determine_drag_drop_operation(
    source_paths: list[Path],
    destination_dir: Path,
    modifiers: Qt.KeyboardModifier,
) -> str:
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        return "copy"
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        return "move"
    if not source_paths:
        return "copy"
    return "move" if same_filesystem(source_paths[0], destination_dir) else "copy"


class MainWindow(QMainWindow):
    def __init__(self, *, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.fs = LocalFileSystem()
        self._clipboard_paths: list[Path] = []
        self._clipboard_operation: str | None = None
        self._jobs_visible_before_terminal_maximize = False
        self.clipboard_chip = QLabel()
        self.layout_chip = QLabel()
        self.theme_button = QPushButton("Theme")
        self.bookmark_store = BookmarkStore(initial_paths=self.context.state.bookmarks)
        self.job_manager = JobManager(self)
        self.undo_stack = UndoStack()
        self._ai_runner: AgentRunner | None = None
        self.root_layout: QVBoxLayout | None = None
        self.panes_host: QWidget | None = None
        self.function_bar: QWidget | None = None
        self.pane_splitter: QSplitter | None = None
        self.content_splitter: QSplitter | None = None
        self.terminal_placeholder = QWidget()
        self._next_pane_shortcut: QShortcut | None = None
        self._previous_pane_shortcut: QShortcut | None = None
        self._side_by_side_previous_active_pane_index = self.context.state.layout.active_pane_index
        self.pane_views: list[PaneView] = []
        self.jobs_view = JobsView()
        self.terminal_dock = TerminalDock(
            initial_directory=self.context.state.panes[self.context.state.layout.active_pane_index].tabs[0].path,
            visible=self.context.config.show_terminal,
            follow_active_pane=self.context.config.follow_active_pane_terminal,
            experimental_pty=self.context.config.terminal.experimental_pty,
            recent_commands=self.context.config.terminal.recent_commands,
            bookmarked_commands=self.context.config.terminal.bookmarked_commands,
            history_panel_visible=self.context.config.terminal.history_panel_visible,
        )
        self.setWindowTitle("Multi-Pane Commander")
        self.resize(self.context.state.window.width, self.context.state.window.height)
        self.setMinimumSize(1000, 700)
        self._build_ui()
        self._apply_selected_theme()
        self._apply_layout_mode(self.context.state.layout.layout_mode, persist=False)
        self._update_clipboard_chip()
        self._update_layout_chip()
        if not self._is_side_by_side_layout():
            self._set_terminal_maximized(self.context.state.layout.terminal_maximized, persist=False)
        if self.context.state.window.is_maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self._bind_shortcuts()
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        self._bind_job_signals()
        self.bookmark_store.bookmarks_changed.connect(self._persist_bookmarks)
        self._set_active_pane(self.context.state.layout.active_pane_index)
        self._update_terminal_tab_shortcuts()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)
        self.root_layout = root_layout
        self.terminal_placeholder.setObjectName("terminalPlaceholder")
        self.terminal_placeholder.setMinimumHeight(0)

        self.panes_host = self._build_panes()
        content_splitter = QSplitter(Qt.Orientation.Vertical)
        content_splitter.setObjectName("contentSplitter")
        content_splitter.setChildrenCollapsible(False)
        content_splitter.addWidget(self.panes_host)
        content_splitter.addWidget(self.terminal_dock)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 0)
        content_splitter.splitterMoved.connect(lambda *_args: self._update_layout_chip())
        if self.context.state.layout.content_splitter_sizes:
            content_splitter.setSizes(self.context.state.layout.content_splitter_sizes)
        else:
            content_splitter.setSizes([760, 260])
        self.content_splitter = content_splitter
        root_layout.addWidget(content_splitter, 1)
        self.jobs_view.setVisible(False)
        root_layout.addWidget(self.jobs_view)
        self.function_bar = build_function_key_bar(
            actions=self._function_key_actions(),
            extra_widget=self._build_theme_controls(),
        )
        root_layout.addWidget(self.function_bar)

        self.setCentralWidget(root)

    def _build_panes(self) -> QWidget:
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.splitterMoved.connect(lambda *_args: self._update_layout_chip())

        for index, pane_state in enumerate(self.context.state.panes):
            pane_view = PaneView(
                pane_state=pane_state,
                bookmark_store=self.bookmark_store,
                active=index == self.context.state.layout.active_pane_index,
            )
            pane_view.activated.connect(self._on_pane_activated)
            pane_view.operation_requested.connect(self._handle_operation_request)
            pane_view.preferences_changed.connect(lambda: persist_app_context(self.context))
            pane_view.drag_drop_requested.connect(self._handle_drag_drop_request)
            pane_view.open_in_other_pane_requested.connect(
                lambda path, source_pane=pane_view: self._open_tab_in_other_pane(source_pane, path)
            )
            pane_view.current_path_changed.connect(
                lambda _path, source_pane=pane_view: self._sync_quick_view(source_pane)
            )
            pane_view.current_directory_changed.connect(
                lambda path, source_pane=pane_view: self._sync_terminal_to_pane_directory(source_pane, path)
            )
            pane_view.quick_view.ai_badges_changed.connect(self._on_ai_badges_changed)
            pane_view.set_theme_palette(
                build_palette(
                    resolve_theme_definition(
                        self.context.config.theme.selected_theme_id,
                        self.context.config.theme.custom_themes,
                    )
                )
            )
            self.pane_views.append(pane_view)
            splitter.addWidget(pane_view)

        if self.context.state.layout.pane_splitter_sizes:
            splitter.setSizes(self.context.state.layout.pane_splitter_sizes)

        self.pane_splitter = splitter
        return splitter

    def _build_theme_controls(self) -> QWidget:
        host = QWidget()
        host.setObjectName("functionKeyExtras")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.theme_button.setObjectName("editThemeButton")
        self.theme_button.setFixedWidth(64)
        self.theme_button.clicked.connect(self._edit_current_theme)

        self.layout_chip.setObjectName("layoutChip")
        self.layout_chip.setFixedWidth(128)

        self.clipboard_chip.setObjectName("clipboardChip")
        self.clipboard_chip.setMaximumWidth(180)
        self.clipboard_chip.setVisible(False)

        layout.addWidget(self.layout_chip)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.clipboard_chip)
        return host

    def _function_key_actions(self) -> list[tuple[str, str, Callable[[], None]]]:
        return [
            ("F1", "Help", self._show_help),
            ("F2", "Rename", self._rename_in_active_pane),
            ("F3", "View", self._toggle_passive_quick_view),
            ("F4", "Edit", self._edit_in_active_pane),
            ("F5", "Copy", self._copy_from_active_pane),
            ("F6", "Move", self._move_from_active_pane),
            ("F7", "MkDir", self._mkdir_in_active_pane),
            ("F8", "Delete", self._delete_from_active_pane),
            ("Ctrl+R", "Refresh", self._refresh_active_pane),
            ("F9", "Terminal", self._toggle_terminal),
            ("F10", "Menu", self._show_main_menu),
            ("F11", "Layout", self._show_layout_menu),
            ("F12", "Jobs", self._toggle_jobs_view),
            ("Ctrl+Shift+V", "Thumbs", self._toggle_thumbnail_mode_in_active_pane),
        ]

    def _bind_shortcuts(self) -> None:
        self._next_pane_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Tab), self, activated=self._focus_next_pane)
        self._previous_pane_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Backtab), self, activated=self._focus_previous_pane
        )
        QShortcut(QKeySequence(Qt.Key.Key_F2), self, activated=self._rename_in_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F3), self, activated=self._toggle_passive_quick_view)
        QShortcut(QKeySequence(Qt.Key.Key_F4), self, activated=self._edit_in_active_pane)
        QShortcut(QKeySequence("Shift+F3"), self, activated=self._open_external_viewer)
        QShortcut(QKeySequence("Shift+F4"), self, activated=self._open_with_default_app)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self._toggle_quick_view_raw_mode)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._refresh_active_pane)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self._toggle_quick_view_ai_mode)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self._new_tab_in_active_pane)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self._close_tab_in_active_pane)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self._next_tab_in_active_pane)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self._previous_tab_in_active_pane)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, activated=self._toggle_thumbnail_mode_in_active_pane)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self._copy_selection_to_clipboard)
        QShortcut(QKeySequence.StandardKey.Cut, self, activated=self._cut_selection_to_clipboard)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste_clipboard_into_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self._copy_from_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F6), self, activated=self._move_from_active_pane)
        QShortcut(QKeySequence("Shift+F6"), self, activated=self._rename_in_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F7), self, activated=self._mkdir_in_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F8), self, activated=self._delete_from_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_from_active_pane)
        QShortcut(QKeySequence("Shift+F8"), self, activated=self._delete_from_active_pane_permanent)
        QShortcut(QKeySequence("Shift+Del"), self, activated=self._delete_from_active_pane_permanent)
        QShortcut(QKeySequence("Alt+1"), self, activated=self._apply_default_workspace_layout)
        QShortcut(QKeySequence("Alt+2"), self, activated=self._apply_focus_files_layout)
        QShortcut(QKeySequence("Alt+3"), self, activated=self._apply_focus_terminal_layout)
        QShortcut(QKeySequence("Alt+4"), self, activated=self._apply_terminal_right_layout)
        QShortcut(QKeySequence("Alt+5"), self, activated=self._apply_terminal_left_layout)
        QShortcut(QKeySequence("Alt+6"), self, activated=self._apply_balanced_layout)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._paste_active_filename_to_terminal)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._paste_active_filename_to_terminal)
        QShortcut(QKeySequence("Alt+Return"), self, activated=self._paste_active_full_path_to_terminal)
        QShortcut(QKeySequence("Alt+Enter"), self, activated=self._paste_active_full_path_to_terminal)
        QShortcut(QKeySequence("Alt+F1"), self, activated=self._show_drive_menu_for_active_pane)
        QShortcut(QKeySequence("Alt+F2"), self, activated=self._show_drive_menu_for_passive_pane)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._show_quick_filter_in_active_pane)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self._focus_pane_left)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self._focus_pane_right)
        QShortcut(QKeySequence("Alt+Up"), self, activated=self._focus_pane_up)
        QShortcut(QKeySequence("Alt+Down"), self, activated=self._focus_pane_down)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo_last_operation)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo_last_operation)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self._multi_rename_in_active_pane)
        QShortcut(QKeySequence("Alt+F7"), self, activated=self._find_files_in_active_pane)
        QShortcut(QKeySequence(Qt.Key.Key_F9), self, activated=self._toggle_terminal)
        QShortcut(QKeySequence(Qt.Key.Key_F10), self, activated=self._show_main_menu)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self._show_layout_menu)
        QShortcut(QKeySequence(Qt.Key.Key_F12), self, activated=self._toggle_jobs_view)
        QShortcut(QKeySequence("Ctrl+`"), self, activated=self._toggle_terminal)
        QShortcut(QKeySequence("Ctrl+Shift+`"), self, activated=self._toggle_terminal_maximized)
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, activated=self._force_kill_terminal_program)

    def _bind_job_signals(self) -> None:
        self.job_manager.job_changed.connect(self.jobs_view.upsert_snapshot)
        self.job_manager.job_removed.connect(self.jobs_view.remove_snapshot)
        self.jobs_view.cancel_requested.connect(self.job_manager.cancel_job)
        self.terminal_dock.maximize_requested.connect(self._toggle_terminal_maximized)
        self.terminal_dock.follow_active_pane_toggled.connect(self._set_follow_active_pane_terminal)
        self.terminal_dock.commands_changed.connect(self._persist_terminal_commands)
        self.terminal_dock.history_panel_visibility_changed.connect(self._persist_terminal_history_panel_visible)
        self.terminal_dock.experimental_pty_toggled.connect(self._persist_terminal_experimental_pty)

    def _persist_bookmarks(self, bookmarks: list[Path]) -> None:
        self.context.state.bookmarks = bookmarks
        persist_app_context(self.context)

    def _set_follow_active_pane_terminal(self, enabled: bool) -> None:
        self.context.config.follow_active_pane_terminal = enabled
        self.terminal_dock.set_follow_active_pane(enabled)
        if enabled:
            self._sync_terminal_to_pane_directory(self._active_pane(), self._active_pane().current_directory())
        persist_app_context(self.context)

    def _persist_terminal_commands(self, recent_commands: list[str], bookmarked_commands: list[str]) -> None:
        self.context.config.terminal.recent_commands = recent_commands
        self.context.config.terminal.bookmarked_commands = bookmarked_commands
        persist_app_context(self.context)

    def _persist_terminal_history_panel_visible(self, visible: bool) -> None:
        self.context.config.terminal.history_panel_visible = visible
        self._update_layout_chip()
        persist_app_context(self.context)

    def _persist_terminal_experimental_pty(self, enabled: bool) -> None:
        self.context.config.terminal.experimental_pty = enabled
        persist_app_context(self.context)

    def _apply_selected_theme(self) -> None:
        theme = resolve_theme_definition(
            self.context.config.theme.selected_theme_id,
            self.context.config.theme.custom_themes,
        )
        self._apply_theme_definition(theme)

    def _apply_theme_definition(self, theme) -> None:
        self.setStyleSheet(build_stylesheet(theme))
        palette = build_palette(theme)
        for pane_view in self.pane_views:
            pane_view.set_theme_palette(palette)
        self._update_clipboard_chip()

    def _edit_current_theme(self) -> None:
        selected_theme_id = self.context.config.theme.selected_theme_id
        current_theme = resolve_theme_definition(
            selected_theme_id,
            self.context.config.theme.custom_themes,
        )
        builtin_ids = {theme.id for theme in builtin_themes()}
        dialog = ThemeEditorDialog(
            parent=self,
            initial_theme=current_theme,
            available_themes=available_themes(self.context.config.theme.custom_themes),
            selected_theme_id=selected_theme_id,
        )
        dialog.preview_requested.connect(self._preview_theme_edit)
        if dialog.exec() != ThemeEditorDialog.DialogCode.Accepted:
            self._apply_selected_theme()
            return

        selected_existing_theme_id = dialog.selected_theme_id_for_save()
        if selected_existing_theme_id is not None:
            self.context.config.theme.selected_theme_id = selected_existing_theme_id
            self._apply_selected_theme()
            persist_app_context(self.context)
            return

        try:
            edited_theme = dialog.result_theme()
            build_palette(edited_theme)
        except ValueError as error:
            self._show_error("Invalid theme", str(error))
            return

        source_theme_id = dialog.current_source_theme_id()
        if edited_theme.id in builtin_ids:
            edited_theme = type(edited_theme)(
                id=f"{edited_theme.id}-custom",
                display_name=f"{edited_theme.display_name} Custom",
                font_family=edited_theme.font_family,
                font_size=edited_theme.font_size,
                window_bg=edited_theme.window_bg,
                surface_bg=edited_theme.surface_bg,
                surface_border=edited_theme.surface_border,
                text_primary=edited_theme.text_primary,
                text_muted=edited_theme.text_muted,
                accent=edited_theme.accent,
                accent_text=edited_theme.accent_text,
                button_bg=edited_theme.button_bg,
                input_bg=edited_theme.input_bg,
                warning=edited_theme.warning,
                warning_text=edited_theme.warning_text,
            )

        self.context.config.theme.custom_themes = [
            theme
            for theme in self.context.config.theme.custom_themes
            if theme.id not in {source_theme_id, edited_theme.id}
        ]
        self.context.config.theme.custom_themes.append(edited_theme)
        self.context.config.theme.selected_theme_id = edited_theme.id
        self._apply_selected_theme()
        persist_app_context(self.context)

    def _preview_theme_edit(self, preview_theme) -> None:
        try:
            build_palette(preview_theme)
        except ValueError:
            return
        self._apply_theme_definition(preview_theme)

    def _on_pane_activated(self, pane_view: PaneView) -> None:
        self._set_active_pane(self.pane_views.index(pane_view))

    def _set_active_pane(self, index: int) -> None:
        side_by_side_index = self._side_by_side_file_pane_index()
        if side_by_side_index is not None:
            index = side_by_side_index
        self.context.state.layout.active_pane_index = index
        for pane_index, pane_view in enumerate(self.pane_views):
            pane_view.set_active(pane_index == index)
        new_active = self._active_pane()
        # Route focus to the file list whenever a pane becomes active so
        # arrows / Enter / Space drive the cursor immediately. Skip if the
        # user is typing in the quick-filter bar (we don't want to steal
        # focus mid-keystroke) or if focus already sits on the file list.
        focused = QApplication.focusWidget()
        if focused is not new_active._quick_filter_bar and focused is not new_active.file_list:
            new_active.focus_list()
        self._sync_terminal_to_pane_directory(new_active, new_active.current_directory())
        self._sync_quick_view(new_active)

    def _sync_terminal_to_pane_directory(self, pane_view: PaneView, path: Path) -> None:
        if pane_view is not self._active_pane():
            return
        self.terminal_dock.sync_to_path(
            path,
            enabled=self.context.config.follow_active_pane_terminal,
        )

    def _focus_next_pane(self) -> None:
        side_by_side_index = self._side_by_side_file_pane_index()
        if side_by_side_index is not None:
            if self._terminal_has_focus():
                self._set_active_pane(side_by_side_index)
                self.pane_views[side_by_side_index].focus_list()
            else:
                self.terminal_dock.focus_input()
            return
        next_index = (self.context.state.layout.active_pane_index + 1) % len(self.pane_views)
        self._set_active_pane(next_index)
        self.pane_views[next_index].focus_list()

    def _focus_previous_pane(self) -> None:
        side_by_side_index = self._side_by_side_file_pane_index()
        if side_by_side_index is not None:
            if self._terminal_has_focus():
                self._set_active_pane(side_by_side_index)
                self.pane_views[side_by_side_index].focus_list()
            else:
                self.terminal_dock.focus_input()
            return
        next_index = (self.context.state.layout.active_pane_index - 1) % len(self.pane_views)
        self._set_active_pane(next_index)
        self.pane_views[next_index].focus_list()

    def _active_pane(self) -> PaneView:
        return self.pane_views[self.context.state.layout.active_pane_index]

    def _passive_pane(self) -> PaneView:
        return self.pane_views[(self.context.state.layout.active_pane_index + 1) % len(self.pane_views)]

    def _handle_operation_request(self, operation: str) -> None:
        handlers = {
            "refresh": self._refresh_active_pane,
            "copy": self._copy_from_active_pane,
            "move": self._move_from_active_pane,
            "rename": self._rename_in_active_pane,
            "mkdir": self._mkdir_in_active_pane,
            "delete": self._delete_from_active_pane,
        }
        handler = handlers.get(operation)
        if handler is not None:
            handler()

    def _refresh_active_pane(self) -> None:
        self._active_pane().refresh()

    def _new_tab_in_active_pane(self) -> None:
        self._active_pane().open_new_tab()

    def _close_tab_in_active_pane(self) -> None:
        self._active_pane().close_current_tab()

    def _next_tab_in_active_pane(self) -> None:
        self._active_pane().next_tab()

    def _previous_tab_in_active_pane(self) -> None:
        self._active_pane().previous_tab()

    def _open_tab_in_other_pane(self, source_pane: PaneView, path: Path) -> None:
        if source_pane not in self.pane_views:
            return
        source_index = self.pane_views.index(source_pane)
        target_index = (source_index + 1) % len(self.pane_views)
        self.pane_views[target_index].open_new_tab(path)

    def _toggle_thumbnail_mode_in_active_pane(self) -> None:
        self._active_pane().toggle_thumbnail_mode()

    def _show_help(self) -> None:
        show_message(
            parent=self,
            title="Help",
            message="Function key actions are available from the bottom bar and keyboard shortcuts.",
            level="info",
            accept_label="Close",
        )

    def _view_in_active_pane(self) -> None:
        self._toggle_passive_quick_view()

    def _edit_in_active_pane(self) -> None:
        path = self._active_pane().current_path()
        if path is None:
            return
        launch_editor(path)

    def _open_external_viewer(self) -> None:
        path = self._active_pane().current_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_with_default_app(self) -> None:
        path = self._active_pane().current_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_main_menu(self) -> None:
        menu = self._build_main_menu()
        popup_point = QCursor.pos()
        menu_size = menu.sizeHint()
        popup_point.setY(max(0, popup_point.y() - menu_size.height()))
        menu.exec(popup_point)

    def _build_main_menu(self) -> QMenu:
        """Build the F10/menu-bar menu organised by SPEC §5.4 sections."""
        menu = QMenu(self)

        file_menu = menu.addMenu("File")
        view_action = QAction("View (F3)", self)
        view_action.triggered.connect(self._toggle_passive_quick_view)
        file_menu.addAction(view_action)
        raw_view_action = QAction("View — Toggle Raw Source (Ctrl+Shift+R)", self)
        raw_view_action.triggered.connect(self._toggle_quick_view_raw_mode)
        file_menu.addAction(raw_view_action)
        web_view_action = QAction("View — Toggle Web Render (HTML)", self)
        web_view_action.triggered.connect(self._toggle_quick_view_web_mode)
        file_menu.addAction(web_view_action)
        edit_action = QAction("Edit (F4)", self)
        edit_action.triggered.connect(self._edit_in_active_pane)
        file_menu.addAction(edit_action)
        copy_action = QAction("Copy (F5)", self)
        copy_action.triggered.connect(self._copy_from_active_pane)
        file_menu.addAction(copy_action)
        move_action = QAction("Move (F6)", self)
        move_action.triggered.connect(self._move_from_active_pane)
        file_menu.addAction(move_action)
        rename_action = QAction("Rename (F2)", self)
        rename_action.triggered.connect(self._rename_in_active_pane)
        file_menu.addAction(rename_action)
        mkdir_action = QAction("New Directory (F7)", self)
        mkdir_action.triggered.connect(self._mkdir_in_active_pane)
        file_menu.addAction(mkdir_action)
        delete_action = QAction("Delete (F8)", self)
        delete_action.triggered.connect(self._delete_from_active_pane)
        file_menu.addAction(delete_action)

        mark_menu = menu.addMenu("Mark")
        mark_all_action = QAction("Mark All (Ctrl+A)", self)
        mark_all_action.triggered.connect(lambda: self._active_pane()._mark_all_entries())
        mark_menu.addAction(mark_all_action)
        clear_marks_action = QAction("Clear Marks (Esc)", self)
        clear_marks_action.triggered.connect(lambda: self._active_pane()._clear_marks())
        mark_menu.addAction(clear_marks_action)

        commands_menu = menu.addMenu("Commands")
        refresh_action = QAction("Refresh (Ctrl+R)", self)
        refresh_action.triggered.connect(self._refresh_active_pane)
        commands_menu.addAction(refresh_action)
        new_tab_action = QAction("New Tab (Ctrl+T)", self)
        new_tab_action.triggered.connect(self._new_tab_in_active_pane)
        commands_menu.addAction(new_tab_action)
        close_tab_action = QAction("Close Tab (Ctrl+W)", self)
        close_tab_action.triggered.connect(self._close_tab_in_active_pane)
        commands_menu.addAction(close_tab_action)

        show_menu = menu.addMenu("Show")
        terminal_action = QAction("Toggle Terminal (F9)", self)
        terminal_action.triggered.connect(self._toggle_terminal)
        show_menu.addAction(terminal_action)
        layout_action = QAction("Layout… (F11)", self)
        layout_action.triggered.connect(self._show_layout_menu)
        show_menu.addAction(layout_action)
        jobs_action = QAction("Jobs (F12)", self)
        jobs_action.triggered.connect(self._toggle_jobs_view)
        show_menu.addAction(jobs_action)
        thumbs_action = QAction("Toggle Thumbnails (Ctrl+Shift+V)", self)
        thumbs_action.triggered.connect(self._toggle_thumbnail_mode_in_active_pane)
        show_menu.addAction(thumbs_action)

        return menu

    def _show_layout_menu(self) -> None:
        menu = QMenu(self)
        active_preset = self._active_layout_preset()

        default_layout_action = QAction("Default Workspace Layout", self)
        default_layout_action.setCheckable(True)
        default_layout_action.setChecked(active_preset == "default")
        default_layout_action.triggered.connect(self._apply_default_workspace_layout)
        menu.addAction(default_layout_action)

        focus_files_action = QAction("Focus Files", self)
        focus_files_action.setCheckable(True)
        focus_files_action.setChecked(active_preset == "focus_files")
        focus_files_action.triggered.connect(self._apply_focus_files_layout)
        menu.addAction(focus_files_action)

        focus_terminal_action = QAction("Focus Terminal", self)
        focus_terminal_action.setCheckable(True)
        focus_terminal_action.setChecked(active_preset == "focus_terminal")
        focus_terminal_action.triggered.connect(self._apply_focus_terminal_layout)
        menu.addAction(focus_terminal_action)

        terminal_right_action = QAction("Terminal Right", self)
        terminal_right_action.setCheckable(True)
        terminal_right_action.setChecked(active_preset == "terminal_right")
        terminal_right_action.triggered.connect(self._apply_terminal_right_layout)
        menu.addAction(terminal_right_action)

        terminal_left_action = QAction("Terminal Left", self)
        terminal_left_action.setCheckable(True)
        terminal_left_action.setChecked(active_preset == "terminal_left")
        terminal_left_action.triggered.connect(self._apply_terminal_left_layout)
        menu.addAction(terminal_left_action)

        balanced_action = QAction("Balanced", self)
        balanced_action.setCheckable(True)
        balanced_action.setChecked(active_preset == "balanced")
        balanced_action.triggered.connect(self._apply_balanced_layout)
        menu.addAction(balanced_action)

        review_mode_action = QAction("Review Mode", self)
        review_mode_action.setCheckable(True)
        review_mode_action.setChecked(active_preset == "review_mode")
        review_mode_action.triggered.connect(self._apply_review_mode_layout)
        menu.addAction(review_mode_action)

        menu.addSeparator()

        reset_terminal_split_action = QAction("Reset Main Split", self)
        reset_terminal_split_action.triggered.connect(self._reset_main_split)
        menu.addAction(reset_terminal_split_action)

        equalize_panes_action = QAction("Equalize File Panes", self)
        equalize_panes_action.triggered.connect(self._equalize_file_panes)
        menu.addAction(equalize_panes_action)

        terminal_full_screen_label = (
            "Exit Terminal Full Screen"
            if self.context.state.layout.terminal_maximized
            else "Terminal Full Screen"
        )
        toggle_terminal_full_screen_action = QAction(terminal_full_screen_label, self)
        toggle_terminal_full_screen_action.triggered.connect(self._toggle_terminal_maximized)
        menu.addAction(toggle_terminal_full_screen_action)

        commands_panel_label = (
            "Hide Commands Panel" if self.context.config.terminal.history_panel_visible else "Show Commands Panel"
        )
        toggle_commands_panel_action = QAction(commands_panel_label, self)
        toggle_commands_panel_action.triggered.connect(self._toggle_terminal_commands_panel)
        menu.addAction(toggle_commands_panel_action)

        popup_point = QCursor.pos()
        menu_size = menu.sizeHint()
        popup_point.setY(max(0, popup_point.y() - menu_size.height()))
        menu.exec(popup_point)

    def _apply_default_workspace_layout(self) -> None:
        self._apply_layout_mode("stacked", persist=False)
        self._set_terminal_maximized(False, persist=False)
        self._equalize_file_panes(persist=False)
        self._reset_main_split(persist=False)
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        self.terminal_dock.set_history_panel_visible(False)
        persist_app_context(self.context)

    def _apply_focus_files_layout(self) -> None:
        self._apply_layout_mode("stacked", persist=False)
        self._set_terminal_maximized(False, persist=False)
        self._equalize_file_panes(persist=False)
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        if self.content_splitter is not None:
            self.content_splitter.setSizes([900, 120])
        self.terminal_dock.set_history_panel_visible(False)
        persist_app_context(self.context)

    def _apply_focus_terminal_layout(self) -> None:
        self._apply_layout_mode("stacked", persist=False)
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        self.terminal_dock.set_history_panel_visible(True)
        self._set_terminal_maximized(True)

    def _apply_terminal_right_layout(self) -> None:
        self._apply_layout_mode("terminal_right")

    def _apply_terminal_left_layout(self) -> None:
        self._apply_layout_mode("terminal_left")

    def _apply_balanced_layout(self) -> None:
        self._apply_layout_mode("stacked", persist=False)
        self._set_terminal_maximized(False, persist=False)
        self._equalize_file_panes(persist=False)
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        if self.content_splitter is not None:
            self.content_splitter.setSizes([760, 260])
        self.terminal_dock.set_history_panel_visible(True)
        persist_app_context(self.context)

    def _apply_review_mode_layout(self) -> None:
        self._apply_layout_mode("stacked", persist=False)
        self._set_terminal_maximized(False, persist=False)
        self._equalize_file_panes(persist=False)
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        if self.content_splitter is not None:
            self.content_splitter.setSizes([640, 380])
        self.terminal_dock.set_history_panel_visible(True)
        persist_app_context(self.context)

    def _reset_main_split(self, *, persist: bool = True) -> None:
        if self.context.state.layout.layout_mode != "stacked":
            self._apply_layout_mode("stacked", persist=False)
        if self.content_splitter is not None:
            self.content_splitter.setSizes([760, 260])
        if persist:
            persist_app_context(self.context)

    def _equalize_file_panes(self, *, persist: bool = True) -> None:
        if self.context.state.layout.layout_mode != "stacked":
            self._apply_layout_mode("stacked", persist=False)
        if self.pane_splitter is not None:
            self.pane_splitter.setSizes([1000, 1000])
        if persist:
            persist_app_context(self.context)

    def _toggle_terminal_commands_panel(self) -> None:
        visible = self.context.config.terminal.history_panel_visible
        self.terminal_dock.set_history_panel_visible(not visible)

    def _active_layout_preset(self) -> str | None:
        if self.context.state.layout.layout_mode == "terminal_right":
            return "terminal_right"
        if self.context.state.layout.layout_mode == "terminal_left":
            return "terminal_left"
        if self.context.state.layout.terminal_maximized:
            return "focus_terminal" if self.context.config.terminal.history_panel_visible else None

        pane_share = self._secondary_splitter_share(self.pane_splitter)
        terminal_share = self._secondary_splitter_share(self.content_splitter)
        history_visible = self.context.config.terminal.history_panel_visible

        if pane_share is None or terminal_share is None:
            return None

        pane_is_balanced = abs(pane_share - 0.5) <= 0.08
        if not pane_is_balanced or not self.terminal_dock.isVisible():
            return None

        if not history_visible and abs(terminal_share - 0.12) <= 0.04:
            return "focus_files"
        if not history_visible and abs(terminal_share - 0.26) <= 0.05:
            return "default"
        if history_visible and abs(terminal_share - 0.26) <= 0.05:
            return "balanced"
        if history_visible and abs(terminal_share - 0.37) <= 0.06:
            return "review_mode"
        return None

    @staticmethod
    def _secondary_splitter_share(splitter: QSplitter | None) -> float | None:
        if splitter is None:
            return None
        sizes = splitter.sizes()
        total = sum(sizes)
        if total <= 0 or len(sizes) < 2:
            return None
        return sizes[1] / total

    def _is_side_by_side_layout(self) -> bool:
        return self.context.state.layout.layout_mode in {"terminal_left", "terminal_right"}

    def _side_by_side_file_pane_index(self) -> int | None:
        if self.context.state.layout.layout_mode == "terminal_right":
            return 0
        if self.context.state.layout.layout_mode == "terminal_left":
            return 1
        return None

    def _update_layout_chip(self) -> None:
        preset = self._active_layout_preset()
        labels = {
            "default": "Layout: Default",
            "focus_files": "Layout: Focus Files",
            "focus_terminal": "Layout: Focus Terminal",
            "terminal_right": "Layout: Terminal Right",
            "terminal_left": "Layout: Terminal Left",
            "balanced": "Layout: Balanced",
            "review_mode": "Layout: Review Mode",
        }
        label = labels.get(preset, "Layout: Custom")
        self.layout_chip.setText(label)
        self.layout_chip.setToolTip(label)

    def _apply_layout_mode(self, mode: str, *, persist: bool = True) -> None:
        target_mode = mode if mode in {"terminal_left", "terminal_right"} else "stacked"
        current_mode = self.context.state.layout.layout_mode

        if target_mode in {"terminal_left", "terminal_right"}:
            if self.context.state.layout.terminal_maximized:
                self._set_terminal_maximized(False, persist=False)
            if current_mode != target_mode:
                self._side_by_side_previous_active_pane_index = self.context.state.layout.active_pane_index
                if self.content_splitter is not None:
                    self.context.state.layout.content_splitter_sizes = self.content_splitter.sizes()
                if self.pane_splitter is not None and not self._is_side_by_side_layout():
                    self.context.state.layout.pane_splitter_sizes = self.pane_splitter.sizes()
            if self.content_splitter is not None and self.content_splitter.widget(1) is self.terminal_dock:
                self.content_splitter.replaceWidget(1, self.terminal_placeholder)
                self.terminal_placeholder.setVisible(False)
                self.content_splitter.handle(1).setVisible(False)
                self.content_splitter.setSizes([1, 0])
            if self.pane_splitter is not None:
                terminal_index = 1 if target_mode == "terminal_right" else 0
                if current_mode in {"terminal_left", "terminal_right"} and current_mode != target_mode:
                    current_terminal_index = 1 if current_mode == "terminal_right" else 0
                    if self.pane_splitter.widget(current_terminal_index) is self.terminal_dock:
                        self.pane_splitter.replaceWidget(
                            current_terminal_index,
                            self.pane_views[current_terminal_index],
                        )
                if self.pane_splitter.widget(terminal_index) is not self.terminal_dock:
                    self.pane_splitter.replaceWidget(terminal_index, self.terminal_dock)
            self.terminal_dock.set_side_by_side_mode(True)
            if target_mode == "terminal_right":
                self.pane_views[0].setVisible(True)
                self.pane_views[1].setVisible(False)
            else:
                self.pane_views[0].setVisible(False)
                self.pane_views[1].setVisible(True)
            if not self.terminal_dock.isVisible():
                self.terminal_dock.setVisible(True)
            if self.pane_splitter is not None:
                side_sizes = self.context.state.layout.side_by_side_splitter_sizes or [1000, 1000]
                self.pane_splitter.setSizes(side_sizes)
            self.context.state.layout.layout_mode = target_mode
            self._set_active_pane(self._side_by_side_file_pane_index() or 0)
            self._update_layout_chip()
            if persist:
                persist_app_context(self.context)
            return

        if self.pane_splitter is not None and self.terminal_dock.parent() is self.pane_splitter:
            self.context.state.layout.side_by_side_splitter_sizes = self.pane_splitter.sizes()
            terminal_index = self.pane_splitter.indexOf(self.terminal_dock)
            if terminal_index >= 0:
                self.pane_splitter.replaceWidget(terminal_index, self.pane_views[terminal_index])
        self.terminal_dock.set_side_by_side_mode(False)
        if self.content_splitter is not None and self.content_splitter.widget(1) is not self.terminal_dock:
            self.terminal_placeholder.setVisible(True)
            self.content_splitter.replaceWidget(1, self.terminal_dock)
            self.content_splitter.handle(1).setVisible(True)
        self.pane_views[0].setVisible(True)
        self.pane_views[1].setVisible(True)
        self.context.state.layout.layout_mode = "stacked"
        if self.pane_splitter is not None and self.context.state.layout.pane_splitter_sizes:
            self.pane_splitter.setSizes(self.context.state.layout.pane_splitter_sizes)
        if self.content_splitter is not None and self.context.state.layout.content_splitter_sizes:
            self.content_splitter.setSizes(self.context.state.layout.content_splitter_sizes)
        restored_index = min(self._side_by_side_previous_active_pane_index, len(self.pane_views) - 1)
        self._set_active_pane(restored_index)
        self._update_layout_chip()
        if persist:
            persist_app_context(self.context)

    def _toggle_passive_quick_view(self) -> None:
        preview_pane = self._passive_pane()
        preview_pane.set_quick_view_enabled(not preview_pane.is_quick_view_enabled())
        if preview_pane.is_quick_view_enabled():
            self._sync_quick_view(self._active_pane())
        else:
            preview_pane.set_quick_view_source(None)

    def _toggle_quick_view_raw_mode(self) -> None:
        preview_pane = self._passive_pane()
        if not preview_pane.is_quick_view_enabled():
            self._show_passive_quick_view()
        preview_pane.quick_view.toggle_raw_mode()

    def _toggle_quick_view_web_mode(self) -> None:
        preview_pane = self._passive_pane()
        if not preview_pane.is_quick_view_enabled():
            self._show_passive_quick_view()
        preview_pane.quick_view.toggle_web_mode()

    def _show_passive_quick_view(self) -> None:
        preview_pane = self._passive_pane()
        if not preview_pane.is_quick_view_enabled():
            preview_pane.set_quick_view_enabled(True)
        self._sync_quick_view(self._active_pane())

    def _sync_quick_view(self, source_pane: PaneView) -> None:
        if source_pane is not self._active_pane():
            return
        preview_pane = self._passive_pane()
        if not preview_pane.is_quick_view_enabled():
            return
        preview_pane.set_quick_view_ai_runtime(
            self._get_or_create_ai_runner(),
            self._make_pane_roots(),
        )
        preview_pane.set_quick_view_source(source_pane.preview_path())

    def _get_or_create_ai_runner(self) -> AgentRunner | None:
        if self._ai_runner is None:
            try:
                self._ai_runner = AgentRunner(self.context.config.ai, parent=self)
            except Exception:  # noqa: BLE001
                return None
        return self._ai_runner

    def _make_pane_roots(self) -> PaneRoots | None:
        if len(self.pane_views) < 2:
            return None
        try:
            return PaneRoots(
                left=self.pane_views[0].current_directory(),
                right=self.pane_views[1].current_directory(),
            )
        except Exception:  # noqa: BLE001
            return None

    def _toggle_quick_view_ai_mode(self) -> None:
        preview_pane = self._passive_pane()
        if not preview_pane.is_quick_view_enabled():
            self._show_passive_quick_view()
        preview_pane.quick_view.toggle_ai_mode()

    def _on_ai_badges_changed(self, paths: frozenset) -> None:
        self._active_pane().set_ai_processing_paths(paths)

    def _copy_from_active_pane(self) -> None:
        self._run_transfer("copy")

    def _move_from_active_pane(self) -> None:
        self._run_transfer("move")

    def _copy_selection_to_clipboard(self) -> None:
        if self._terminal_has_focus():
            self.terminal_dock.copy_selected_text()
            return
        self._stage_active_selection_for_paste("copy")

    def _force_kill_terminal_program(self) -> None:
        if not self._terminal_has_focus():
            return
        self.terminal_dock.force_kill_current_program()

    def _cut_selection_to_clipboard(self) -> None:
        if self._terminal_has_focus():
            self.terminal_dock.cut_selected_text()
            return
        self._stage_active_selection_for_paste("move")

    def _stage_active_selection_for_paste(self, operation: str) -> None:
        paths = self._active_pane().selected_paths()
        if not paths:
            return
        self._clipboard_paths = list(paths)
        self._clipboard_operation = operation
        self._update_clipboard_chip()

    def _paste_clipboard_into_active_pane(self) -> None:
        if self._terminal_has_focus():
            self.terminal_dock.paste_to_input()
            return
        if not self._clipboard_paths or self._clipboard_operation is None:
            return

        destination_dir = self._active_pane().current_directory()
        conflict_policy = "ask"
        if self._clipboard_operation == "copy" and all(
            path.parent == destination_dir for path in self._clipboard_paths
        ):
            conflict_policy = "keep_both"

        self._start_transfer_operation(
            operation=self._clipboard_operation,
            source_paths=list(self._clipboard_paths),
            destination_dir=destination_dir,
            conflict_policy=conflict_policy,
            clear_clipboard_on_success=self._clipboard_operation == "move",
        )

    def _terminal_has_focus(self) -> bool:
        focus_widget = QApplication.focusWidget()
        return focus_widget is not None and self.terminal_dock.isAncestorOf(focus_widget)

    def _on_focus_changed(self, _old, _now) -> None:
        self._update_terminal_tab_shortcuts()

    def _update_terminal_tab_shortcuts(self) -> None:
        enabled = not self._terminal_has_focus() or self._is_side_by_side_layout()
        if self._next_pane_shortcut is not None:
            self._next_pane_shortcut.setEnabled(enabled)
        if self._previous_pane_shortcut is not None:
            self._previous_pane_shortcut.setEnabled(enabled)

    def _run_transfer(self, operation: str) -> None:
        source_pane = self._active_pane()
        destination_pane = self._passive_pane()
        source_paths = source_pane.selected_paths()
        if not source_paths:
            return

        self._run_transfer_request(
            operation=operation,
            source_paths=source_paths,
            default_destination=destination_pane.current_directory(),
        )

    def _handle_drag_drop_request(
        self,
        source_paths: list[Path],
        destination_dir: Path,
        modifiers: int,
    ) -> None:
        QTimer.singleShot(
            0,
            lambda: self._run_drag_drop_request(
                source_paths=list(source_paths),
                destination_dir=destination_dir,
                modifiers=modifiers,
            ),
        )

    def _run_drag_drop_request(
        self,
        *,
        source_paths: list[Path],
        destination_dir: Path,
        modifiers: int,
    ) -> None:
        if not source_paths:
            return
        if all(path.parent == destination_dir for path in source_paths):
            return

        operation = determine_drag_drop_operation(
            source_paths,
            destination_dir,
            Qt.KeyboardModifier(modifiers),
        )
        self._start_transfer_operation(
            operation=operation,
            source_paths=source_paths,
            destination_dir=destination_dir,
            conflict_policy="ask",
        )

    def _run_transfer_request(
        self,
        *,
        operation: str,
        source_paths: list[Path],
        default_destination: Path,
    ) -> None:
        if not source_paths:
            return

        dialog = TransferDialog(
            operation=operation,
            source_paths=source_paths,
            default_destination=default_destination,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self._start_transfer_operation(
            operation=operation,
            source_paths=source_paths,
            destination_dir=dialog.destination_directory(),
            conflict_policy=dialog.conflict_policy(),
        )

    def _start_transfer_operation(
        self,
        *,
        operation: str,
        source_paths: list[Path],
        destination_dir: Path,
        conflict_policy: str,
        clear_clipboard_on_success: bool = False,
    ) -> None:
        if not destination_dir.exists() or not destination_dir.is_dir():
            self._show_error(
                f"{operation.title()} failed",
                f"Destination directory does not exist:\n{destination_dir}",
            )
            return

        actions: list[FileJobAction] = []
        for source_path in source_paths:
            destination_path = destination_dir / source_path.name
            if (
                operation == "copy"
                and conflict_policy == "keep_both"
                and source_path.parent == destination_dir
            ):
                destination_path = self._unique_destination_path(destination_path)
            if source_path == destination_path:
                self._show_error(
                    f"{operation.title()} failed",
                    f"Source and destination are the same:\n{source_path}",
                )
                continue

            replace_existing = False
            if destination_path.exists():
                destination_path, replace_existing = self._resolve_conflict(
                    source_path=source_path,
                    destination_path=destination_path,
                    conflict_policy=conflict_policy,
                    operation=operation,
                )
                if destination_path is None:
                    continue

            actions.append(
                FileJobAction(
                    operation=operation,
                    source=source_path,
                    destination=destination_path,
                    replace_existing=replace_existing,
                )
            )

        if not actions:
            return

        self.job_manager.start_file_job(
            parent=self,
            title=f"{operation.title()} {len(actions)} item(s) -> {destination_dir}",
            actions=actions,
            on_finished=lambda result: self._on_file_job_finished(
                result=result,
                success_title=operation.title(),
                clear_clipboard_on_success=clear_clipboard_on_success,
            ),
        )

    def _rename_in_active_pane(self) -> None:
        pane = self._active_pane()
        paths = pane.selected_paths()
        if not paths:
            return
        if len(paths) > 1:
            self._show_error("Rename failed", "Rename currently supports one item at a time.")
            return

        source_path = paths[0]
        dialog = TextEntryDialog(
            parent=self,
            title="Rename Item",
            subtitle=f"Rename {source_path.name} in place.",
            field_label="New name",
            initial_value=source_path.name,
            accept_label="Rename",
            hint="Only the name changes. The item stays in the current folder.",
        )
        if dialog.exec() != TextEntryDialog.DialogCode.Accepted:
            return

        new_name = dialog.value().strip()
        if not new_name or new_name == source_path.name:
            return

        destination_path = source_path.with_name(new_name)
        if destination_path.exists():
            self._show_error(
                "Rename failed",
                f"An item named '{new_name}' already exists in this folder.",
            )
            return

        try:
            self.fs.rename_entry(source_path, destination_path)
        except OSError as exc:
            self._show_error("Rename failed", f"{source_path}\n\n{exc}")
            return

        self.undo_stack.push(UndoRecord(kind="rename", source=source_path, destination=destination_path))
        pane.refresh()
        pane.focus_list()

    def _resolve_conflict(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        conflict_policy: str,
        operation: str,
    ) -> tuple[Path | None, bool]:
        if conflict_policy == "overwrite":
            return destination_path, True
        if conflict_policy == "skip":
            return None, False
        if conflict_policy == "keep_both":
            return self._unique_destination_path(destination_path), False
        if self._confirm_overwrite(destination_path):
            return destination_path, True
        return None, False

    def _unique_destination_path(self, destination_path: Path) -> Path:
        stem = destination_path.stem
        suffix = destination_path.suffix
        parent = destination_path.parent
        counter = 2
        candidate = destination_path
        while candidate.exists():
            candidate = parent / f"{stem} ({counter}){suffix}"
            counter += 1
        return candidate

    def _mkdir_in_active_pane(self) -> None:
        pane = self._active_pane()
        dialog = TextEntryDialog(
            parent=self,
            title="Create Folder",
            subtitle=f"Create a new folder in {pane.current_directory()}.",
            field_label="Folder name",
            initial_value="NewFolder",
            accept_label="Create Folder",
            hint="Press Enter to create it immediately.",
        )
        if dialog.exec() != TextEntryDialog.DialogCode.Accepted:
            return

        name = dialog.value().strip()
        if not name:
            return

        path = pane.current_directory() / name
        try:
            self.fs.mkdir(path)
        except OSError as exc:
            self._show_error("Create directory failed", f"{path}\n\n{exc}")
            return

        pane.refresh()
        pane.focus_list()

    def _delete_from_active_pane(self, *, bypass_trash: bool = False) -> None:
        pane = self._active_pane()
        paths = pane.selected_paths()
        if not paths:
            return

        names = "\n".join(path.name for path in paths[:8])
        if len(paths) > 8:
            names += f"\n... and {len(paths) - 8} more"

        if bypass_trash:
            title = "Permanently Delete Items"
            message = (
                f"PERMANENTLY delete {len(paths)} item(s)? "
                f"This bypasses the Recycle Bin and cannot be undone.\n\n{names}"
            )
            accept = "Permanently Delete"
            job_title = f"Permanently delete {len(paths)} item(s)"
            success_title = "Permanent delete"
        else:
            title = "Move Items To Recycle Bin"
            message = f"Send {len(paths)} item(s) to the Recycle Bin?\n\n{names}"
            accept = "Move To Recycle Bin"
            job_title = f"Delete {len(paths)} item(s)"
            success_title = "Delete"

        confirmed = ask_confirmation(
            parent=self,
            title=title,
            message=message,
            accept_label=accept,
            cancel_label="Keep Items",
            is_destructive=True,
        )
        if not confirmed:
            return

        self.job_manager.start_file_job(
            parent=self,
            title=job_title,
            actions=[
                FileJobAction(operation="delete", source=path, bypass_trash=bypass_trash)
                for path in paths
            ],
            on_finished=lambda result: self._on_file_job_finished(
                result=result,
                success_title=success_title,
            ),
        )

    def _delete_from_active_pane_permanent(self) -> None:
        self._delete_from_active_pane(bypass_trash=True)

    def _show_quick_filter_in_active_pane(self) -> None:
        self._active_pane().show_quick_filter()

    def _focus_pane_in_direction(self, direction: str) -> None:
        """Focus the pane spatially nearest to the active pane in `direction`.

        `direction` is one of "left", "right", "up", "down". Picks the pane
        whose centre lies furthest in `direction` from the active pane,
        breaking ties by perpendicular distance. No-op if no pane qualifies.
        """
        if not self.pane_views:
            return
        active_index = self.context.state.layout.active_pane_index
        if not (0 <= active_index < len(self.pane_views)):
            return
        active = self.pane_views[active_index]
        if not active.isVisible():
            return
        active_center = active.mapToGlobal(active.rect().center())

        best_index: int | None = None
        best_score: tuple[int, int] | None = None
        for index, pane in enumerate(self.pane_views):
            if index == active_index or not pane.isVisible():
                continue
            center = pane.mapToGlobal(pane.rect().center())
            dx = center.x() - active_center.x()
            dy = center.y() - active_center.y()
            if direction == "left" and dx >= 0:
                continue
            if direction == "right" and dx <= 0:
                continue
            if direction == "up" and dy >= 0:
                continue
            if direction == "down" and dy <= 0:
                continue
            score = (
                abs(dy if direction in ("left", "right") else dx),
                abs(dx if direction in ("left", "right") else dy),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_index = index

        if best_index is None:
            return
        self._set_active_pane(best_index)
        self.pane_views[best_index].focus_list()

    def _find_files_in_active_pane(self) -> None:
        pane = self._active_pane()
        root = pane.active_tab.path
        dialog = FindFilesDialog(
            root,
            parent=self,
            on_open=self._open_search_result,
        )
        dialog.exec()

    def _open_search_result(self, path: Path) -> None:
        if not path.exists():
            return
        target_dir = path.parent if path.is_file() else path
        pane = self._active_pane()
        pane.navigate_to(target_dir)

    def _multi_rename_in_active_pane(self) -> None:
        pane = self._active_pane()
        paths = pane.selected_paths()
        if not paths:
            return
        dialog = MultiRenameDialog(paths, parent=self)
        if dialog.exec() != MultiRenameDialog.DialogCode.Accepted:
            return
        previews = dialog.previews()
        succeeded, errors = apply_renames(
            previews,
            rename=self.fs.rename_entry,
            on_record=lambda src, dst: self.undo_stack.push(
                UndoRecord(kind="rename", source=src, destination=dst)
            ),
        )
        pane.refresh()
        if errors:
            self._show_error(
                "Multi-rename completed with errors",
                f"Renamed {succeeded} item(s).\n\n" + "\n".join(errors[:10]),
            )

    def _undo_last_operation(self) -> None:
        record = self.undo_stack.pop()
        if record is None:
            show_message(
                parent=self,
                title="Undo",
                message="Nothing to undo.",
                level="info",
                accept_label="Close",
            )
            return
        # invert: move destination back to source
        if not record.destination.exists():
            self._show_error(
                "Undo failed",
                f"Cannot undo {record.kind}: {record.destination} no longer exists.",
            )
            return
        if record.source.exists():
            self._show_error(
                "Undo failed",
                f"Cannot undo {record.kind}: {record.source} now exists.",
            )
            return
        try:
            self.fs.rename_entry(record.destination, record.source)
        except OSError as exc:
            self._show_error("Undo failed", f"{record.destination} -> {record.source}\n\n{exc}")
            return
        for pane in self.pane_views:
            pane.refresh()

    def _focus_pane_left(self) -> None:
        self._focus_pane_in_direction("left")

    def _focus_pane_right(self) -> None:
        self._focus_pane_in_direction("right")

    def _focus_pane_up(self) -> None:
        self._focus_pane_in_direction("up")

    def _focus_pane_down(self) -> None:
        self._focus_pane_in_direction("down")

    def _show_drive_menu_for_active_pane(self) -> None:
        self._show_drive_menu(self._active_pane())

    def _show_drive_menu_for_passive_pane(self) -> None:
        self._show_drive_menu(self._passive_pane())

    def _show_drive_menu(self, target_pane: PaneView) -> None:
        menu = QMenu(self)
        menu.setTitle(root_section_label())
        for path in root_paths():
            label = str(path)
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, p=path, pane=target_pane: pane.navigate_to(p))
            menu.addAction(action)
        if not menu.actions():
            return
        menu.exec(QCursor.pos())

    def _paste_active_filename_to_terminal(self) -> None:
        path = self._active_pane().current_path()
        if path is None:
            return
        self._inject_into_terminal(self._shell_quote(path.name))

    def _paste_active_full_path_to_terminal(self) -> None:
        path = self._active_pane().current_path()
        if path is None:
            return
        self._inject_into_terminal(self._shell_quote(str(path)))

    def _inject_into_terminal(self, text: str) -> None:
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        self.terminal_dock.focus_input()
        self.terminal_dock.output.inject_command(text + " ", run=False)

    @staticmethod
    def _shell_quote(text: str) -> str:
        if any(ch.isspace() for ch in text) or any(ch in text for ch in '"\'\\$`!&|;<>(){}[]*?'):
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return text

    def _confirm_overwrite(self, destination_path: Path) -> bool:
        return ask_confirmation(
            parent=self,
            title="Replace Existing Item",
            message=f"{destination_path.name} already exists in the target pane.\n\nReplace the existing item?",
            accept_label="Replace Existing",
            cancel_label="Keep Existing",
            is_destructive=True,
        )

    def _show_error(self, title: str, message: str) -> None:
        show_message(
            parent=self,
            title=title,
            message=message,
            level="error",
            accept_label="Close",
        )

    def _on_file_job_finished(
        self,
        *,
        result: FileJobResult,
        success_title: str,
        clear_clipboard_on_success: bool = False,
    ) -> None:
        self._active_pane().refresh()
        self._passive_pane().refresh()
        self._active_pane().focus_list()

        if clear_clipboard_on_success and not result.errors and not result.cancelled:
            self._clipboard_paths = []
            self._clipboard_operation = None
            self._update_clipboard_chip()

        if result.cancelled:
            message = (
                f"Processed {result.processed_actions} item(s) and completed "
                f"{result.completed_actions} successfully before cancellation."
            )
            if result.errors:
                details = "\n".join(result.errors[:8])
                if len(result.errors) > 8:
                    details += f"\n... and {len(result.errors) - 8} more"
                show_message(
                    parent=self,
                    title=f"{success_title} Cancelled With Errors",
                    message=message,
                    details=details,
                    level="warning",
                    accept_label="Close",
                )
                return

            show_message(
                parent=self,
                title=f"{success_title} Cancelled",
                message=message,
                level="info",
                accept_label="Close",
            )
            return

        if result.errors:
            message = "\n".join(result.errors[:8])
            if len(result.errors) > 8:
                message += f"\n... and {len(result.errors) - 8} more"
            self._show_error(
                f"{success_title} completed with errors",
                message,
            )
        

    def _update_clipboard_chip(self) -> None:
        cut_paths = self._clipboard_paths if self._clipboard_operation == "move" else []
        for pane_view in self.pane_views:
            pane_view.set_cut_pending_paths(cut_paths)

        if not self._clipboard_paths or self._clipboard_operation is None:
            self.clipboard_chip.setVisible(False)
            return

        verb = "Copy" if self._clipboard_operation == "copy" else "Move"
        count = len(self._clipboard_paths)
        self.clipboard_chip.setText(f"Clipboard: {verb} {count} item(s)")
        self.clipboard_chip.setProperty("cutMode", self._clipboard_operation == "move")
        self.clipboard_chip.style().unpolish(self.clipboard_chip)
        self.clipboard_chip.style().polish(self.clipboard_chip)
        self.clipboard_chip.setVisible(True)

    def _toggle_jobs_view(self) -> None:
        if self.context.state.layout.terminal_maximized:
            return
        self.jobs_view.setVisible(not self.jobs_view.isVisible())

    def _toggle_terminal(self) -> None:
        if self._is_side_by_side_layout():
            self._apply_layout_mode("stacked", persist=False)
        self.terminal_dock.toggle_visible()
        if not self.terminal_dock.isVisible() and self.context.state.layout.terminal_maximized:
            self._set_terminal_maximized(False)

    def _focus_terminal(self) -> None:
        if not self.terminal_dock.isVisible():
            self.terminal_dock.setVisible(True)
        self.terminal_dock.focus_input()

    def _toggle_terminal_maximized(self) -> None:
        if self._is_side_by_side_layout():
            self._apply_layout_mode("stacked", persist=False)
        self._set_terminal_maximized(not self.context.state.layout.terminal_maximized)

    def _set_terminal_maximized(self, maximized: bool, *, persist: bool = True) -> None:
        if self.context.state.layout.terminal_maximized == maximized and self.root_layout is not None:
            self.terminal_dock.set_maximized(maximized)
            return

        if maximized:
            self._jobs_visible_before_terminal_maximize = self.jobs_view.isVisible()

        self.context.state.layout.terminal_maximized = maximized
        self.terminal_dock.setVisible(True)
        self.terminal_dock.set_maximized(maximized)
        self._update_layout_chip()

        if self.panes_host is not None:
            self.panes_host.setVisible(not maximized)
        self.jobs_view.setVisible(False if maximized else self._jobs_visible_before_terminal_maximize)
        if self.function_bar is not None:
            self.function_bar.setVisible(not maximized)

        if self.root_layout is not None:
            self.root_layout.setStretch(0, 1)
            self.root_layout.setStretch(1, 0)
            self.root_layout.setStretch(2, 0)

        if maximized:
            self.terminal_dock.focus_input()

        if persist:
            persist_app_context(self.context)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.isMaximized():
            normal = self.normalGeometry()
            self.context.state.window.width = max(1000, normal.width())
            self.context.state.window.height = max(700, normal.height())
        else:
            self.context.state.window.width = self.width()
            self.context.state.window.height = self.height()
        self.context.state.window.is_maximized = self.isMaximized()
        if self.pane_splitter is not None:
            if self._is_side_by_side_layout():
                self.context.state.layout.side_by_side_splitter_sizes = self.pane_splitter.sizes()
            else:
                self.context.state.layout.pane_splitter_sizes = self.pane_splitter.sizes()
        if self.content_splitter is not None and not self._is_side_by_side_layout():
            self.context.state.layout.content_splitter_sizes = self.content_splitter.sizes()
        persist_app_context(self.context)
        self.terminal_dock.close_session()
        super().closeEvent(event)


_MAIN_WINDOW_STYLESHEET = """
QMainWindow {
    background: #0b1220;
}
QFrame#topBar,
QFrame#functionKeyBar,
QFrame#pane,
QFrame#terminalDock,
QFrame#jobsView,
QFrame#folderBrowser,
QFrame#quickView {
    background: #111a2e;
    border: 1px solid #24324a;
    border-radius: 14px;
}
QFrame#topBar {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #13203a, stop: 1 #0f1a30);
}
QFrame#pane[activePane="true"] {
    border: 2px solid #4fd1ff;
}
QLabel#appTitle,
QLabel#paneTitle,
QLabel#terminalTitle {
    color: #f8fbff;
    font-size: 18px;
    font-weight: 700;
}
QLabel#appSubtitle,
QLabel#paneStatus,
QLabel#terminalNote,
QLabel#terminalPath,
QLabel#jobsEmpty,
QLabel#quickViewMeta,
QLabel#quickViewEmpty {
    color: #8ca0c3;
}
QLabel#jobsTitle {
    color: #f8fbff;
    font-size: 16px;
    font-weight: 700;
}
QLabel#quickViewTitle {
    color: #f8fbff;
    font-size: 16px;
    font-weight: 700;
}
QLabel#paneChip,
QLabel#paneChipMuted,
QLabel#functionKeyLabel,
QLabel#clipboardChip {
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid #294263;
    background: #13233d;
    color: #dbe8ff;
}
QLabel#paneChip {
    background: #0f3b57;
    border-color: #3c7da0;
    color: #dff6ff;
}
QLabel#paneChipMuted {
    background: #102236;
    border-color: #24324a;
    color: #a9bdd7;
}
QLabel#clipboardChip {
    background: #13314d;
    border-color: #3e6e98;
    color: #e8f5ff;
}
QLabel#clipboardChip[cutMode="true"] {
    background: #4a2a1a;
    border-color: #a56a3a;
    color: #fff1de;
}
QLabel#terminalPath {
    padding: 2px 2px 6px 2px;
}
QWidget#breadcrumbHost {
    background: #0b1324;
    border: 1px solid #263754;
    border-radius: 10px;
    min-height: 38px;
}
QWidget#tabStripHost {
    background: transparent;
}
QPushButton#breadcrumbButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 6px;
    color: #bcd0eb;
    text-align: left;
}
QPushButton#breadcrumbButton[current="true"] {
    background: #122742;
    border-color: #2e5d87;
    color: #f7fbff;
    font-weight: 600;
}
QPushButton#breadcrumbButton:hover {
    background: #13233d;
    border-color: #294263;
}
QLabel#breadcrumbSeparator {
    color: #89a4c7;
    font-weight: 700;
    padding: 0 1px;
}
QPushButton#breadcrumbBookmarkButton {
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0px;
    margin-left: 6px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #89a4c7;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#breadcrumbBookmarkButton:hover {
    background: #13233d;
    border-color: #294263;
    color: #cfe2ff;
}
QPushButton#breadcrumbBookmarkButton[active="true"] {
    background: #122742;
    border-color: #2e5d87;
    color: #ffd76a;
}
QLineEdit,
QComboBox,
QListWidget,
QTextEdit,
QPlainTextEdit,
QTreeWidget {
    background: #0b1324;
    color: #e7edf8;
    border: 1px solid #263754;
    border-radius: 10px;
    padding: 6px;
    selection-background-color: #17395d;
    selection-color: #f7fbff;
}
QTextEdit#terminalOutput,
QLineEdit#terminalInput,
QPlainTextEdit#quickViewText {
    font-family: Consolas;
}
QPlainTextEdit#quickViewText {
    border-radius: 12px;
}
QLabel#quickViewImage {
    background: #0b1324;
    border: 1px solid #24324a;
    border-radius: 12px;
}
QComboBox#quickViewSizePicker {
    min-width: 130px;
    padding: 6px 10px;
    border-radius: 10px;
}
QComboBox#thumbnailSizePicker {
    min-width: 104px;
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 10px;
}
QComboBox#quickViewSizePicker QAbstractItemView {
    background: #111a2e;
    color: #e7edf8;
    border: 1px solid #294263;
    selection-background-color: #17395d;
}
QComboBox#thumbnailSizePicker QAbstractItemView {
    background: #111a2e;
    color: #e7edf8;
    border: 1px solid #294263;
    selection-background-color: #17395d;
}
QHeaderView::section {
    background: #0f2038;
    color: #96aed2;
    border: none;
    border-bottom: 1px solid #24324a;
    padding: 8px 10px;
    font-weight: 600;
}
QTreeWidget::item {
    height: 32px;
    border-bottom: 1px solid rgba(36, 50, 74, 0.35);
}
QTreeWidget::item:hover {
    background: rgba(38, 64, 102, 0.45);
}
QTreeWidget::item:selected {
    background: #17395d;
}
QTreeWidget::item:alternate {
    background: rgba(15, 24, 42, 0.65);
}
QListWidget#thumbnailList {
    padding: 10px;
}
QListWidget#thumbnailList::item {
    border: 1px solid #24324a;
    border-radius: 12px;
    padding: 10px;
    margin: 4px;
}
QListWidget#thumbnailList::item:hover {
    background: rgba(38, 64, 102, 0.45);
    border-color: #35547a;
}
QListWidget#thumbnailList::item:selected {
    background: #17395d;
}
QPushButton {
    background: #16253f;
    color: #e5eefc;
    border: 1px solid #2f4565;
    border-radius: 10px;
    padding: 6px 12px;
}
QPushButton#secondaryActionButton {
    min-height: 30px;
    padding: 4px 10px;
    background: #112033;
    color: #c9d9ee;
    border-color: #28415f;
}
QPushButton#tabButton,
QPushButton#tabAddButton {
    min-height: 32px;
    padding: 6px 12px;
    border-radius: 10px 10px 0px 0px;
    background: #0c1628;
    color: #9fb6d6;
    border: 1px solid #22324c;
    border-bottom: none;
}
QPushButton#tabButton[active="true"] {
    background: #142844;
    color: #f7fbff;
    border-color: #3c7da0;
    font-weight: 600;
}
QPushButton#tabButton:hover {
    background: #11243d;
    color: #e4eefc;
    border-color: #35577d;
}
QPushButton#tabAddButton {
    min-width: 34px;
    padding: 6px 0px;
}
QPushButton#secondaryActionButton[active="true"] {
    background: #0f3b57;
    color: #f2fbff;
    border-color: #3c7da0;
}
QTreeWidget#folderBrowserTree {
    background: transparent;
    border: none;
    padding: 4px;
}
QTreeWidget#folderBrowserTree::item {
    height: 30px;
    border-radius: 8px;
}
QTreeWidget#folderBrowserTree::item:hover {
    background: rgba(32, 72, 116, 0.40);
}
QTreeWidget#folderBrowserTree::item:selected {
    background: rgba(33, 98, 154, 0.50);
}
QMenu#contextMenu {
    background: #111a2e;
    color: #e7edf8;
    border: 1px solid #294263;
    padding: 6px;
}
QMenu#contextMenu::item {
    padding: 8px 16px;
    border-radius: 8px;
}
QMenu#contextMenu::item:selected {
    background: #17395d;
}
QPushButton:hover {
    background: #1a3155;
    border-color: #436690;
}
QPushButton:pressed {
    background: #10223c;
}
QSplitter::handle {
    background: transparent;
    width: 10px;
}
QSplitter::handle:hover {
    background: rgba(79, 209, 255, 0.22);
}
"""
