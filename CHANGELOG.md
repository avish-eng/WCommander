# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- (P0 #1) Up/Down/PgUp/PgDn/Home/End now move the cursor in file panes. `PaneView` was accepting focus on the container instead of routing it to the inner `QTreeWidget`, so arrow keys hit the QFrame default and never reached the list. Fixed by setting `setFocusProxy(self.file_list)`.
- F5 now emits `"copy"` (TC convention) instead of `"refresh"`. `PaneView.keyPressEvent` was checking `QKeySequence.StandardKey.Refresh` before the explicit F5 branch, and Qt maps `StandardKey.Refresh` to F5 on several platforms (collision). Removed the `StandardKey.Refresh` check; explicit Ctrl+R still triggers refresh.
- (P0 #2) Enter on a file now launches it via the OS default association (`QDesktopServices.openUrl`). Previously `_activate_item` was a no-op for files — only directories descended. Behaviour for directories and the `..` row is unchanged.

### Tests

- Added `tests/test_keyboard_shortcuts.py` — regression suite (R1–R13) covering F2 / Shift+F6 rename, F5/F6/F7/F8/Delete operations, Backspace navigation, Insert/Space selection toggle (with TC-style cursor advance), Esc clear-marks, Ctrl+A mark-all, Ctrl+R refresh, Enter on directory / parent row.
