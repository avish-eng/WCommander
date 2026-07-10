# Multi-Pane Commander — User Help

A practical guide to using the app day-to-day. For design rationale and scope, see [SPEC.md](SPEC.md). For change history, see [CHANGELOG.md](CHANGELOG.md).

---

## 1. Install & launch

```bash
# Create a venv and install runtime deps
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install PySide6 send2trash py7zr libarchive-c watchdog pygments
# Optional extras: pywinpty (Windows terminal), Pygments lexers

# Run from the repo root
python run_app.py
```

Or, after `pip install -e .`:

```bash
mpc
```

Tested primarily on macOS; Linux and Windows should also work — platform-specific bits (`pywinpty`, `send2trash`) are gated behind capability checks.

---

## 2. The window at a glance

```
┌──────────────────────────────────────────────────────────┐
│ Menu bar      File  Mark  Commands  Show  Config         │
│ Drive buttons [C:] [D:] [\\server]                       │
│ Tabs          [home] [downloads] [+] │ [docs] [work] [+] │
├──────────────────────────────────────┼───────────────────┤
│ Active pane — file list              │ Passive pane      │
│  cursor row, marks, breadcrumb       │  (peer)           │
├──────────────────────────────────────┴───────────────────┤
│ Command bar   pwd> _                                     │
│ Embedded terminal (toggle with F9)                       │
│ F1 Help  F3 View  F4 Edit  F5 Copy  F6 Move  F7 MkDir … │
└──────────────────────────────────────────────────────────┘
```

- **Active pane** is the one with keyboard focus. Switch with `Tab` or `Alt+Arrow`.
- **Marks** (set with `Insert` / `Space`) are the multi-file selection that `F5`/`F6`/`F8` operate on. Marks are independent of the cursor.
- The **passive pane** is the default destination for copy/move.

---

## 3. The basics — what to press first

| You want to... | Press |
|---|---|
| Move the cursor | `↑` `↓` `PgUp` `PgDn` `Home` `End` |
| Enter a directory / launch a file | `Enter` |
| Go up one level | `Backspace` |
| Switch to the other pane | `Tab` |
| Mark a file (toggle) | `Insert` or `Space` |
| Mark all | `Ctrl+A` |
| Clear marks | `Esc` |
| Refresh the active pane | `Ctrl+R` |
| Quick-jump to a name | Just start typing (750 ms timeout) |
| Filter the list in place | `Ctrl+S`, type, `Enter` to keep, `Esc` to clear |

---

## 4. Function keys (the classic TC bar)

| Key | Action |
|---|---|
| `F1` | Help |
| `F2` | Rename cursor item (alias: `Shift+F6`) |
| `F3` | Quick View — preview cursor item in the passive pane |
| `Shift+F3` | Open in OS-associated viewer |
| `F4` | Edit — text editor for text files, default app for binaries |
| `Shift+F4` | Open in OS default app (regardless of `$EDITOR`) |
| `F5` | Copy marked items to passive pane |
| `F6` | Move marked items to passive pane |
| `F7` | Make directory |
| `F8` / `Delete` | Delete to Recycle Bin / Trash |
| `Shift+F8` / `Shift+Del` | Permanent delete (skip Trash, with extra confirmation) |
| `F9` | Toggle embedded terminal (alias: `Ctrl+\``) |
| `F10` | Main menu |
| `F11` | Layout presets menu |
| `F12` | Jobs view (running/backgrounded operations) |

F-keys fire globally — they work even while the path field or terminal has focus.

---

## 5. Quick View (F3)

Press `F3` with the cursor on any file to preview it in the passive pane.

Built-in renderers:

- **Text & code** — Pygments syntax highlighting (Python, TS, JSON, YAML, Rust, Go, SQL, shell, Dockerfile, TOML, …)
- **Markdown** (`.md`, `.markdown`) — rendered via QTextBrowser
- **HTML** (`.html`, `.htm`) — static render; toggle "Web" for full Chromium (`QWebEngineView`)
- **PDF** — page navigation
- **SVG** and images — `.png`, `.jpg`, `.gif`, `.webp`, `.tiff`, `.tif`, `.ico`, `.heic`
- **CSV / TSV** — sortable table (capped at 1 000 × 100 cells)
- **Audio / video** — `QMediaPlayer` with scrubbable seek bar; **does not autoplay**
- **Archives** — directory listing for `.zip`, `.tar(.gz/.bz2/.xz)`, `.7z`, `.rar`, `.jar`
- **Binaries** — offset/hex/ASCII dump of the first 4 KB

Toggles inside Quick View:

| Key | Action |
|---|---|
| `Tab` (in viewer) or `Ctrl+Shift+R` | Raw mode — show underlying source for any rich renderer |
| Header "Web" button | HTML files only — switch to Chromium render |
| `Ctrl+I` | AI mode toggle (see §10) |

---

## 6. Working with archives

Archives behave like directories:

- `Enter` on a `.zip` / `.tar.*` / `.7z` / `.rar` / `.jar` to **enter** it.
- Navigate inside as if it were a folder.
- `Backspace` at the archive root takes you back out to the local filesystem.
- `F3` on a file inside an archive previews it (extracted to a temp file behind the scenes).
- `F5` from inside an archive **extracts** the marked entries to the destination pane.
- `F6` from inside an archive raises a clear "read-only" error — archives are not yet mutable.

---

## 7. Power features

### Multi-rename — `Ctrl+M`

Batch-rename the marked selection with a live preview table.

- Tokens: `[N]` = original name, `[E]` = extension, `[C]` = counter, `[C0n]` = zero-padded counter
- Collisions (target exists, or two sources collapse to one name) are highlighted red and skipped on commit
- Each successful rename pushes onto the undo stack — `Ctrl+Z` reverses them one at a time
- Regex find/replace is **out of v1 scope**

### Find files — `Alt+F7`

- Glob patterns for filenames; recursive toggle
- Optional case-insensitive substring **content** search
- Binary files skipped via NUL-byte sniff; files >10 MB skipped on content search; results capped at 5 000
- Double-click a result → active pane navigates to the result's parent directory

### Undo — `Ctrl+Z`

- Reverses the most recent **rename** (multi-rename rolls back one entry at a time)
- LIFO stack, capacity 50
- 5-minute "fresh" window; older entries dim and require confirmation
- Move and delete undo are not implemented in v1

### Directory size — `Space` on a directory

Computes recursive size and updates the Size column. Synchronous, capped at 50 000 entries (capped results are labelled `(capped)`).

---

## 8. Panes, tabs, and layouts

### Panes

| Key | Action |
|---|---|
| `Tab` / `Shift+Tab` | Cycle to the next / previous pane |
| `Alt+Left` / `Alt+Right` / `Alt+Up` / `Alt+Down` | Focus the spatially nearest pane in that direction |
| `Alt+F1` / `Alt+F2` | Drive/mount menu for the active / passive pane |

### Tabs

| Key | Action |
|---|---|
| `Ctrl+T` | New tab in the active pane |
| `Ctrl+W` | Close tab (closing the last tab closes the pane) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Cycle tabs within the active pane |

### Layout presets

`F11` opens the layout menu. Direct shortcuts:

| Key | Preset |
|---|---|
| `Alt+1` | Default |
| `Alt+2` | Focus files |
| `Alt+3` | Focus terminal |
| `Alt+4` | Terminal right |
| `Alt+5` | Terminal left |
| `Alt+6` | Balanced |
| `Alt+7` | Compact left pane only; press `F9` to add the terminal below it |

---

## 9. Terminal & command bar

### Embedded terminal — `F9` (alias `Ctrl+\``)

A real PTY-backed shell, docked at the bottom of the window.

- **Follow active pane** is on by default — pane navigation issues a `cd` so the terminal tracks the active pane's directory. Toggle off any time to let the two diverge.
- Showing the terminal moves focus to it, so `F9` doubles as "focus terminal" once it's open.

| Key | Action |
|---|---|
| `F9` / `Ctrl+\`` | Toggle terminal visibility |
| `Ctrl+Shift+\`` | Toggle terminal maximised |
| `Ctrl+Enter` | Paste the cursor item's **name** into the terminal (quoted if needed) |
| `Alt+Enter` | Paste the cursor item's **full path** into the terminal |
| `Ctrl+Shift+K` | Force-kill the program currently running in the terminal |

### Command bar — `Ctrl+G`

A persistent one-liner above the F-key bar that always shows the active pane's directory as a prompt.

- **Activate**: click it, press `Ctrl+G`, or just start typing while a pane has focus
- **Enter** — runs the command inline; output streams into a collapsible panel above the input. The active pane refreshes on process exit
- `cd <dir>` is intercepted and navigates the **active pane** instead of spawning a subprocess; bare `cd` goes to home
- **Shift+Enter** — escalates to the full terminal: opens it, navigates the PTY to the active pane's directory, and injects the command
- `↑` / `↓` cycle session command history (no persistence)
- `Esc` dismisses the output panel; pressing it again clears the input; again returns focus to the pane

---

## 10. AI features

The app embeds AI assistance inside the file manager.

| Key | Action |
|---|---|
| `Ctrl+K` | Open the AI command palette |
| `Ctrl+I` | Toggle AI view for the file currently in Quick View |
| `Ctrl+Shift+I` | Toggle the AI pane |
| `Ctrl+Shift+C` | Toggle the AI chat |

The passive pane can also host an embedded Claude Code terminal (F3-style) — switching between the file viewer and the Claude terminal preserves output buffer and session.

---

## 11. Clipboard & drag-and-drop

| Key | Action |
|---|---|
| `Ctrl+C` | Copy marked items to clipboard |
| `Ctrl+X` | Cut marked items |
| `Ctrl+V` | Paste clipboard into the active pane |

Drag-and-drop is unambiguous: drop pane = destination. With multiple panes:

- `Ctrl+drop` = copy
- `Shift+drop` = move
- `Alt+drop` = symlink

---

## 12. Background jobs — `F12`

Copy / move / delete / extract operations run as **independent background jobs**. Each shows a modal progress window with files / bytes / throughput / ETA, plus **Pause**, **Cancel**, and **Move to background** buttons.

- "Move to background" hides the modal but the job keeps running.
- `F12` opens the jobs view — a flyout listing every running/backgrounded job with progress, controls, and "bring to front".
- Per-physical-disk jobs are serialised; cross-disk jobs run in parallel.
- On quit, running jobs prompt: *"N file operations are still running. Wait / Cancel all / Force quit?"*
- Mixed results (some succeeded, some failed) are normal and shown explicitly — the UI never claims "done" for a partial result.

---

## 13. Where settings & state live

- **Config** — `%APPDATA%\MultiCommander\config.toml` (keybindings, theme, columns, button bar, file associations). Hot-reloaded on save.
- **State** — `%APPDATA%\MultiCommander\state.json` (window geometry, layout tree, per-pane tabs/dirs, terminal cwd). Restored on launch. Pass `--fresh` to skip restoring.
- **Thumbnail cache** — `%APPDATA%\MultiCommander\thumbs\`.

(On macOS / Linux, the equivalent application-data directory is used.)

Themes shipped: `tc-classic`, `tc-dark`, `nc-nostalgia`, `system`.

---

## 14. Troubleshooting

- **Arrow keys don't move the cursor** — make sure the file list (not the breadcrumb or a button) has focus. Click any row, or press `Tab` until the active pane highlights and refocuses its list.
- **Terminal won't start on Windows** — `pywinpty` must be installed: `pip install pywinpty`. On other platforms the terminal uses the system PTY.
- **Archive open fails with "unsupported"** — `libarchive-c` is required for `.7z` / `.rar` / `.tar.*`. `.zip` works without it via the stdlib.
- **F5 seems to refresh instead of copy** — fixed: F5 always means Copy. Refresh is `Ctrl+R`.
- **A delete didn't go to the trash** — `Shift+F8` and `Shift+Del` permanently delete. Use plain `F8` / `Delete` for the trash path.

---

## 15. Out of scope for v1

- Cloud / network filesystems (SFTP, FTP, S3, SMB)
- Plugin loading (architecture is plugin-ready; loader is stubbed)
- Multi-window, theming UI, i18n, telemetry
- Crash-safe undo persistence and job resumption after process failure
- Move / delete undo (rename undo only)
- Multi-pane operations across ≥3 panes — basic support only; fan-out / compare planned

See [SPEC.md §18](SPEC.md) for the full list.
