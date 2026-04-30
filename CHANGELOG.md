# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- (P0 #1) Up/Down/PgUp/PgDn/Home/End now move the cursor in file panes. `PaneView` was accepting focus on the container instead of routing it to the inner `QTreeWidget`, so arrow keys hit the QFrame default and never reached the list. Fixed by setting `setFocusProxy(self.file_list)`.
- F5 now emits `"copy"` (TC convention) instead of `"refresh"`. `PaneView.keyPressEvent` was checking `QKeySequence.StandardKey.Refresh` before the explicit F5 branch, and Qt maps `StandardKey.Refresh` to F5 on several platforms (collision). Removed the `StandardKey.Refresh` check; explicit Ctrl+R still triggers refresh.
- (P0 #2) Enter on a file now launches it via the OS default association (`QDesktopServices.openUrl`). Previously `_activate_item` was a no-op for files — only directories descended. Behaviour for directories and the `..` row is unchanged.

### Added

- (P0 #4) F4 (Edit) and F10 (Menu) are now real, not "not implemented" dialogs.
  - F4 launches a text editor for the cursor item via `launch_editor()` — resolution chain: `$VISUAL` → `$EDITOR` → `code` on PATH → OS default association. Bound as a `QShortcut` (previously F4 was only on the on-screen function-key bar).
  - F10 opens a context menu organised by SPEC §5.4 sections (File / Mark / Commands / Show), with each entry connected to its existing handler (Rename / Copy / Move / MkDir / Delete / Mark all / Refresh / New tab / Toggle terminal / Layout / Jobs / Thumbnails). Bound as a `QShortcut` and surfaced through the function-key bar.

### Verified

- (P0 #3) SPEC §16 spike-3 ("F-keys fire while a path field or the terminal has focus") is met by the existing `QShortcut` + `WindowShortcut` setup. Empirically confirmed: `QLineEdit` and `QPlainTextEdit` (the widget classes used by the breadcrumb path bar and terminal surface) do not consume F-key events, so Qt's shortcut system routes them to the `MainWindow` handler regardless of which child holds focus. Locked in `test_F0_3_f_keys_fire_with_qlineedit_focused`. **Caveat:** if the terminal is migrated to `QWebEngineView` per SPEC §8.1, web views consume keys aggressively and a global event filter or `ApplicationShortcut` context will be required at that point.

### Tests

- Added `tests/test_keyboard_shortcuts.py` — regression suite (R1–R13) covering F2 / Shift+F6 rename, F5/F6/F7/F8/Delete operations, Backspace navigation, Insert/Space selection toggle (with TC-style cursor advance), Esc clear-marks, Ctrl+A mark-all, Ctrl+R refresh, Enter on directory / parent row.
