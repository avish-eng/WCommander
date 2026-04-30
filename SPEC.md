# Multi-Pane Commander — Specification

A **Total Commander-inspired** orthodox file manager, built as a **Windows desktop GUI in Python using [PySide6](https://doc.qt.io/qtforpython-6/)**. Default layout is the classic **two-pane** view; users can open additional panes when they want them.

---

## 1. Context

- **Author & sole user:** one developer (the author) who wants the Total Commander experience back on modern Windows, in Python, on their own terms.
- **Single-user assumptions:** no i18n, no accessibility review, no telemetry, no crash-reporting backend, no pricing/licensing concerns, no onboarding UX. The target audience is "me."
- **Consequences:** we can skip preference-dialog polish, per-OS quirks, and bundle-size anxiety. If it works well on the author's Windows 11 machine, it ships.

## 2. Goals

- Reproduce the Total Commander workflow that the author misses: **dual-pane** files, tabs per pane, function-key bar, an always-available **real terminal**, drive buttons, keyboard-first with mouse support.
- Allow opening **additional panes** (up to 8) when a situation calls for it — 3-way compare, triage from multiple sources — without making the 2-pane case any less fluent.
- Ship classic TC power features that the author actually uses: multi-rename, find-in-files, byte-by-byte compare, and serious archive handling.
- Be better than TC in a few deliberate places: real undo, native image thumbnails, richer Quick View.

### 2.1 v1 Hard Requirements

- Two-pane workflow must feel fluent and keyboard-first.
- Embedded terminal must be a real PTY-backed terminal and pass the spike gate (§16).
- File operations must support backgrounding, conflict handling, undo for move/rename/delete, and clear failure reporting.
- Archives must behave like first-class containers: browse, extract, create, add, delete, rename, and test.
- Windows-specific realities (long paths, reparse points, elevation, locked files, UNC paths) must be handled deliberately rather than as undefined edge cases.

### 2.2 Stretch If The Core Shell Is Stable

- Rich Quick View for text/image/PDF/hex.
- Native image thumbnails with persistent cache.
- Directory compare/sync visualizations across 3+ panes.
- Tree view and thumbnail-grid view modes.

## 3. Non-Goals

- Not cross-platform. Windows 10/11 only.
- Not a shell replacement — but the embedded terminal **is** a real terminal (see §8), not a neutered command line.
- No cloud/remote backends in v1 (SFTP/S3 are post-v1 plugin concerns).
- No mobile, no web build.

---

## 4. Technology Stack

- **Language:** Python 3.12+
- **UI framework:** PySide6 (Qt Widgets desktop app)
- **Async runtime:** `asyncio` for FS and long-running ops, bridged cleanly into the Qt event loop
- **FS libs:** `pathlib`, `os`, `shutil`, `send2trash`, `py7zr` / `libarchive-c` for archives
- **Terminal:** `pywinpty` (ConPTY) + **xterm.js** inside a Qt web view, bridged via a local WebSocket (see §8). This is the same stack VS Code uses for its integrated terminal, so it's a proven path.
- **Packaging:** `flet pack` → single Windows `.exe`
- **Testing:** `pytest` for logic; ad-hoc manual testing for UI (single-user, so GUI-test investment is not worth it)

---

## 5. Layout Model

### 5.1 Panes

- A **pane** = an independent directory view with its own tabs, cursor, selection, sort, filter, and history.
- Exactly one pane is **active** (keyboard focus, highlighted header).
- Default layout on first launch: **two panes side-by-side** (classic TC).
- Panes live inside a **layout tree** of nested Qt splitters and containers with draggable dividers. The tree supports up to 8 leaf panes.
- Each pane's internal stack: `[tab strip] [path bar] [file list] [status strip]`.

### 5.2 Tabs (per pane)

Each pane holds independent tabs. Each tab remembers directory, sort, filter, scroll.

- `Ctrl+T` new tab  
- `Ctrl+W` close tab (closing the last tab closes the pane)  
- `Ctrl+Tab` / `Ctrl+Shift+Tab` cycle tabs within the active pane  
- `Ctrl+Shift+T` reopen last closed tab  
- Drag tabs between panes  
- Middle-click or context menu to **lock** a tab (navigating away opens a new tab instead)

### 5.3 Opening Additional Panes

The 2-pane case is the contract; extra panes are opt-in.

- `Ctrl+\` split active pane vertically  
- `Ctrl+-` split active pane horizontally  
- `Ctrl+Shift+W` close active pane (minimum 1 remains)  
- `Tab` / `Shift+Tab` cycle active pane  
- `Alt+Arrow` move focus between panes  
- `Alt+1`…`Alt+8` snap to a preset layout (single, 2-side, 3-pane-L, 2×2, 3-col+strip, 2×3, two custom slots)
- Splitters are mouse-draggable; double-click resets to an even split

When only two panes are open, the UI behaves exactly like classic TC. Multi-pane-only features (destination picker, fan-out) appear only when ≥3 panes are live.

### 5.4 Window Chrome

```
┌──────────────────────────────────────────────────────────────────┐
│  Menu bar        [File] [Mark] [Commands] [Show] [Config]        │
├──────────────────────────────────────────────────────────────────┤
│  Button bar    ▣ ▣ ▣ ▣ ▣ ▣ ▣       (user-configurable, §10)      │
├──────────────────────────────────────────────────────────────────┤
│  Drive buttons [C:] [D:] [E:] [\\server]   (per pane)            │
├──────────────────────────────────────────────────────────────────┤
│  Tabs  [home] [downloads] [+]    │  [docs] [work] [+]            │
├──────────────────────────────────┼───────────────────────────────┤
│  Pane 1 — file list              │  Pane 2 — file list           │
│                                  │                               │
├──────────────────────────────────┴───────────────────────────────┤
│  Embedded terminal (toggleable, §8)                              │
├──────────────────────────────────────────────────────────────────┤
│  F1 Help  F3 View  F4 Edit  F5 Copy  F6 Move  F7 MkDir  F8 Del   │
└──────────────────────────────────────────────────────────────────┘
```

Everything except the panes is toggleable via `View` menu.

---

## 6. Pane Contents

### 6.1 File List

Virtualized list built on Qt's model/view stack. Must scroll smoothly at 100k rows — this is a v1 acceptance criterion and a subject of the UI spike (§16).

Columns (user-configurable, per-pane): icon, name, extension, size, modified, created, attributes. Widths and order persist per-pane.

Thumbnails for JPG/PNG/WebP/GIF generated on a background worker, cached to `%APPDATA%\MultiCommander\thumbs\`.

### 6.2 Sort Modes

Name, extension, size, mtime, ctime, unsorted. Toggle via column header click or `Ctrl+F3`…`Ctrl+F7`.

### 6.3 View Modes

- **Full** — detailed multi-column list (default)
- **Brief** — icon + name grid
- **Thumbnails** — image thumbnail grid
- **Tree** — collapsible directory tree
- **Quick View** — rich preview of the peer pane's cursor item: text with syntax highlight, image, PDF first-page, hex for binaries

### 6.4 Quick Search

Type any character while a pane is focused to jump to the first matching filename. `Ctrl+S` opens a filter box that narrows the list in place. `Esc` clears.

### 6.5 Refresh & File Watching

- Use filesystem watching where practical so visible directories refresh automatically when contents change.
- Watcher updates are debounced and coalesced to avoid repaint storms during large copy/move/delete jobs.
- If watching is unavailable or unreliable for a given path/provider, the pane falls back to manual refresh (`F2`) plus opportunistic refresh after local operations.
- v1 scope is local filesystem watching only; archive and future plugin-backed filesystems may expose refresh as a capability later.

---

## 7. Selection Model

- **Cursor** — highlighted row.
- **Selection** — set of marked items, rendered with a distinct background.
- Keyboard: `Insert` toggle, `Space` toggle + size, `Num +` / `Num -` glob-based add/remove, `Ctrl+A` all.
- Mouse: click to focus, `Ctrl+click` toggle one, `Shift+click` range. Right-drag range-select is enabled by default (TC's signature gesture).
- Per-pane selections are independent.

---

## 8. Embedded Terminal — first-class feature

The author uses the terminal constantly, so this cannot be a neutered command line. It is a real terminal, docked at the bottom of the window.

### 8.1 Implementation

- **Backend:** `pywinpty` spawns a ConPTY-backed shell (default: `pwsh.exe`, falling back to `cmd.exe`).
- **Frontend:** `xterm.js` inside a Qt web view. `xterm.js` is the battle-tested terminal front-end used by VS Code, Hyper, and others.
- **Bridge:** a local-only WebSocket server (bound to `127.0.0.1`, ephemeral port, token-auth) shuttles bytes between the xterm instance and the ConPTY. Python asyncio handles both ends.
- **CWD sync:** default is **Follow active pane = on**. In this mode, pane changes issue a shell-specific `cd` so the terminal follows the active pane. The user can toggle Follow active pane off at any time, after which the terminal and panes diverge intentionally. v1 is one-way sync only (pane → terminal); terminal-driven cwd changes do not retarget panes.
- **Pane-to-terminal integration:** `Ctrl+Enter` pastes the cursor item's name; `Alt+Enter` pastes the full path. `Ctrl+\`` toggles terminal visibility. `F9` focuses the terminal from anywhere.

### 8.2 What this replaces

The "command line + output drawer" described in earlier drafts is **dropped**. Interactive programs (`vim`, `htop`, ssh password prompts) just work, because it's a real PTY.

### 8.3 Spike requirement

This is the highest-risk subsystem. See §16 — prove it before the rest of the UI work starts.

---

## 9. Multi-Pane Operations

Activated only when ≥3 panes are open. With 2 panes, behavior is identical to classic TC.

### 9.1 Destination Resolution (for copy/move)

- **Source** = active pane's selection (or cursor item).
- **Destination** in order:
  1. Targeted shortcut: e.g. `F5 2` copies to pane 2.
  2. Exactly one other pane open → that pane (classic TC).
  3. Otherwise → a destination picker modal (pane thumbnails + paths; Enter or number key confirms).
- Drag-and-drop is always unambiguous: the drop target pane is the destination. `Ctrl+drop` = copy, `Shift+drop` = move, `Alt+drop` = symlink.

### 9.2 Fan-out Operations (≥3 panes only)

- `Shift+F5` — copy selection to **every** other pane
- `Shift+F6` — broadcast-move (copy to all, delete source after all verify)
- `Ctrl+F5` — symlink into every other pane

A preview dialog lists every destination before executing.

### 9.3 Compare & Sync

- `Ctrl+F12` — **compare panes**: diff active pane's directory against all others; differences highlighted in every pane (missing / newer / older / size-mismatch).
- `Ctrl+Shift+F12` — **sync planner**: per-file arrows showing proposed direction; user can flip any; Enter executes.

### 9.4 Conflicts

Every destructive op shows a preview and a conflict policy: `Overwrite` / `Skip` / `Rename` / `Ask` / `Newer wins`. Per-operation, not global.

---

## 10. Classic TC Power Features

First-class, not punted to plugins.

### 10.1 Multi-Rename (`Ctrl+M`)

A dialog for batch-renaming the selection:
- Filename / extension template strings with placeholders: `[N]` name, `[E]` ext, `[C]` counter, `[YMD]` date, `[N2-5]` substring, etc.
- Regex find/replace on top of the template.
- Live preview table (original → new); problematic rows highlighted (collisions, invalid chars).
- Commit, cancel, or "Undo rename" (see §12).

### 10.2 Find Files (`Alt+F7`)

Modal dialog with tabs:
- **Name & location:** glob patterns, recursive, exclude patterns.
- **Content:** text or regex search inside files, with encoding hint.
- **Attributes:** size range, date range, attributes.
- Results list → `Feed to listbox` (loads into a new virtual tab in the active pane) or `Go to file`.

### 10.3 Byte-by-byte Compare (`Commands → Compare by content`)

- Select exactly 2 files (one per pane, or two in one pane) → opens a side-by-side hex/text diff window.
- Jump-to-next-difference shortcut.

### 10.4 Directory Size (`Space` on a directory)

Computes size in a background worker; result shown in the pane's Size column.

### 10.5 Archive Operations

- Archives are first-class containers, not extract-only curiosities.
- Supported user actions in v1: browse, quick-view, compare, extract selected items, create new archive from selection, add files/folders, delete entries, rename entries, and test archive integrity.
- If an archive format requires a full rewrite for mutation, that rewrite runs as a normal background job with preview/progress/cancel semantics.
- Password-protected and unsupported-compression cases fail explicitly with a clear message; they are not silently skipped.

---

## 11. Selection & File Operations — Concurrency Model

- Each file operation (copy, move, delete, archive extract) runs as an **independent background job** with its own modal **progress window** containing:
  - files-processed / bytes-processed / throughput / ETA
  - current source → destination line
  - **Pause**, **Cancel**, and **Move to background** buttons
- Pressing "Move to background" closes the modal but the job keeps running. Backgrounded jobs are listed in the **`F12` jobs view** (a flyout panel) with progress bars, pause/cancel controls, and a "bring back to front" button.
- Multiple jobs run concurrently. Per-physical-disk, jobs that touch the same disk are **serialized** by a per-disk async semaphore to avoid head thrash; cross-disk jobs run in parallel.
- On quit, running/backgrounded jobs prompt: *"3 file operations are still running. Wait / Cancel all / Force quit?"*

This matches classic TC's "send to background" UX the author specifically asked for.

### 11.1 Failure Behavior

- Every mutating operation produces a preview before execution and a summary after completion: succeeded / skipped / failed counts, with per-item reasons.
- Failures are isolated per item where possible: one locked file or permission error should not invalidate unrelated items in the same job unless the user chooses "stop on first error".
- Partial success is normal and visible. The UI must never imply "done" when the result is mixed.
- Checksum verification is optional for v1 and may be offered as a slower validation mode later; v1 relies on size/write/read errors unless the backend exposes stronger verification cheaply.

### 11.2 Elevation & Permissions

- When an operation needs administrator rights, the app asks permission to continue with elevation before mutating anything.
- If the user declines elevation, the operation fails cleanly with a clear explanation and leaves completed work untouched.
- Elevation is per operation, not a global "run the whole app as admin" requirement.

### 11.3 Reparse Points, Symlinks, and Junctions

- The file list shows symlinks/junctions distinctly.
- Entering a directory symlink/junction navigates into it, but destructive operations target the link itself unless the user explicitly chooses otherwise.
- Copying a symlink/junction preserves the link by default rather than recursively copying the target contents.
- Find/search does **not** follow directory reparse points by default, to avoid loops and surprising traversal explosions. A follow-links option can be added later.

---

## 12. Undo

A deliberate upgrade over TC, which has none.

- Move / rename / delete / multi-rename push an **undo record** onto a bounded in-memory stack (last 50).
- Delete-to-trash is trivially reversible via `send2trash` → Shell restore.
- Move/rename is reversible by inverse operation.
- `Ctrl+Z` pops the top record and executes the inverse, within a 5-minute window. After 5 minutes, entries dim and require confirmation ("Undo this move from 47 minutes ago?").
- Copy is **not** undoable (it doesn't remove the source; the user can just delete the copy).

---

## 13. Button Bar — User Commands

A row of clickable buttons above the panes. Each button is defined in config:

```toml
[[button]]
icon = "archive"
tooltip = "Zip selected"
command = "7z.exe a %T\\%N.zip %S"
```

Placeholder grammar (applied before spawning the subprocess; shell-unsafe chars are quoted):

| Token | Meaning                                                   |
|-------|-----------------------------------------------------------|
| `%N`  | Current item name (no path)                               |
| `%P`  | Active pane's current directory (trailing `\`)            |
| `%F`  | Full path of current item                                 |
| `%S`  | Space-separated full paths of all selected items          |
| `%T`  | Target (peer) pane's directory                            |
| `%Q`  | Prompt the user for a string, inserted here               |
| `%%`  | Literal `%`                                               |

Buttons are reorderable by drag. User-commands can also be bound to F-keys via config overrides.

---

## 14. Function Key Bar

| Key   | Action                            |
|-------|-----------------------------------|
| F1    | Help                              |
| F2    | Refresh active pane               |
| F3    | View file                         |
| F4    | Edit file                         |
| F5    | Copy (to resolved destination)    |
| F6    | Move/Rename                       |
| F7    | Make directory                    |
| F8    | Delete (to Recycle Bin by default)|
| F9    | Focus terminal                    |
| F10   | Menu                              |
| F11   | Layout presets                    |
| F12   | Jobs view                         |

F-keys fire globally regardless of focus; printable keys respect focus (so typing into the terminal doesn't also scroll a pane).

---

## 15. File System Abstraction & Plugin-Ready Design

Even though plugins ship post-v1, the v1 architecture assumes them, to avoid rewriting later.

```python
class VFS(Protocol):
    name: str
    async def list_dir(self, path: str) -> list[Entry]: ...
    async def stat(self, path: str) -> Stat: ...
    async def open_read(self, path: str) -> AsyncBinaryIO: ...
    async def open_write(self, path: str) -> AsyncBinaryIO: ...
    async def delete(self, path: str, *, to_trash: bool) -> None: ...
    async def mkdir(self, path: str) -> None: ...
    async def rename(self, src: str, dst: str) -> None: ...
    async def copy(self, src: str, dst: str, *, progress: ProgressCB) -> None: ...
    async def test(self, path: str) -> ValidationResult: ...
```

Bundled VFS implementations in v1: `LocalFS`, `ZipFS`, `SevenZipFS`, `TarFS`.

### 15.1 Windows Semantics Are Part of the Product

- Use long-path-safe APIs and normalized internal path handling.
- UNC paths are supported anywhere local paths are supported, subject to permission/elevation differences.
- Locked files, readonly attributes, sharing violations, and destination-disappeared races are expected states with explicit user-facing error messages.
- Alternate data streams are out of scope for v1 UI, but normal file operations should avoid corrupting them when Windows APIs preserve them by default.

### 15.2 Archive Semantics

- Archives participate in the same pane/tab/navigation model as normal directories.
- Mutating archive operations use the same job system as filesystem operations.
- Archive support is format-capability-driven: some formats may support full mutation, some may require rewrite-on-save, and some may be browse/extract-only if the underlying library cannot safely do more. The UI must surface those capability differences honestly.

`UserCommand` (button-bar / F-key action) is a second extension point — v1 ships the built-ins as registered `UserCommand` objects so plugins can add peers on equal footing later.

Plugins load from `%APPDATA%\MultiCommander\plugins\*.py` at startup (post-v1; stubbed but not enabled in v1).

---

## 16. UI Spike — Gate for v1 Commitment

Before committing to the full build, a short prototype must prove:

1. **Virtualized file list** renders 100k rows with smooth scroll (60 fps target, 30 fps floor).
2. **Global keyboard capture** — F-keys fire while a path field or the terminal has focus.
3. **Drag-and-drop** works between nested splitters and pane/tab containers (tab-to-pane and file-to-pane).
4. **Embedded terminal** — `pywinpty` + `xterm.js` in a Qt web view renders at interactive latency, handles resize, and supports `vim`/`ssh`.

If any of these fails badly enough, the spec is revised before deep feature work continues.

---

## 17. Configuration & Persistence

- Config: `%APPDATA%\MultiCommander\config.toml` (keybindings, theme, columns, presets, button-bar entries, file associations). Hot-reloaded on save.
- State: `%APPDATA%\MultiCommander\state.json` (window geometry, layout tree, per-pane tabs & dirs, terminal cwd, jobs pending on quit). Restored on launch unless `--fresh`.

Themes ship: `tc-classic`, `tc-dark`, `nc-nostalgia` (blue/cyan/yellow tribute), `system` (follow Windows light/dark).

---

## 18. Out of Scope for v1

- Non-Windows platforms
- Network filesystems (SFTP, FTP, S3, SMB)
- Plugin loading (architecture is plugin-ready; loader is stubbed)
- Mobile / web
- i18n, a11y, telemetry, crash reporting
- Crash-safe undo persistence and job resumption after app/process failure

---

## 19. Resolved Product Decisions

1. **Terminal cwd sync default:** on. The user can toggle Follow active pane off at any time; v1 sync is pane → terminal only.
2. **Fan-out serialization across disks:** serialize per physical disk, parallel across disks. SSD vs HDD detection: use `GetDriveType` + `DeviceIoControl(StorageDeviceSeekPenaltyProperty)`; treat ambiguous as HDD (pessimistic).
3. **Multi-pane selection (`Ctrl+Shift+A` across panes):** skip in v1. Adds UX complexity for a case the author has not justified.
4. **Archive editing:** included in v1 where the format/library supports it safely; capability limits must be visible in the UI.
5. **Editor for `F4`:** default to `$env:EDITOR` or VS Code if present, else Notepad. Configurable.
6. **Viewer for `F3`:** built-in (text with syntax highlight via Pygments, hex for binary, image for images). No external viewer in v1.
