from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QFileInfo, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFileIconProvider,
    QFrame,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from multipane_commander.platform import root_paths, root_section_label
from multipane_commander.services.bookmarks import BookmarkStore


class FolderBrowser(QFrame):
    path_selected = Signal(object)

    def __init__(self, *, bookmark_store: BookmarkStore) -> None:
        super().__init__()
        self.bookmark_store = bookmark_store
        self.icon_provider = QFileIconProvider()
        self.tree = QTreeWidget()
        self.tree.setObjectName("folderBrowserTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemActivated.connect(lambda item, _column: self._activate_item(item))
        self.tree.itemClicked.connect(lambda item, _column: self._activate_item(item))
        self.tree.itemExpanded.connect(self._expand_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.installEventFilter(self)

        self.setObjectName("folderBrowser")
        self.setMinimumWidth(250)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

        self.bookmark_store.bookmarks_changed.connect(lambda _bookmarks: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        expanded_labels = self._expanded_labels()
        self.tree.clear()

        self._add_bookmark_section()
        self._add_quick_access_section()
        self._add_root_section()

        for label in expanded_labels:
            matches = self.tree.findItems(label, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
            for item in matches:
                if item.data(0, Qt.ItemDataRole.UserRole + 10) == "section":
                    item.setExpanded(True)

    def _add_bookmark_section(self) -> None:
        section = self._section_item("Bookmarks")
        self.tree.addTopLevelItem(section)
        for path in self.bookmark_store.bookmarks():
            section.addChild(self._path_item(path, label=path.name or str(path), source_kind="bookmark"))
        section.setExpanded(True)

    def _add_quick_access_section(self) -> None:
        section = self._section_item("Quick Access")
        self.tree.addTopLevelItem(section)

        for label, path in self._quick_access_paths():
            if path.exists():
                section.addChild(self._path_item(path, label=label, source_kind="shortcut"))
        section.setExpanded(True)

    def _add_root_section(self) -> None:
        section = self._section_item(root_section_label())
        self.tree.addTopLevelItem(section)

        for root_path in root_paths():
            root_item = self._path_item(root_path, label=root_path.name or str(root_path), source_kind="drive")
            self._add_placeholder_if_needed(root_item, root_path)
            section.addChild(root_item)
        section.setExpanded(True)

    def _section_item(self, label: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole + 10, "section")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        return item

    def _path_item(
        self,
        path: Path,
        *,
        label: str | None = None,
        source_kind: str = "tree",
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label or (path.name or str(path))])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 10, "path")
        item.setData(0, Qt.ItemDataRole.UserRole + 11, source_kind)
        item.setToolTip(0, str(path))
        item.setIcon(0, self.icon_provider.icon(QFileInfo(str(path))))
        return item

    def _add_placeholder_if_needed(self, item: QTreeWidgetItem, path: Path) -> None:
        try:
            has_child_dirs = any(child.is_dir() for child in path.iterdir())
        except OSError:
            return
        if not has_child_dirs:
            return

        placeholder = QTreeWidgetItem(["Loading..."])
        placeholder.setData(0, Qt.ItemDataRole.UserRole + 10, "placeholder")
        item.addChild(placeholder)

    def _expand_item(self, item: QTreeWidgetItem) -> None:
        if item.childCount() != 1:
            return
        if item.child(0).data(0, Qt.ItemDataRole.UserRole + 10) != "placeholder":
            return

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return

        item.takeChildren()
        try:
            directories = sorted(
                [child for child in path.iterdir() if child.is_dir()],
                key=lambda child: child.name.lower(),
            )
        except OSError:
            return

        for child in directories:
            child_item = self._path_item(child, source_kind="tree")
            self._add_placeholder_if_needed(child_item, child)
            item.addChild(child_item)

    def _activate_item(self, item: QTreeWidgetItem) -> None:
        if item.data(0, Qt.ItemDataRole.UserRole + 10) != "path":
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(path, Path) and path.exists() and path.is_dir():
            self.path_selected.emit(path)

    def _expanded_labels(self) -> set[str]:
        expanded: set[str] = set()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.isExpanded():
                expanded.add(item.text(0))
        return expanded

    def _quick_access_paths(self) -> list[tuple[str, Path]]:
        home = Path.home()
        candidates = [
            ("Home", home),
            ("Desktop", home / "Desktop"),
            ("Downloads", home / "Downloads"),
            ("Documents", home / "Documents"),
            ("Pictures", home / "Pictures"),
            ("Music", home / "Music"),
            ("Videos", home / "Videos"),
        ]

        one_drive = home / "OneDrive"
        if one_drive.exists():
            candidates.insert(2, ("OneDrive", one_drive))
        return candidates

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.tree and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Delete:
                if self._remove_selected_bookmark():
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _remove_selected_bookmark(self) -> bool:
        item = self.tree.currentItem()
        if item is None:
            return False
        if item.data(0, Qt.ItemDataRole.UserRole + 11) != "bookmark":
            return False

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, Path):
            return False

        self.bookmark_store.remove(path)
        return True

    def _show_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)

        source_kind = item.data(0, Qt.ItemDataRole.UserRole + 11)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.setObjectName("contextMenu")

        if isinstance(path, Path):
            open_action = menu.addAction("Open")
            if source_kind == "bookmark":
                remove_action = menu.addAction("Remove Bookmark")
            else:
                remove_action = None
        else:
            return

        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if open_action is not None and chosen == open_action and path.exists() and path.is_dir():
            self.path_selected.emit(path)
        elif remove_action is not None and chosen == remove_action:
            self.bookmark_store.remove(path)
