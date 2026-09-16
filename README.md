# Multi-Pane Commander

A Total Commander-inspired, keyboard-first file manager built on PySide6.

Designed around the workflow that anyone who's used Norton/Total/Windows Commander will recognise: side-by-side panes with tabs, a function-key bar at the bottom, an embedded terminal that follows the active pane's directory, drive buttons, and the F5/F6/F7/F8 muscle memory.

The full design intent and scope is in [SPEC.md](SPEC.md). The change history is in [CHANGELOG.md](CHANGELOG.md).

## Status

v1, in active development. Cross-platform but primarily tested on macOS at the moment. Linux and Windows should also work — the core uses PySide6 + standard library, with platform-specific bits gated behind capability checks (e.g. `pywinpty` for Windows terminal, `send2trash` for the Recycle-Bin path).

## Quickstart

```bash
# 1. Create a venv and install runtime deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install PySide6 send2trash py7zr libarchive-c watchdog pygments
# Optional: pywinpty (Windows terminal), Pygments lexers, etc.

# 2. Run from the repo root
python run_app.py
```

Or, after `pip install -e .`:

```bash
mpc
```

## Keyboard surface

The classic keys do what you'd expect — `F5`/`F6`/`F7`/`F8` for copy / move / mkdir / delete, `F2` or `Shift+F6` for rename, `F3` for Quick View, `F4` for Edit, `F9` for the embedded terminal, `Tab` to switch panes, `Insert` / `Space` to mark, `Backspace` for parent, `Enter` to descend / launch.

Beyond the basics:

| Key | Action |
|-----|--------|
| Type any character | Quick-jump to first entry starting with the typed prefix (750 ms timeout) |
| `Ctrl+S` | Quick-filter bar — narrows the pane in place |
| `Alt+F1` / `Alt+F2` | Drive menu for active / passive pane |
| `Alt+F7` | Find files (glob name + content search) |
| `Ctrl+M` | Multi-rename (`[N]`, `[E]`, `[C]`, `[C0n]` tokens, live preview) |
| `Ctrl+Z` | Undo last rename, multi-rename batch, or move (50 operations per session) |
| `Shift+F8` / `Shift+Del` | Permanent delete (bypass Recycle Bin) |
| `Ctrl+Enter` / `Alt+Enter` | Paste cursor name / full path into the terminal |
| `Alt+Arrow` | Focus pane in that direction |
| `Alt+1` … `Alt+7` | Layout presets (Alt+7 uses a compact left-pane window; F9 adds the terminal below it) |
| `Space` (on a directory) | Compute recursive size |
| `Shift+F3` / `Shift+F4` | Open in OS-associated viewer / default app |

The full keymap and design rationale live in [SPEC.md §14](SPEC.md).

## Highlights

- **Quick View (F3)** with first-class renderers for Markdown, HTML (with optional `QWebEngineView` "Web" mode), PDF, SVG, image (incl. `.tiff`/`.ico`/`.heic`), CSV/TSV (sortable table), audio/video (`QMediaPlayer`, no autoplay), archives (`.zip` / `.tar.*` / `.7z` / `.rar` / `.jar`), syntax-highlighted source via Pygments, and a hex dump fallback for binaries. A "Raw" toggle (`Ctrl+Shift+R` or the header button) flips any rich renderer back to the underlying source.
- **Read-only archive browsing** — `Enter` on a `.zip` / `.tar.*` / `.7z` / `.rar` / `.jar` enters the archive as if it were a directory. F5 from inside an archive extracts files or complete folder trees to the local filesystem. Copying or moving the archive itself transfers the original archive file.
- **Embedded shell** — a shared terminal core and bundled xterm.js renderer, with PTY support, prompt-aware directory following, search, zoom, copy/paste, and pinned commands. **Layout (F11) → Terminal compatibility (next launch)** selects standard or classic controls without replacing the current session. Claude Code uses the same renderer and process backend while keeping its separate per-folder sessions.
- **Embedded terminal** that follows the active pane's directory by default.
- **Custom marking model** — `Insert`/`Space` toggle marks (separate from cursor selection) so multi-file ops compose naturally with cursor movement.
- **Find Files** with glob name patterns + optional case-insensitive content search; binary files skipped via NUL-byte sniff; results capped at 5 000.
- **Multi-Rename dialog** with live preview and collision detection.
- **Undo** for renames, grouped multi-renames, and successful moves, including restoring the previous destination after a move/overwrite. A failed undo remains available for retry. History lasts for the current session and holds up to 50 operations.
- **Background browsing and search** with incremental list rendering, streamed search results, a Stop button, and visible-image thumbnail loading.
- **Automatic folder refresh** preserves cursor, marks, filter, and scroll position after external changes. Native directory notifications are backed by periodic checks while the pane is visible.
- **Transfer progress** shows action counts plus bytes, speed, and estimated time remaining for the current item. Cancellation checks run between copy blocks and archive members. Closing the app requests cancellation and waits for active file jobs to finish safely.

Copy and extraction stage output before replacing an existing destination. Moves retain the previous destination in a sibling `.mpc-bak` file while undo is available; those backups are removed when history expires or the app closes normally. Recovery copies may remain after an interrupted process or failed cleanup. Once a cross-volume move has committed its destination, source cleanup finishes without cancellation to avoid leaving a half-deleted source.

## Architecture

```
src/multipane_commander/
├── app.py                    Entry point
├── ui/
│   ├── main_window.py        Window chrome, menu, F-key bar, global shortcuts
│   ├── pane_view.py          Panes — file list, breadcrumb, tabs, marquee, marks
│   ├── quick_view.py         F3 renderer pipeline (markdown / pdf / media / hex / …)
│   ├── multi_rename_dialog.py  Ctrl+M
│   ├── find_files_dialog.py    Alt+F7
│   ├── folder_browser.py     Tree sidebar
│   ├── terminal_dock.py      Classic controls over the shared terminal core
│   ├── terminal_commands.py  Shared command dispatch and history
│   ├── deep_terminal/        Standard dock, shared xterm.js surface, compatibility picker
│   └── themes.py             Palette, QSS
├── services/
│   ├── fs/local_fs.py        LocalFileSystem
│   ├── fs/archive_fs.py      ArchiveFileSystem (read-only over libarchive-c)
│   ├── jobs/                 Background copy/move/delete via QThread
│   ├── bookmarks.py
│   └── undo.py               UndoStack (LIFO, capacity 50)
├── terminal/
│   ├── deep/                 Shared PTY backends, shell-integration parser, session
│   └── session.py            Classic session compatibility adapter
├── state/                    Per-tab state, persistence
└── platform/                 Platform-specific helpers (root paths, etc.)
```

The file-system abstraction is plugin-ready: panes hold a `self.fs` that swaps between `LocalFileSystem` and `ArchiveFileSystem` based on whether the active path is inside an archive. The same approach extends to network filesystems / cloud providers without rewriting the UI.

## Testing

```bash
# Full suite
pytest

# Just the keyboard surface (regression + per-feature)
pytest tests/test_keyboard_shortcuts.py

# End-to-end scenarios (real MainWindow over a synthetic AppContext)
pytest tests/test_e2e_scenarios.py
```

GitHub Actions runs Ruff and pytest on Windows, Linux, and macOS with Python 3.12, plus Windows with Python 3.13. Cross-platform CI results are available after a push or pull request.

Tests run headless via `QT_QPA_PLATFORM=offscreen` (no display server needed). The keyboard suite is regression-first: `R1`–`R13` cover the keys that already worked when this work began, and `F*` tests cover each new binding.

## Project goals (and non-goals)

See [SPEC.md §2](SPEC.md). In short: reproduce the parts of the TC workflow the author misses, do them better than TC in a few specific places (real undo, native image thumbnails, richer Quick View), and keep the v1 scope tight enough to ship.

Non-goals for v1: cloud providers, custom plugin hosting, multi-window, theming UI. Those are stretch items if the core shell stabilises.

## License

Not yet declared. Treat as "all rights reserved" until a LICENSE is added.
