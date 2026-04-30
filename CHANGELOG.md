# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Tests

- Added `tests/test_keyboard_shortcuts.py` — regression suite (R1–R13) covering F2 / Shift+F6 rename, F6/F7/F8/Delete operations, Backspace navigation, Insert/Space selection toggle (with TC-style cursor advance), Esc clear-marks, Ctrl+A mark-all, Ctrl+R refresh, Enter on directory / parent row.

### Notes

- Regression suite surfaced a P0 bug: **F5 currently emits `"refresh"` instead of `"copy"`** because `QKeySequence.StandardKey.Refresh` matches F5 and the Refresh branch runs first in `PaneView.keyPressEvent`. Locked as a known-quirk test (`test_R2_known_quirk_f5_routes_to_refresh_via_standardkey`) until fixed.
