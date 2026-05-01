from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QFileInfo, QMimeData, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QDrag, QFont, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileIconProvider,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QRubberBand,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.services.ai.cache import has_summary as _has_ai_summary
from multipane_commander.services.bookmarks import BookmarkStore
from multipane_commander.domain.entries import EntryInfo
from multipane_commander.state.model import PaneState, TabState
from multipane_commander.services.fs.archive_fs import (
    ArchiveFileSystem,
    is_archive_file,
    inside_archive,
)
from multipane_commander.services.fs.local_fs import LocalFileSystem
from multipane_commander.ui.folder_browser import FolderBrowser
from multipane_commander.ui.quick_view import QuickViewWidget
from multipane_commander.ui.themes import ThemePalette, build_palette, builtin_themes

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _CursorRowDelegate(QStyledItemDelegate):
    """Paint a strong selection bar for the view's current row.

    QTreeWidget/QListWidget with selectionMode=NoSelection won't render the
    standard selection highlight, and per-item setBackground() set via the
    BackgroundRole gets ignored when the global QSS styles ::item. Drawing
    the row in the delegate is the one place that reliably wins.
    """

    def __init__(self, pane: "PaneView", parent=None) -> None:
        super().__init__(parent)
        self._pane = pane

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        widget = option.widget
        is_current = False
        if widget is not None:
            current = widget.currentIndex()
            if current.isValid() and current.row() == index.row() and current.parent() == index.parent():
                is_current = True

        if is_current:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            palette = self._pane.theme_palette
            bg = QColor(palette.active_pane_border)
            fg = QColor(palette.chip_text)
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
            opt.palette.setColor(opt.palette.ColorRole.Text, fg)
            opt.palette.setColor(opt.palette.ColorRole.WindowText, fg)
            opt.palette.setColor(opt.palette.ColorRole.HighlightedText, fg)
            opt.backgroundBrush = QBrush(bg)
            # Strip the :hover/:selected state so default painting doesn't
            # repaint our background.
            opt.state &= ~QStyle.StateFlag.State_MouseOver
            opt.state &= ~QStyle.StateFlag.State_Selected
            super().paint(painter, opt, index)
        else:
            super().paint(painter, option, index)

        if index.column() == 0:
            self._paint_ai_badge(painter, option, index)

    def _paint_ai_badge(self, painter, option, index) -> None:
        path = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return
        if index.data(Qt.ItemDataRole.UserRole + 1) != "entry":
            return

        pane = self._pane
        if path in pane._ai_processing_paths:
            char = _SPINNER_FRAMES[pane._ai_spinner_frame]
            color = "#4ec9b0"
        else:
            if not _has_ai_summary(path):
                return
            char = "✦"
            color = "#5a7a8a"

        painter.save()
        painter.setPen(QColor(color))
        font = QFont()
        font.setPointSize(14)
        painter.setFont(font)
        r = option.rect
        badge_rect = QRect(r.right() - 26, r.top(), 24, r.height())
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, char)
        painter.restore()


class PaneView(QFrame):
    _DRAG_MIME_TYPE = "application/x-multipane-commander-paths"

    activated = Signal(object)
    operation_requested = Signal(str)
    navigate_requested = Signal(object)
    current_path_changed = Signal(object)
    current_directory_changed = Signal(object)
    preferences_changed = Signal()
    drag_drop_requested = Signal(object, object, int)
    open_in_other_pane_requested = Signal(object)

    def __init__(
        self,
        pane_state: PaneState,
        *,
        bookmark_store: BookmarkStore,
        active: bool,
    ) -> None:
        super().__init__()
        self.pane_state = pane_state
        self._local_fs = LocalFileSystem()
        self._archive_fs = ArchiveFileSystem()
        self.fs = self._local_fs
        self._quick_view_temp_path: Path | None = None
        self.bookmark_store = bookmark_store
        self.icon_provider = QFileIconProvider()
        self.marked_paths: set[Path] = set()
        self.file_list = QTreeWidget()
        self.thumbnail_list = QListWidget()
        self.status = QLabel()
        self.summary_chip = QLabel()
        self.selection_chip = QLabel()
        self.tab_strip_host = QWidget()
        self.tab_strip_layout = QHBoxLayout(self.tab_strip_host)
        self.breadcrumb_host = QWidget()
        self.breadcrumb_layout = QHBoxLayout(self.breadcrumb_host)
        self.folder_browser = FolderBrowser(bookmark_store=bookmark_store)
        self.folder_browser_toggle = QPushButton("Folders")
        self.back_button = QPushButton("←")
        self.bookmark_toggle = QPushButton("Bookmark")
        self.thumbnail_toggle = QPushButton("Thumbs")
        self.thumbnail_size_picker = QComboBox()
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_stack = QStackedWidget()
        self.browser_stack = QStackedWidget()
        self.quick_view = QuickViewWidget()
        self.quick_view_enabled = self.pane_state.quick_view_enabled
        self.thumbnail_mode_enabled = self.pane_state.thumbnail_mode_enabled
        self._image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        self._marquee_band: QRubberBand | None = None
        self._marquee_origin: QPoint | None = None
        self._marquee_viewport: QWidget | None = None
        self._marquee_started = False
        self._marquee_base_marks: set[Path] = set()
        self._drag_origin: QPoint | None = None
        self._drag_viewport: QWidget | None = None
        self._drag_source_paths: list[Path] = []
        self._drop_target_dir: Path | None = None
        self._cut_pending_paths: set[Path] = set()
        self._type_to_jump_buffer: str = ""
        self._type_to_jump_timer = QTimer(self)
        self._type_to_jump_timer.setSingleShot(True)
        self._type_to_jump_timer.setInterval(750)
        self._type_to_jump_timer.timeout.connect(self._reset_type_to_jump)
        self._ai_processing_paths: frozenset[Path] = frozenset()
        self._ai_spinner_frame: int = 0
        self._ai_spinner_timer = QTimer(self)
        self._ai_spinner_timer.setSingleShot(False)
        self._ai_spinner_timer.setInterval(100)
        self._ai_spinner_timer.timeout.connect(self._advance_ai_spinner)
        self._quick_filter_text: str = ""
        self._quick_filter_bar = QLineEdit()
        self._quick_filter_bar.setPlaceholderText("Filter (Esc to clear)")
        self._quick_filter_bar.setVisible(False)
        self._quick_filter_bar.textChanged.connect(self._apply_quick_filter)
        self._quick_filter_bar.installEventFilter(self)
        self.theme_palette = build_palette(builtin_themes()[0])
        self._thumbnail_size_presets = {
            "Small": {"icon": QSize(96, 72), "grid": QSize(122, 124)},
            "Medium": {"icon": QSize(144, 112), "grid": QSize(170, 164)},
            "Large": {"icon": QSize(216, 168), "grid": QSize(242, 220)},
        }
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._current_entries: list[EntryInfo] = []

        self.setObjectName("pane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Route any focus targeted at the pane container to the inner file
        # list so keyboard navigation (Up/Down/PgUp/PgDn/Home/End) reaches
        # the QTreeWidget that actually understands those keys.
        self.setFocusProxy(self.file_list)
        self.set_active(active)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("secondaryActionButton")
        refresh_button.clicked.connect(self.refresh)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title_row.addWidget(self.folder_browser_toggle)
        title_row.addWidget(self.thumbnail_toggle)
        title_row.addWidget(self.thumbnail_size_picker)
        title_row.addStretch(1)
        title_row.addWidget(self.summary_chip)
        title_row.addWidget(self.selection_chip)
        title_row.addWidget(refresh_button)

        self.tab_strip_host.setObjectName("tabStripHost")
        self.tab_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_strip_layout.setSpacing(4)
        self.breadcrumb_host.setObjectName("breadcrumbHost")
        self.breadcrumb_layout.setContentsMargins(8, 3, 8, 3)
        self.breadcrumb_layout.setSpacing(2)
        self.folder_browser_toggle.setObjectName("secondaryActionButton")
        self.folder_browser_toggle.clicked.connect(self._toggle_folder_browser)
        self.back_button.setObjectName("breadcrumbNavButton")
        self.back_button.setToolTip("Back")
        self.back_button.clicked.connect(self._navigate_back)
        self.bookmark_toggle.setObjectName("breadcrumbBookmarkButton")
        self.bookmark_toggle.clicked.connect(self._toggle_bookmark)
        self.thumbnail_toggle.setObjectName("secondaryActionButton")
        self.thumbnail_toggle.clicked.connect(self.toggle_thumbnail_mode)
        self.thumbnail_size_picker.setObjectName("thumbnailSizePicker")
        self.thumbnail_size_picker.addItems(list(self._thumbnail_size_presets))
        self.thumbnail_size_picker.setCurrentText(self.pane_state.thumbnail_size_preset)
        self.thumbnail_size_picker.currentTextChanged.connect(self._on_thumbnail_size_changed)
        self.thumbnail_size_picker.setEnabled(False)
        self.folder_browser.path_selected.connect(self.navigate_to)
        self.folder_browser.tree.installEventFilter(self)
        self.folder_browser.setVisible(False)
        self.file_list.setObjectName("fileList")
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.file_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_list.setAlternatingRowColors(False)
        self.file_list.setRootIsDecorated(False)
        self.file_list.setUniformRowHeights(True)
        self.file_list.setHeaderLabels(["Name", "Type", "Size", "Modified"])
        header = self.file_list.header()
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self._sort_column, self._sort_order)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.sectionClicked.connect(self._sort_by_header)
        self.file_list.itemActivated.connect(lambda item, _column: self._activate_item(item))
        self.file_list.currentItemChanged.connect(self._update_status)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(
            lambda position: self._show_item_context_menu(self.file_list, position)
        )
        self.file_list.setAcceptDrops(True)
        self.file_list.viewport().setAcceptDrops(True)
        self._file_delegate = _CursorRowDelegate(self, self.file_list)
        self.file_list.setItemDelegate(self._file_delegate)
        self.file_list.installEventFilter(self)
        self.file_list.viewport().installEventFilter(self)
        self.thumbnail_list.setObjectName("thumbnailList")
        self.thumbnail_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.thumbnail_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_list.setMovement(QListWidget.Movement.Static)
        self.thumbnail_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_list.setWrapping(True)
        self.thumbnail_list.setWordWrap(True)
        self.thumbnail_list.setSpacing(12)
        self.thumbnail_list.itemActivated.connect(self._activate_item)
        self.thumbnail_list.currentItemChanged.connect(self._update_status)
        self.thumbnail_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnail_list.customContextMenuRequested.connect(
            lambda position: self._show_item_context_menu(self.thumbnail_list, position)
        )
        self.thumbnail_list.setAcceptDrops(True)
        self.thumbnail_list.viewport().setAcceptDrops(True)
        self._thumb_delegate = _CursorRowDelegate(self, self.thumbnail_list)
        self.thumbnail_list.setItemDelegate(self._thumb_delegate)
        self.thumbnail_list.installEventFilter(self)
        self.thumbnail_list.viewport().installEventFilter(self)
        self.status.setObjectName("paneStatus")
        self.summary_chip.setObjectName("paneChip")
        self.selection_chip.setObjectName("paneChipMuted")

        location_row = QHBoxLayout()
        location_row.setContentsMargins(0, 0, 0, 0)
        location_row.setSpacing(8)
        location_row.addWidget(self.tab_strip_host, 1)
        location_row.addStretch(1)

        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.folder_browser)
        self.browser_stack.addWidget(self.file_list)
        self.browser_stack.addWidget(self.thumbnail_list)
        self.content_splitter.addWidget(self.browser_stack)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([0, 1])
        self.content_stack.setAcceptDrops(True)
        self.quick_view.setAcceptDrops(True)
        self.content_stack.installEventFilter(self)
        self.quick_view.installEventFilter(self)
        self.content_stack.addWidget(self.content_splitter)
        self.content_stack.addWidget(self.quick_view)

        layout.addLayout(title_row)
        layout.addLayout(location_row)
        layout.addWidget(self.breadcrumb_host)
        layout.addWidget(self._quick_filter_bar)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self.status)

        self.bookmark_store.bookmarks_changed.connect(lambda _bookmarks: self._update_bookmark_button())
        self.quick_view.size_picker.currentTextChanged.connect(self._on_quick_view_size_changed)
        self.quick_view.set_size_preset(self.pane_state.quick_view_size_preset)
        self._ensure_tab_history(self.active_tab)
        self._apply_thumbnail_size_preset(self.thumbnail_size_picker.currentText())
        self.refresh()
        self.set_thumbnail_mode_enabled(self.pane_state.thumbnail_mode_enabled)
        self.set_quick_view_enabled(self.pane_state.quick_view_enabled)

    @property
    def active_tab(self):
        return self.pane_state.tabs[self.pane_state.active_tab_index]

    def set_active(self, active: bool) -> None:
        self.setProperty("activePane", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def focus_list(self) -> None:
        if self.quick_view_enabled:
            self.quick_view.setFocus(Qt.FocusReason.TabFocusReason)
            return
        self._current_browser_widget().setFocus(Qt.FocusReason.TabFocusReason)

    def init_claude_terminal(self, session_cache: object) -> None:
        """Create the ClaudeTerminalWidget and add it to content_stack.
        Called once from MainWindow after pane construction."""
        from multipane_commander.ui.claude_terminal import ClaudeTerminalWidget  # type: ignore[attr-defined]
        self.claude_view: ClaudeTerminalWidget = ClaudeTerminalWidget(session_cache)  # type: ignore[assignment]
        self.content_stack.addWidget(self.claude_view)

    def is_claude_enabled(self) -> bool:
        return (
            hasattr(self, "claude_view")
            and self.content_stack.currentWidget() is self.claude_view
        )

    def set_claude_enabled(self, enabled: bool, cwd: Path | None = None, extra: list | None = None) -> None:
        if enabled and cwd is not None and hasattr(self, "claude_view"):
            self.content_stack.setCurrentWidget(self.claude_view)
            self.claude_view.show_for(cwd, extra or [])  # focus happens inside show_for
        elif not enabled:
            if hasattr(self, "claude_view"):
                self.claude_view.stop_session()
            # Restore whichever widget was showing before claude took over
            self.content_stack.setCurrentWidget(
                self.quick_view if self.quick_view_enabled else self.content_splitter
            )

    def is_quick_view_enabled(self) -> bool:
        return self.quick_view_enabled

    def set_quick_view_enabled(self, enabled: bool) -> None:
        self.quick_view_enabled = enabled
        self.pane_state.quick_view_enabled = enabled
        self.content_stack.setCurrentWidget(self.quick_view if enabled else self.content_splitter)
        self.preferences_changed.emit()

    def set_quick_view_ai_runtime(self, runner: object | None, pane_roots: object | None) -> None:
        """Pass-through that lets MainWindow wire the AI runner + sandbox roots
        into this pane's quick-view. Typed `object | None` to avoid pulling
        the AI service into pane_view's import graph at module load."""
        self.quick_view.set_ai_runtime(runner, pane_roots)  # type: ignore[arg-type]

    def set_ai_processing_paths(self, paths: frozenset) -> None:
        self._ai_processing_paths = paths
        if paths:
            if not self._ai_spinner_timer.isActive():
                self._ai_spinner_timer.start()
        else:
            self._ai_spinner_timer.stop()
        self.file_list.viewport().update()
        self.thumbnail_list.viewport().update()

    def _advance_ai_spinner(self) -> None:
        self._ai_spinner_frame = (self._ai_spinner_frame + 1) % len(_SPINNER_FRAMES)
        self.file_list.viewport().update()
        self.thumbnail_list.viewport().update()

    def set_quick_view_source(self, path: Path | None) -> None:
        # Clean up any temp file extracted for the previous archive preview.
        if self._quick_view_temp_path is not None:
            try:
                self._quick_view_temp_path.unlink()
            except OSError:
                pass
            self._quick_view_temp_path = None

        if path is None:
            self.quick_view.show_path(None)
            return

        ctx = inside_archive(path)
        if ctx is not None and str(ctx[1]) and str(ctx[1]) != ".":
            # File inside an archive — extract to a temp path for inline preview.
            try:
                temp_path = self._archive_fs.extract_entry_to_temp(path)
            except Exception:
                self.quick_view.show_path(None)
                return
            self._quick_view_temp_path = temp_path
            # Re-label so the user still sees the virtual file name.
            self.quick_view.show_path(temp_path)
            self.quick_view.title_label.setText(path.name or str(path))
            return

        self.quick_view.show_path(path)

    def is_thumbnail_mode_enabled(self) -> bool:
        return self.thumbnail_mode_enabled

    def toggle_thumbnail_mode(self) -> None:
        self.set_thumbnail_mode_enabled(not self.thumbnail_mode_enabled)

    def set_thumbnail_mode_enabled(self, enabled: bool) -> None:
        current_path = self.preview_path()
        self.thumbnail_mode_enabled = enabled
        self.pane_state.thumbnail_mode_enabled = enabled
        self.browser_stack.setCurrentWidget(self.thumbnail_list if enabled else self.file_list)
        self.thumbnail_toggle.setProperty("active", enabled)
        self.thumbnail_size_picker.setEnabled(enabled)
        self.thumbnail_toggle.style().unpolish(self.thumbnail_toggle)
        self.thumbnail_toggle.style().polish(self.thumbnail_toggle)
        self.thumbnail_toggle.update()
        if current_path is not None:
            self._set_current_path(current_path)
        else:
            self._focus_first_entry()
        self._update_status()
        self.preferences_changed.emit()

    def _current_browser_widget(self):
        return self.thumbnail_list if self.thumbnail_mode_enabled else self.file_list

    def set_cut_pending_paths(self, paths: list[Path]) -> None:
        self._cut_pending_paths = set(paths)
        self._refresh_row_styles()

    def set_theme_palette(self, palette: ThemePalette) -> None:
        self.theme_palette = palette
        self._refresh_row_styles()

    def _apply_thumbnail_size_preset(self, preset_name: str) -> None:
        preset = self._thumbnail_size_presets.get(preset_name)
        if preset is None:
            return

        self.thumbnail_list.setIconSize(preset["icon"])
        self.thumbnail_list.setGridSize(preset["grid"])

        current_path = self.preview_path()
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            path = item.data(Qt.ItemDataRole.UserRole)
            is_dir = item.data(Qt.ItemDataRole.UserRole + 3) == "dir"
            if isinstance(path, Path):
                item.setIcon(self._thumbnail_icon(path, is_dir=is_dir))

        if isinstance(current_path, Path):
            self._set_thumbnail_current_path(current_path)

    def _on_quick_view_size_changed(self, preset_name: str) -> None:
        self.pane_state.quick_view_size_preset = preset_name
        self.preferences_changed.emit()

    def _on_thumbnail_size_changed(self, preset_name: str) -> None:
        self.pane_state.thumbnail_size_preset = preset_name
        self._apply_thumbnail_size_preset(preset_name)
        self.preferences_changed.emit()

    def _current_browser_item(self):
        widget = self._current_browser_widget()
        return widget.currentItem()

    def _item_data(self, item, role: int):
        if isinstance(item, QTreeWidgetItem):
            return item.data(0, role)
        if isinstance(item, QListWidgetItem):
            return item.data(role)
        return None

    def open_new_tab(self, path: Path | None = None) -> None:
        new_path = path or self.current_directory()
        self.pane_state.tabs.append(
            TabState(
                title=new_path.name or str(new_path),
                path=new_path,
                navigation_history=[new_path],
                navigation_index=0,
            )
        )
        self.pane_state.active_tab_index = len(self.pane_state.tabs) - 1
        self.marked_paths.clear()
        self.refresh()
        self.focus_list()

    def close_current_tab(self) -> bool:
        if len(self.pane_state.tabs) <= 1:
            return False
        self.pane_state.tabs.pop(self.pane_state.active_tab_index)
        self.pane_state.active_tab_index = max(0, self.pane_state.active_tab_index - 1)
        self.marked_paths.clear()
        self.refresh()
        self.focus_list()
        return True

    def close_tab(self, index: int) -> bool:
        if len(self.pane_state.tabs) <= 1:
            return False
        if index < 0 or index >= len(self.pane_state.tabs):
            return False
        self.pane_state.tabs.pop(index)
        self.pane_state.active_tab_index = min(self.pane_state.active_tab_index, len(self.pane_state.tabs) - 1)
        self.marked_paths.clear()
        self.refresh()
        self.focus_list()
        return True

    def activate_tab(self, index: int) -> None:
        if index < 0 or index >= len(self.pane_state.tabs):
            return
        self.pane_state.active_tab_index = index
        self._ensure_tab_history(self.active_tab)
        self.marked_paths.clear()
        self.refresh()

    def next_tab(self) -> None:
        if len(self.pane_state.tabs) <= 1:
            return
        self.activate_tab((self.pane_state.active_tab_index + 1) % len(self.pane_state.tabs))
        self.focus_list()

    def previous_tab(self) -> None:
        if len(self.pane_state.tabs) <= 1:
            return
        self.activate_tab((self.pane_state.active_tab_index - 1) % len(self.pane_state.tabs))
        self.focus_list()

    def refresh(self) -> None:
        current_path = self.active_tab.path
        self._ensure_tab_history(self.active_tab)
        # Switch the active filesystem based on whether we're inside an archive.
        in_archive = inside_archive(current_path) is not None
        self.fs = self._archive_fs if in_archive else self._local_fs
        if in_archive:
            preserved_marks = {
                path for path in self.marked_paths if path.parent == current_path
            }
        else:
            preserved_marks = {
                path for path in self.marked_paths
                if path.parent == current_path and path.exists()
            }
        self.marked_paths = preserved_marks
        preserved_current_path = self.preview_path()
        self._rebuild_tab_strip()
        self._rebuild_breadcrumbs(current_path)

        try:
            self._current_entries = self.fs.list_dir(current_path)
        except OSError as exc:
            self._current_entries = []
            self._rebuild_file_views(current_path)
            error_item = QTreeWidgetItem([f"Unable to open directory: {exc}", "Error", "", ""])
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.file_list.addTopLevelItem(error_item)
            self.status.setText("directory open failed")
            return

        self._rebuild_file_views(current_path)

        self.summary_chip.setText(f"{len(self._current_entries):,} items")

        if self.file_list.topLevelItemCount() > 0:
            if preserved_current_path is not None:
                self._set_current_path(preserved_current_path)
            else:
                self._focus_first_entry()
        else:
            self.status.setText("empty directory")
        self._update_status()
        self._refresh_row_styles()
        self._update_bookmark_button()
        self._update_navigation_buttons()
        self.current_directory_changed.emit(current_path)

    def _rebuild_file_views(self, current_path: Path) -> None:
        self.file_list.clear()
        self.thumbnail_list.clear()

        if current_path.parent != current_path:
            parent_item = QTreeWidgetItem(["..", "Parent", "", ""])
            parent_item.setData(0, Qt.ItemDataRole.UserRole, current_path.parent)
            parent_item.setData(0, Qt.ItemDataRole.UserRole + 1, "parent")
            parent_item.setData(0, Qt.ItemDataRole.UserRole + 3, "parent")
            parent_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogToParent))
            parent_item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.file_list.addTopLevelItem(parent_item)
            self.thumbnail_list.addItem(
                self._build_thumbnail_item(path=current_path.parent, is_dir=True, size=0, modified_text="Parent")
            )

        for entry in self._sorted_entries(self._current_entries):
            self.file_list.addTopLevelItem(self._build_tree_item(entry))
            self.thumbnail_list.addItem(
                self._build_thumbnail_item(
                    path=entry.path,
                    is_dir=entry.is_dir,
                    size=entry.size,
                    modified_text=entry.modified_at.strftime("%Y-%m-%d %H:%M"),
                )
            )

    def _sort_by_header(self, column: int) -> None:
        if column not in {0, 1, 2, 3}:
            return
        if self._sort_column == column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder

        self.file_list.header().setSortIndicator(self._sort_column, self._sort_order)
        preserved_current_path = self.preview_path()
        self._rebuild_file_views(self.active_tab.path)
        if preserved_current_path is not None:
            self._set_current_path(preserved_current_path)
        else:
            self._focus_first_entry()
        self._update_status()
        self._refresh_row_styles()

    def _sorted_entries(self, entries: list[EntryInfo]) -> list[EntryInfo]:
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        directories = [entry for entry in entries if entry.is_dir]
        files = [entry for entry in entries if not entry.is_dir]
        return sorted(directories, key=self._entry_sort_key, reverse=reverse) + sorted(
            files,
            key=self._entry_sort_key,
            reverse=reverse,
        )

    def _entry_sort_key(self, entry: EntryInfo):
        name_key = entry.name.casefold()
        if self._sort_column == 1:
            type_key = "Folder" if entry.is_dir else (entry.extension or "File")
            return (type_key.casefold(), name_key)
        if self._sort_column == 2:
            return (entry.size, name_key)
        if self._sort_column == 3:
            return (entry.modified_at, name_key)
        return (name_key,)

    def _build_tree_item(self, entry) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                entry.name,
                "Folder" if entry.is_dir else (entry.extension or "File"),
                "" if entry.is_dir else self._format_size(entry.size),
                entry.modified_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, entry.path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, "entry")
        item.setData(0, Qt.ItemDataRole.UserRole + 2, entry.size)
        item.setData(0, Qt.ItemDataRole.UserRole + 3, "dir" if entry.is_dir else "file")
        item.setIcon(0, self.icon_provider.icon(QFileInfo(str(entry.path))))
        return item

    def _build_thumbnail_item(
        self,
        *,
        path: Path,
        is_dir: bool,
        size: int,
        modified_text: str,
    ) -> QListWidgetItem:
        label = path.name or str(path)
        if modified_text == "Parent":
            label = ".."
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, "parent" if modified_text == "Parent" else "entry")
        item.setData(Qt.ItemDataRole.UserRole + 2, size)
        item.setData(Qt.ItemDataRole.UserRole + 3, "dir" if is_dir else "file")
        item.setData(Qt.ItemDataRole.UserRole + 4, modified_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
        item.setToolTip(str(path))
        item.setIcon(self._thumbnail_icon(path, is_dir=is_dir))
        return item

    def _thumbnail_icon(self, path: Path, *, is_dir: bool) -> QIcon:
        if not is_dir and path.suffix.lower() in self._image_suffixes:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return QIcon(
                    pixmap.scaled(
                        self.thumbnail_list.iconSize(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        return self.icon_provider.icon(QFileInfo(str(path)))

    def _focus_first_entry(self) -> None:
        if self.file_list.topLevelItemCount() == 0:
            return
        tree_item = self.file_list.topLevelItem(0)
        if (
            tree_item is not None
            and tree_item.data(0, Qt.ItemDataRole.UserRole + 1) == "parent"
            and self.file_list.topLevelItemCount() > 1
        ):
            tree_item = self.file_list.topLevelItem(1)
        if tree_item is not None:
            self.file_list.setCurrentItem(tree_item)
            path = tree_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(path, Path):
                self._set_thumbnail_current_path(path)

    def _set_current_path(self, path: Path) -> None:
        self._set_tree_current_path(path)
        self._set_thumbnail_current_path(path)

    def _set_tree_current_path(self, path: Path) -> None:
        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                self.file_list.setCurrentItem(item)
                return

    def _set_thumbnail_current_path(self, path: Path) -> None:
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self.thumbnail_list.setCurrentItem(item)
                return

    def _entry_count(self) -> int:
        count = self.file_list.topLevelItemCount()
        if count <= 0:
            return 0
        first_item = self.file_list.topLevelItem(0)
        if first_item is not None and first_item.data(0, Qt.ItemDataRole.UserRole + 1) == "parent":
            return count - 1
        return count

    def _advance_current_item(self) -> None:
        if self.thumbnail_mode_enabled:
            current_item = self.thumbnail_list.currentItem()
            if current_item is None:
                return
            next_row = min(self.thumbnail_list.row(current_item) + 1, self.thumbnail_list.count() - 1)
            next_item = self.thumbnail_list.item(next_row)
            if next_item is not None:
                self.thumbnail_list.setCurrentItem(next_item)
            return

        current_item = self.file_list.currentItem()
        if current_item is None:
            return
        next_row = min(
            self.file_list.indexOfTopLevelItem(current_item) + 1,
            self.file_list.topLevelItemCount() - 1,
        )
        next_item = self.file_list.topLevelItem(next_row)
        if next_item is not None:
            self.file_list.setCurrentItem(next_item)

    def _begin_pointer_action(self, viewport: QWidget, origin: QPoint) -> None:
        self.activated.emit(self)
        self._drag_origin = origin
        self._drag_viewport = viewport
        self._drag_source_paths = self._drag_paths_at(viewport, origin)
        if self._drag_source_paths:
            self._marquee_viewport = None
            self._marquee_origin = None
            self._marquee_started = False
            return
        self._begin_marquee(viewport, origin)

    def _drag_paths_at(self, viewport: QWidget, position: QPoint) -> list[Path]:
        item = self._item_at_position(viewport, position)
        if item is None or self._item_data(item, Qt.ItemDataRole.UserRole + 1) != "entry":
            return []
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return []
        self._set_current_path(path)
        if path in self.marked_paths:
            return self.selected_paths()
        return [path]

    def _item_at_position(self, viewport: QWidget, position: QPoint):
        if viewport is self.file_list.viewport():
            return self.file_list.itemAt(position)
        if viewport is self.thumbnail_list.viewport():
            return self.thumbnail_list.itemAt(position)
        return None

    def _maybe_start_drag(self, viewport: QWidget, position: QPoint, *, buttons) -> bool:
        if self._drag_viewport is not viewport or self._drag_origin is None or not self._drag_source_paths:
            return False
        if not buttons & Qt.MouseButton.LeftButton:
            return False
        if (position - self._drag_origin).manhattanLength() < QApplication.startDragDistance():
            return False
        self._start_internal_drag(viewport, self._drag_source_paths)
        self._reset_pointer_state()
        return True

    def _start_internal_drag(self, viewport: QWidget, source_paths: list[Path]) -> None:
        drag = QDrag(viewport)
        mime_data = QMimeData()
        payload = json.dumps({"paths": [str(path) for path in source_paths]}).encode("utf-8")
        mime_data.setData(self._DRAG_MIME_TYPE, payload)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def _begin_marquee(self, viewport: QWidget, origin: QPoint) -> None:
        self.activated.emit(self)
        self._marquee_viewport = viewport
        self._marquee_origin = origin
        self._marquee_started = False
        self._marquee_base_marks = set(self.marked_paths)

    def _update_marquee(self, viewport: QWidget, position: QPoint, *, buttons) -> bool:
        if self._marquee_viewport is not viewport or self._marquee_origin is None:
            return False
        if not buttons & Qt.MouseButton.LeftButton:
            return False

        if not self._marquee_started:
            if (position - self._marquee_origin).manhattanLength() < QApplication.startDragDistance():
                return False
            self._marquee_started = True
            if self._marquee_band is None or self._marquee_band.parent() is not viewport:
                self._marquee_band = QRubberBand(QRubberBand.Shape.Rectangle, viewport)
            self._marquee_band.setGeometry(QRect(self._marquee_origin, QSize()).normalized())
            self._marquee_band.show()

        selection_rect = QRect(self._marquee_origin, position).normalized()
        if self._marquee_band is not None:
            self._marquee_band.setGeometry(selection_rect)
        self._apply_marquee_selection(viewport, selection_rect)
        return True

    def _end_marquee(self, viewport: QWidget, position: QPoint) -> bool:
        if self._marquee_viewport is not viewport or self._marquee_origin is None:
            return False

        consumed = self._marquee_started
        if self._marquee_started:
            selection_rect = QRect(self._marquee_origin, position).normalized()
            self._apply_marquee_selection(viewport, selection_rect)
        self._reset_marquee()
        return consumed

    def _reset_marquee(self) -> None:
        if self._marquee_band is not None:
            self._marquee_band.hide()
        self._marquee_origin = None
        self._marquee_viewport = None
        self._marquee_started = False
        self._marquee_base_marks = set()

    def _reset_pointer_state(self) -> None:
        self._drag_origin = None
        self._drag_viewport = None
        self._drag_source_paths = []
        self._reset_marquee()

    def _apply_marquee_selection(self, viewport: QWidget, selection_rect: QRect) -> None:
        touched_paths = self._paths_in_selection_rect(viewport, selection_rect)
        self.marked_paths = touched_paths
        if touched_paths:
            self._set_current_path(next(iter(sorted(touched_paths, key=lambda path: path.name.lower()))))
        self._update_status()

    def _drop_destination(self, viewport: QWidget, position: QPoint) -> Path | None:
        if viewport in {self.content_stack, self.quick_view}:
            return self.current_directory()
        item = self._item_at_position(viewport, position)
        if item is None:
            return self.current_directory()
        if self._item_data(item, Qt.ItemDataRole.UserRole + 1) != "entry":
            return None
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        if isinstance(path, Path) and path.is_dir():
            return path
        return None

    def _decode_drag_paths(self, mime_data: QMimeData) -> list[Path]:
        if not mime_data.hasFormat(self._DRAG_MIME_TYPE):
            return []
        try:
            payload = json.loads(bytes(mime_data.data(self._DRAG_MIME_TYPE)).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        paths = []
        for path_str in payload.get("paths", []):
            if isinstance(path_str, str) and path_str:
                paths.append(Path(path_str))
        return paths

    def _update_drop_target(self, destination_dir: Path | None) -> None:
        if destination_dir == self._drop_target_dir:
            return
        self._drop_target_dir = destination_dir
        self._refresh_row_styles()

    def _paths_in_selection_rect(self, viewport: QWidget, selection_rect: QRect) -> set[Path]:
        if viewport is self.file_list.viewport():
            return self._tree_paths_in_selection_rect(selection_rect)
        if viewport is self.thumbnail_list.viewport():
            return self._thumbnail_paths_in_selection_rect(selection_rect)
        return set()

    def _tree_paths_in_selection_rect(self, selection_rect: QRect) -> set[Path]:
        touched: set[Path] = set()
        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
                continue
            if not self.file_list.visualItemRect(item).intersects(selection_rect):
                continue
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(path, Path):
                touched.add(path)
        return touched

    def _thumbnail_paths_in_selection_rect(self, selection_rect: QRect) -> set[Path]:
        touched: set[Path] = set()
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole + 1) != "entry":
                continue
            if not self.thumbnail_list.visualItemRect(item).intersects(selection_rect):
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(path, Path):
                touched.add(path)
        return touched

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Backspace:
            self.navigate_to(self.active_tab.path.parent)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Insert, Qt.Key.Key_Space):
            self._toggle_current_selection()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._clear_marks()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self._mark_all_entries()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F2:
            self.operation_requested.emit("rename")
            event.accept()
            return
        # Don't use QKeySequence.StandardKey.Refresh — Qt maps it to F5 on
        # several platforms, which collides with TC's F5 = Copy below.
        if (
            event.key() == Qt.Key.Key_R
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.operation_requested.emit("refresh")
            event.accept()
            return
        if event.key() == Qt.Key.Key_F5:
            self.operation_requested.emit("copy")
            event.accept()
            return
        if event.key() == Qt.Key.Key_F6:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.operation_requested.emit("rename")
            else:
                self.operation_requested.emit("move")
            event.accept()
            return
        if event.key() == Qt.Key.Key_F7:
            self.operation_requested.emit("mkdir")
            event.accept()
            return
        if event.key() == Qt.Key.Key_F8:
            self.operation_requested.emit("delete")
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.operation_requested.emit("delete")
            event.accept()
            return
        if self._maybe_type_to_jump(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self.activated.emit(self)
        super().focusInEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.activated.emit(self)
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.FocusIn and watched in {
            self.file_list,
            self.thumbnail_list,
            self.file_list.viewport(),
            self.thumbnail_list.viewport(),
            self.content_stack,
            self.quick_view,
            self.folder_browser.tree,
        }:
            self.activated.emit(self)
            self._refresh_row_styles()
        drag_targets = {
            self.file_list.viewport(),
            self.thumbnail_list.viewport(),
            self.content_stack,
            self.quick_view,
        }
        pointer_sources = {
            self.file_list.viewport(),
            self.thumbnail_list.viewport(),
        }
        if watched in drag_targets:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if watched in pointer_sources:
                    self._begin_pointer_action(watched, event.position().toPoint())
            elif event.type() == QEvent.Type.MouseMove:
                if watched in pointer_sources:
                    if self._maybe_start_drag(watched, event.position().toPoint(), buttons=event.buttons()):
                        return True
                    if self._update_marquee(watched, event.position().toPoint(), buttons=event.buttons()):
                        return True
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if watched in pointer_sources:
                    if self._drag_viewport is watched:
                        self._drag_source_paths = []
                        self._drag_origin = None
                        self._drag_viewport = None
                    if self._end_marquee(watched, event.position().toPoint()):
                        return True
            elif event.type() == QEvent.Type.DragEnter:
                source_paths = self._decode_drag_paths(event.mimeData())
                destination_dir = self._drop_destination(watched, event.position().toPoint())
                if source_paths and destination_dir is not None:
                    event.acceptProposedAction()
                    self._update_drop_target(destination_dir)
                    return True
            elif event.type() == QEvent.Type.DragMove:
                source_paths = self._decode_drag_paths(event.mimeData())
                destination_dir = self._drop_destination(watched, event.position().toPoint())
                if source_paths and destination_dir is not None:
                    event.acceptProposedAction()
                    self._update_drop_target(destination_dir)
                    return True
                self._update_drop_target(None)
            elif event.type() == QEvent.Type.DragLeave:
                self._update_drop_target(None)
            elif event.type() == QEvent.Type.Drop:
                source_paths = self._decode_drag_paths(event.mimeData())
                destination_dir = self._drop_destination(watched, event.position().toPoint())
                self._update_drop_target(None)
                if source_paths and destination_dir is not None:
                    self.drag_drop_requested.emit(
                        source_paths,
                        destination_dir,
                        event.modifiers().value,
                    )
                    event.acceptProposedAction()
                    return True
        if watched is self._quick_filter_bar and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.hide_quick_filter(clear=True)
                self._apply_quick_filter("")
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.hide_quick_filter(clear=False)
                return True
        if watched in {self.file_list, self.thumbnail_list, self.file_list.viewport(), self.thumbnail_list.viewport()} and event.type() == QEvent.Type.KeyPress:
            # With selectionMode == NoSelection, Qt's QAbstractItemView blocks
            # arrow-key cursor movement by design (it's tied to the selection
            # model). We do our own marking via Insert/Space/Ctrl+A, so we
            # need to drive the cursor explicitly here.
            if self._handle_navigation_key(watched, event):
                event.accept()
                return True
            if event.key() in (Qt.Key.Key_Insert, Qt.Key.Key_Space):
                self._toggle_current_selection()
                event.accept()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self._clear_marks()
                event.accept()
                return True
            if event.matches(QKeySequence.StandardKey.SelectAll):
                self._mark_all_entries()
                event.accept()
                return True
            if event.key() == Qt.Key.Key_Backspace:
                self._go_up()
                event.accept()
                return True
            if event.key() == Qt.Key.Key_F6 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.operation_requested.emit("rename")
                event.accept()
                return True
            if event.key() == Qt.Key.Key_Delete:
                self.operation_requested.emit("delete")
                event.accept()
                return True
            if self._maybe_type_to_jump(event):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def navigate_to(self, path: Path, *, record_history: bool = True) -> None:
        self._ensure_tab_history(self.active_tab)
        if record_history:
            self._record_navigation(path)
        self.active_tab.path = path
        self.active_tab.title = path.name or str(path)
        self.refresh()

    def current_directory(self) -> Path:
        return self.active_tab.path

    def selected_paths(self) -> list[Path]:
        if self.marked_paths:
            return sorted(self.marked_paths, key=lambda path: path.name.lower())

        current_path = self.current_path()
        return [current_path] if current_path is not None else []

    def current_path(self) -> Path | None:
        item = self._current_browser_item()
        if item is None or self._item_data(item, Qt.ItemDataRole.UserRole + 1) != "entry":
            return None
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        return path if isinstance(path, Path) else None

    def preview_path(self) -> Path | None:
        item = self._current_browser_item()
        if item is None:
            return None
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        return path if isinstance(path, Path) else None

    def show_quick_filter(self) -> None:
        self._quick_filter_bar.setVisible(True)
        self._quick_filter_bar.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._quick_filter_bar.selectAll()

    def hide_quick_filter(self, *, clear: bool = True) -> None:
        if clear:
            self._quick_filter_bar.clear()
        self._quick_filter_bar.setVisible(False)
        self.file_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_quick_filter(self, text: str) -> None:
        self._quick_filter_text = text.strip().lower()
        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
                item.setHidden(False)
                continue
            if not self._quick_filter_text:
                item.setHidden(False)
                continue
            label = item.text(0).lower()
            item.setHidden(self._quick_filter_text not in label)

    def _handle_navigation_key(self, watched, event) -> bool:
        """Drive Up/Down/PgUp/PgDn/Home/End/Enter on the file list ourselves.

        QAbstractItemView with selectionMode == NoSelection refuses to move
        currentItem on arrow keys (by design — see Qt docs / forum: when
        selection is disabled, the navigation hooks that update currentIndex
        are gated). We need our own custom-mark model, so we re-implement
        the navigation here.
        """
        key = event.key()
        modifiers = event.modifiers()
        # On macOS, the standard arrow keys carry KeypadModifier — don't treat
        # that as "the user is invoking a shortcut". Only bail out for Ctrl /
        # Alt / Meta so the global shortcut layer keeps Ctrl+arrow / Alt+arrow.
        blocking = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocking:
            return False

        # Enter / Return — activate cursor item (descend dir / launch file).
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.file_list.currentItem()
            if current is not None:
                self._activate_item(current)
                return True
            return False

        if watched not in {self.file_list, self.file_list.viewport()}:
            return False  # thumbnail list keeps Qt's icon-grid navigation

        count = self.file_list.topLevelItemCount()
        if count == 0:
            return False
        current = self.file_list.currentItem()
        current_row = self.file_list.indexOfTopLevelItem(current) if current else -1
        if current_row < 0:
            current_row = 0

        if key == Qt.Key.Key_Down:
            target_row = min(count - 1, current_row + 1)
        elif key == Qt.Key.Key_Up:
            target_row = max(0, current_row - 1)
        elif key == Qt.Key.Key_PageDown:
            target_row = min(count - 1, current_row + max(1, self._page_step()))
        elif key == Qt.Key.Key_PageUp:
            target_row = max(0, current_row - max(1, self._page_step()))
        elif key == Qt.Key.Key_Home:
            target_row = 0
        elif key == Qt.Key.Key_End:
            target_row = count - 1
        else:
            return False

        if target_row == current_row:
            return True  # consume so QAIV doesn't no-op-blink
        target_item = self.file_list.topLevelItem(target_row)
        if target_item is not None:
            self.file_list.setCurrentItem(target_item)
            self.file_list.scrollToItem(target_item)
            self._refresh_row_styles()
            self.file_list.viewport().update()
        return True

    def _page_step(self) -> int:
        viewport = self.file_list.viewport()
        row_height = max(1, self.file_list.sizeHintForRow(0))
        return max(1, viewport.height() // row_height)

    def _maybe_type_to_jump(self, event) -> bool:
        if event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier:
            return False
        text = event.text()
        if not text or len(text) != 1 or not text.isprintable() or text == " ":
            return False
        self._type_to_jump_buffer += text.lower()
        self._type_to_jump_timer.start()
        return self._jump_to_first_match(self._type_to_jump_buffer)

    def _jump_to_first_match(self, prefix: str) -> bool:
        if not prefix:
            return False
        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
                continue
            label = item.text(0).lower()
            if label.startswith(prefix):
                self.file_list.setCurrentItem(item)
                return True
        return False

    def _reset_type_to_jump(self) -> None:
        self._type_to_jump_buffer = ""

    def _activate_item(self, item) -> None:
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return
        # Real archive file: enter it as a virtual directory.
        if is_archive_file(path):
            self.navigate_to(path)
            return
        # Virtual entries store is_dir in UserRole+3.
        kind = self._item_data(item, Qt.ItemDataRole.UserRole + 3)
        if kind == "dir" or path.is_dir():
            self.navigate_to(path)
            return
        # Inside an archive, plain files can't be opened via the OS handler
        # (the Path doesn't exist on disk). Defer to F3 / F5 instead.
        if inside_archive(path) is not None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _update_status(self, *_args) -> None:
        item = self._current_browser_item()
        if item is None:
            self.selection_chip.setText("No selection")
            self.status.setText("empty directory")
            self._refresh_row_styles()
            self.current_path_changed.emit(None)
            return

        selected_count = len(self.marked_paths)
        selected_size = sum(
            item.data(0, Qt.ItemDataRole.UserRole + 2) or 0
            for row in range(self.file_list.topLevelItemCount())
            for item in [self.file_list.topLevelItem(row)]
            if item.data(0, Qt.ItemDataRole.UserRole + 1) == "entry"
            and item.data(0, Qt.ItemDataRole.UserRole) in self.marked_paths
        )
        self.selection_chip.setText(
            f"{selected_count} marked" if selected_count else "No selection"
        )

        if selected_count > 1:
            self.status.setText(
                f"{self._entry_count():,} rows | marked: {selected_count} | "
                f"size: {self._format_size(selected_size)}"
            )
            self._refresh_row_styles()
            self.current_path_changed.emit(self.preview_path())
            return

        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        if isinstance(path, Path):
            if path.is_dir():
                self.status.setText(
                    f"{self._entry_count():,} rows | folder: {path.name or path}"
                )
            else:
                self.status.setText(
                    f"{self._entry_count():,} rows | file: {path.name} | "
                    f"size: {self._format_size(self._item_data(item, Qt.ItemDataRole.UserRole + 2) or 0)}"
                )
            self._refresh_row_styles()
            self.current_path_changed.emit(path)
            return

        self.status.setText(f"{self._entry_count():,} rows")
        self._refresh_row_styles()
        self.current_path_changed.emit(None)

    def _toggle_current_selection(self) -> None:
        item = self._current_browser_item()
        if item is None or self._item_data(item, Qt.ItemDataRole.UserRole + 1) != "entry":
            return
        path = self._item_data(item, Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return
        if path in self.marked_paths:
            self.marked_paths.remove(path)
        else:
            self.marked_paths.add(path)
        if path.is_dir():
            self._compute_and_apply_dir_size(item, path)
        self._advance_current_item()
        self._update_status()

    def _compute_and_apply_dir_size(self, item, path: Path) -> None:
        """Compute total bytes under `path` and update the size column.

        v1: synchronous walk capped at 50 000 entries so we never hang the
        UI on pathological trees. For trees over the cap the column shows
        "(>50k items)" instead of a number. Move to QThreadPool when we
        have a baseline for typical sizes.
        """
        size, capped = self._dir_size_with_cap(path, cap=50_000)
        if isinstance(item, QTreeWidgetItem):
            label = self._format_size(size) + (" (capped)" if capped else "")
            item.setText(2, label)
            item.setData(0, Qt.ItemDataRole.UserRole + 2, size)

    @staticmethod
    def _dir_size_with_cap(root: Path, *, cap: int) -> tuple[int, bool]:
        total = 0
        seen = 0
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                with __import__("os").scandir(current) as it:
                    for entry in it:
                        seen += 1
                        if seen > cap:
                            return total, True
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            else:
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        return total, False

    def _go_up(self) -> None:
        self.navigate_to(self.active_tab.path.parent)

    def _navigate_back(self) -> None:
        self._ensure_tab_history(self.active_tab)
        if self.active_tab.navigation_index <= 0:
            return
        self.active_tab.navigation_index -= 1
        self.navigate_to(
            self.active_tab.navigation_history[self.active_tab.navigation_index],
            record_history=False,
        )

    def _toggle_folder_browser(self) -> None:
        should_show = not self.folder_browser.isVisible()
        self.folder_browser.setVisible(should_show)
        if should_show:
            self.content_splitter.setSizes([260, max(640, self.width() - 260)])
            self.folder_browser.tree.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            self.content_splitter.setSizes([0, 1])
            self._current_browser_widget().setFocus(Qt.FocusReason.TabFocusReason)

    def _toggle_bookmark(self) -> None:
        self.bookmark_store.toggle(self.current_directory())
        self._update_bookmark_button()

    def _update_bookmark_button(self) -> None:
        if self.bookmark_store.is_bookmarked(self.current_directory()):
            self.bookmark_toggle.setText("★")
            self.bookmark_toggle.setToolTip("Remove bookmark")
            self.bookmark_toggle.setProperty("active", True)
        else:
            self.bookmark_toggle.setText("☆")
            self.bookmark_toggle.setToolTip("Add bookmark")
            self.bookmark_toggle.setProperty("active", False)
        self.bookmark_toggle.style().unpolish(self.bookmark_toggle)
        self.bookmark_toggle.style().polish(self.bookmark_toggle)
        self.bookmark_toggle.update()

    def _rebuild_breadcrumbs(self, path: Path) -> None:
        while self.breadcrumb_layout.count():
            child = self.breadcrumb_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                if widget in {self.back_button, self.bookmark_toggle}:
                    widget.setParent(None)
                    continue
                widget.deleteLater()

        self.breadcrumb_layout.addWidget(self.back_button)
        segments = self._path_segments(path)
        for index, (label, segment_path) in enumerate(segments):
            button = QPushButton(label)
            button.setObjectName("breadcrumbButton")
            button.setProperty("current", index == len(segments) - 1)
            button.clicked.connect(lambda _checked=False, p=segment_path: self.navigate_to(p))
            self.breadcrumb_layout.addWidget(button)

            if index != len(segments) - 1:
                separator = QLabel("›")
                separator.setObjectName("breadcrumbSeparator")
                self.breadcrumb_layout.addWidget(separator)

        self.breadcrumb_layout.addStretch(1)
        self.breadcrumb_layout.addWidget(self.bookmark_toggle)

    def _ensure_tab_history(self, tab: TabState) -> None:
        if not tab.navigation_history:
            tab.navigation_history = [tab.path]
            tab.navigation_index = 0
            return
        tab.navigation_index = max(0, min(tab.navigation_index, len(tab.navigation_history) - 1))

    def _record_navigation(self, path: Path) -> None:
        tab = self.active_tab
        if tab.navigation_index < len(tab.navigation_history) - 1:
            tab.navigation_history = tab.navigation_history[: tab.navigation_index + 1]
        if not tab.navigation_history or tab.navigation_history[-1] != path:
            tab.navigation_history.append(path)
        tab.navigation_index = len(tab.navigation_history) - 1

    def _update_navigation_buttons(self) -> None:
        self.back_button.setEnabled(self.active_tab.navigation_index > 0)

    def _path_segments(self, path: Path) -> list[tuple[str, Path]]:
        parts = list(path.parts)
        if not parts:
            return [(str(path), path)]

        segments: list[tuple[str, Path]] = []
        current = Path(parts[0])
        root_label = parts[0].rstrip("\\") or parts[0]
        segments.append((root_label, current))
        for part in parts[1:]:
            current = current / part
            segments.append((part, current))
        return segments

    def _refresh_row_styles(self) -> None:
        palette = self.theme_palette
        current_item = self.file_list.currentItem()
        # QAbstractScrollArea redirects focus to its viewport via focusProxy,
        # so file_list.hasFocus() is False whenever the user is actually
        # interacting with the list. Treat viewport focus as list focus.
        has_focus = self.file_list.hasFocus() or self.file_list.viewport().hasFocus()

        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            item_type = item.data(0, Qt.ItemDataRole.UserRole + 3)
            is_current = item is current_item
            item_path = item.data(0, Qt.ItemDataRole.UserRole)
            is_selected = isinstance(item_path, Path) and item_path in self.marked_paths
            is_drop_target = isinstance(item_path, Path) and item_path == self._drop_target_dir and item_type == "dir"
            is_cut_pending = isinstance(item_path, Path) and item_path in self._cut_pending_paths

            base_bg = QColor(palette.row_even_bg if row % 2 == 0 else palette.row_odd_bg)
            fg = QColor(palette.text_primary)
            font = QFont()

            if item_type == "parent":
                base_bg = QColor(palette.chip_muted_bg)
                fg = QColor(palette.text_muted)
                font.setItalic(True)

            if is_selected and is_current:
                base_bg = QColor(
                    palette.row_marked_current_bg if has_focus else palette.row_current_bg
                )
                fg = QColor(palette.row_marked_current_text)
                font.setBold(True)
            elif is_selected:
                base_bg = QColor(palette.row_marked_bg)
                fg = QColor(palette.row_marked_text)
                font.setBold(True)
            elif is_current:
                base_bg = QColor(palette.active_pane_border)
                fg = QColor(palette.chip_text)
            if is_drop_target:
                base_bg = QColor(palette.row_drop_target_bg)
                fg = QColor(palette.row_drop_target_text)
                font.setBold(True)
            elif is_cut_pending:
                base_bg = QColor(palette.row_cut_pending_bg)
                fg = QColor(palette.row_cut_pending_text)
                font.setItalic(True)

            for column in range(self.file_list.columnCount()):
                item.setBackground(column, QBrush(base_bg))
                item.setForeground(column, QBrush(fg))
                item.setFont(column, font)

        current_thumb = self.thumbnail_list.currentItem()
        thumb_has_focus = self.thumbnail_list.hasFocus() or self.thumbnail_list.viewport().hasFocus()
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            item_type = item.data(Qt.ItemDataRole.UserRole + 3)
            is_current = item is current_thumb
            item_path = item.data(Qt.ItemDataRole.UserRole)
            is_selected = isinstance(item_path, Path) and item_path in self.marked_paths
            is_drop_target = isinstance(item_path, Path) and item_path == self._drop_target_dir and item_type == "dir"
            is_cut_pending = isinstance(item_path, Path) and item_path in self._cut_pending_paths

            base_bg = QColor(palette.row_even_bg)
            fg = QColor(palette.text_primary)
            font = QFont()

            if item.data(Qt.ItemDataRole.UserRole + 1) == "parent":
                base_bg = QColor(palette.chip_muted_bg)
                fg = QColor(palette.text_muted)
                font.setItalic(True)

            if is_selected and is_current:
                base_bg = QColor(
                    palette.row_marked_current_bg if thumb_has_focus else palette.row_current_bg
                )
                fg = QColor(palette.row_marked_current_text)
                font.setBold(True)
            elif is_selected:
                base_bg = QColor(palette.row_marked_bg)
                fg = QColor(palette.row_marked_text)
                font.setBold(True)
            elif is_current:
                base_bg = QColor(palette.active_pane_border)
                fg = QColor(palette.chip_text)
            if is_drop_target:
                base_bg = QColor(palette.row_drop_target_bg)
                fg = QColor(palette.row_drop_target_text)
                font.setBold(True)
            elif is_cut_pending:
                base_bg = QColor(palette.row_cut_pending_bg)
                fg = QColor(palette.row_cut_pending_text)
                font.setItalic(True)

            item.setBackground(QBrush(base_bg))
            item.setForeground(QBrush(fg))
            item.setFont(font)

    def _mark_all_entries(self) -> None:
        self.marked_paths.clear()
        for row in range(self.file_list.topLevelItemCount()):
            item = self.file_list.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
                continue
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(path, Path):
                self.marked_paths.add(path)
        self._update_status()

    def _clear_marks(self) -> None:
        if not self.marked_paths:
            return
        self.marked_paths.clear()
        self._update_status()

    def _show_item_context_menu(self, source_widget, position: QPoint) -> None:
        item = source_widget.itemAt(position)
        menu = QMenu(self)
        menu.setObjectName("contextMenu")

        if item is None:
            refresh_action = menu.addAction("Refresh")
            new_folder_action = menu.addAction("New Folder")
            chosen = menu.exec(source_widget.viewport().mapToGlobal(position))
            if chosen == refresh_action:
                self.refresh()
            elif chosen == new_folder_action:
                self.operation_requested.emit("mkdir")
            return

        item_type = self._item_data(item, Qt.ItemDataRole.UserRole + 1)
        path = self._item_data(item, Qt.ItemDataRole.UserRole)

        if item_type == "parent" and isinstance(path, Path):
            open_parent_action = menu.addAction("Open Parent")
            chosen = menu.exec(source_widget.viewport().mapToGlobal(position))
            if chosen == open_parent_action:
                self.navigate_to(path)
            return

        if item_type != "entry" or not isinstance(path, Path):
            return

        source_widget.setCurrentItem(item)
        self._set_current_path(path)

        if path.is_dir():
            open_action = menu.addAction("Open")
            open_new_tab_action = menu.addAction("Open In New Tab")
            bookmark_action = menu.addAction(
                "Remove Bookmark" if self.bookmark_store.is_bookmarked(path) else "Bookmark Folder"
            )
            menu.addSeparator()
        else:
            open_action = None
            open_new_tab_action = None
            bookmark_action = None

        copy_action = menu.addAction("Copy")
        move_action = menu.addAction("Move")
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        refresh_action = menu.addAction("Refresh")

        chosen = menu.exec(source_widget.viewport().mapToGlobal(position))
        if open_action is not None and chosen == open_action:
            self.navigate_to(path)
        elif open_new_tab_action is not None and chosen == open_new_tab_action:
            self.open_new_tab(path)
        elif bookmark_action is not None and chosen == bookmark_action:
            self.bookmark_store.toggle(path)
            self._update_bookmark_button()
        elif chosen == copy_action:
            self.operation_requested.emit("copy")
        elif chosen == move_action:
            self.operation_requested.emit("move")
        elif chosen == rename_action:
            self.operation_requested.emit("rename")
        elif chosen == delete_action:
            self.operation_requested.emit("delete")
        elif chosen == refresh_action:
            self.refresh()

    def _format_size(self, size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value):,} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024

    def _rebuild_tab_strip(self) -> None:
        while self.tab_strip_layout.count():
            child = self.tab_strip_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        for index, tab in enumerate(self.pane_state.tabs):
            tab_button = QPushButton(tab.title)
            tab_button.setObjectName("tabButton")
            tab_button.setProperty("active", index == self.pane_state.active_tab_index)
            tab_button.clicked.connect(lambda _checked=False, i=index: self.activate_tab(i))
            tab_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tab_button.customContextMenuRequested.connect(
                lambda position, i=index, button=tab_button: self._show_tab_context_menu(i, button.mapToGlobal(position))
            )
            self.tab_strip_layout.addWidget(tab_button)

        new_tab_button = QPushButton("+")
        new_tab_button.setObjectName("tabAddButton")
        new_tab_button.clicked.connect(self.open_new_tab)
        self.tab_strip_layout.addWidget(new_tab_button)
        self.tab_strip_layout.addStretch(1)

    def _show_tab_context_menu(self, index: int, global_position: QPoint) -> None:
        if index < 0 or index >= len(self.pane_state.tabs):
            return

        menu = QMenu(self)
        menu.setObjectName("contextMenu")
        open_other_action = menu.addAction("Open In The Other Panel")
        close_action = menu.addAction("Close Tab")
        if len(self.pane_state.tabs) <= 1:
            close_action.setEnabled(False)

        chosen = menu.exec(global_position)
        if chosen == open_other_action:
            self.open_in_other_pane_requested.emit(self.pane_state.tabs[index].path)
        elif chosen == close_action:
            self.close_tab(index)
