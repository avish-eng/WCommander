# Command Bar — Design Spec
_2026-05-01_

## Context

WCommander already has a full ConPTY-backed terminal (F9 → TerminalDock), but no inline command bar — the kind Total Commander shows at the bottom of its pane area. Users who want to run a quick `git status` or `cd ..` currently have to open the full terminal dock and context-switch. The command bar closes that gap: a persistent single-line input that lets you fire commands without leaving the pane UI, while still being able to escalate to the real terminal when needed.

---

## Layout

A new `CommandBar` widget is inserted into `main_window.py`'s root `QVBoxLayout`, between the `content_splitter` (which holds the panes and terminal dock) and `JobsView`/`FunctionKeyBar`:

```
root_layout (QVBoxLayout)
├── content_splitter      ← panes + terminal dock (existing)
├── CommandBar            ← NEW
│   ├── OutputPanel       ← hidden by default, expands upward on output
│   └── InputRow          ← [path label]  [QLineEdit]
├── JobsView              ← existing
└── FunctionKeyBar        ← existing
```

`CommandBar` lives in a new file: `src/multipane_commander/ui/command_bar.py`.

---

## Activation

| Trigger | Behavior |
|---|---|
| Click the input field | Focuses it |
| Ctrl+G | Focuses the input from anywhere |
| Any printable keypress while a pane is focused | Main window forwards the key event to CommandBar and focuses it |

The "start typing" path requires `main_window` to intercept **unhandled** keypresses from the pane (i.e. those not consumed by an existing shortcut binding) and route them to the bar. Ctrl+S (quick-filter) and other existing bindings are unaffected.

---

## Behaviors

### Prompt label
Shows the active pane's current directory (e.g. `D:\Data\dev>`). Updates automatically whenever the active pane navigates to a new directory.

### Enter — inline execution
1. **`cd` interception**: if the command starts with `cd`, parse the target path (`cd ..`, `cd ~`, `cd /some/path`, bare `cd` → home dir), navigate the active pane to it, clear the input. No subprocess is spawned.
2. **All other commands**: spawn a subprocess in the active pane's cwd, stream stdout + stderr into `OutputPanel`, auto-refresh the active pane's file list when the process exits (exit code 0 or not).

### Shift+Enter — escalate to TerminalDock
1. Inject `cd {active_pane_cwd}` into the existing `TerminalDock` PTY session.
2. Inject the command.
3. Open/reveal the terminal dock.
4. Clear the command bar input.

### Up / Down arrows — command history
In-memory list (session only, no persistence in v1). Up cycles backward through history, Down cycles forward. History is appended on every Enter or Shift+Enter.

### Esc
- If `OutputPanel` is visible: dismiss it, return focus to command bar.
- If input is empty: return focus to active pane.
- Otherwise: clear input.

---

## OutputPanel

A collapsible `QFrame` stacked above the `InputRow` inside `CommandBar`. Hidden by default.

| Property | Detail |
|---|---|
| Max height | ~150px |
| Overflow | Vertical scroll |
| Header | Dimmed command label + ✕ button |
| Content | stdout/stderr, monospace font |
| Dismiss | Esc or ✕ click |
| Auto-refresh | Active pane's file list refreshed on process exit |

---

## Key Files

| File | Change |
|---|---|
| `src/multipane_commander/ui/command_bar.py` | New file — `CommandBar` widget |
| `src/multipane_commander/ui/main_window.py` | Add `CommandBar` to layout; wire active-pane signals; handle Ctrl+G; forward unhandled keypresses |
| `src/multipane_commander/ui/terminal_dock.py` | Expose a method to inject a command + cwd into the live PTY session |
| `src/multipane_commander/ui/pane_view.py` | Read-only — understand navigation API and directory-changed signals |
| `src/multipane_commander/ui/function_key_bar.py` | Read-only — style/layout reference |

---

## Error Handling

- Subprocess fails to start (command not found): show stderr in `OutputPanel`, no crash.
- `cd` target doesn't exist: show an inline error in `OutputPanel` (don't navigate the pane).
- TerminalDock PTY session not yet started when Shift+Enter is used: start the session, then inject.

---

## Verification

1. Launch the app — command bar appears between panes and F-key bar, showing active pane's path.
2. Click bar → type `echo hello` → Enter → OutputPanel shows `hello`, file list unchanged.
3. Type `mkdir test_dir` → Enter → OutputPanel shows output, file list refreshes and shows `test_dir`.
4. Type `cd test_dir` → Enter → active pane navigates into `test_dir`, no output panel, prompt updates.
5. Type `cd nonexistent` → Enter → error shown in OutputPanel, pane stays put.
6. Type `vim README.md` → Shift+Enter → TerminalDock opens with `vim` running.
7. Up/Down arrows in bar → history cycles correctly.
8. Ctrl+G from pane → bar is focused.
9. Start typing while pane is focused → keystrokes appear in bar.
10. Esc with OutputPanel open → dismisses panel.
11. Esc with empty input → focus returns to pane.
