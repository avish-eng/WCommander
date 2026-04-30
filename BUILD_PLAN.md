# Multi-Pane Commander - Build Plan

This plan turns `SPEC.md` into an executable sequence. Do not start broad feature work until Phase 0 is complete.

## Phase 0 - Technical Spike Gate

Goal: prove the stack is viable before investing in architecture.

### Deliverables

1. `spikes/qt_list_spike.py`
   - Render a virtualized file list with 100k synthetic rows.
   - Measure scroll smoothness manually on the target machine.
   - Verify row selection, cursor movement, and column resizing assumptions.

2. `spikes/qt_keys_spike.py`
   - Verify global F-key handling while:
     - a Qt path input has focus
     - the terminal web view has focus
   - Confirm printable keys still respect focused controls.

3. `spikes/qt_layout_dnd_spike.py`
   - Prototype nested splitter-based pane layout.
   - Verify drag/drop between tabs and panes.

4. `spikes/qt_terminal_spike/`
   - `pywinpty` backend
   - `xterm.js` frontend in Qt web view
   - local WebSocket bridge
   - verify resize, interactive latency, and `vim` / `ssh`

### Exit Criteria

- 100k-row list is usable on the target machine.
- F-keys are reliable even when input controls or terminal are focused.
- Drag/drop is workable in nested layouts.
- Terminal is stable enough to treat as a first-class feature.

### Fail-Fast Rule

If any spike result is flaky rather than clearly viable, pause and re-evaluate the GUI stack before Phase 1.

## Phase 1 - Skeleton App

Goal: create the app shell and state model without deep features.

### Deliverables

- Python package layout
- app bootstrap
- config/state loading
- command registry
- empty two-pane window
- function-key bar
- placeholder terminal dock

### Initial package layout

```text
src/multipane_commander/
  app.py
  bootstrap.py
  config/
    model.py
    load.py
  state/
    model.py
    store.py
  ui/
    main_window.py
    layout_tree.py
    pane_view.py
    tab_strip.py
    file_list.py
    status_bar.py
    function_key_bar.py
    terminal_dock.py
  commands/
    registry.py
    file_ops.py
    navigation.py
    terminal.py
    layout.py
  domain/
    entries.py
    selection.py
    history.py
  services/
    fs/
      protocol.py
      local_fs.py
    jobs/
      manager.py
      model.py
    thumbs/
      cache.py
    watch/
      manager.py
  terminal/
    session.py
    bridge.py
  archive/
    capabilities.py
  tests/
```

### Acceptance Criteria

- App launches into a two-pane layout.
- Active pane is visually distinct.
- Basic keyboard focus moves between panes.
- State and config files can be read/written.

## Phase 2 - Core Local Filesystem Workflow

Goal: ship the smallest useful commander.

### Scope

- local directory listing
- cursor movement
- selection model
- sort modes
- path navigation
- drive buttons
- refresh
- copy / move / delete / mkdir
- progress dialog plus background jobs view

### Acceptance Criteria

- The user can navigate both panes entirely by keyboard.
- `F5`, `F6`, `F7`, `F8`, `Tab`, `Shift+Tab`, and `F2` work.
- Backgrounding a job works and progress remains visible.
- Errors and partial success are reported clearly.

## Phase 3 - Real Terminal Integration

Goal: make the terminal a normal part of daily use.

### Scope

- full ConPTY-backed terminal dock
- focus toggle
- pane-to-terminal paste shortcuts
- follow-active-pane toggle
- basic session persistence rules

### Acceptance Criteria

- `Ctrl+\`` toggles terminal visibility.
- `F9` focuses terminal reliably.
- `Ctrl+Enter` and `Alt+Enter` paste correctly.
- Pane-to-terminal cwd sync works when enabled.

## Phase 4 - Tabs and Multi-Pane Layout

Goal: restore the classic workflow and optional extra panes.

### Scope

- per-pane tabs
- reopen closed tab
- pane split / close
- layout presets
- drag/drop tabs between panes

### Acceptance Criteria

- Two-pane mode remains the default and feels simple.
- Extra panes are optional and do not complicate the 2-pane path.
- Pane and tab state restore correctly on relaunch.

## Phase 5 - Archive VFS

Goal: make archives behave like first-class containers.

### Scope

- capability matrix by format
- browse archives like directories
- extract selected items
- create archives from selection
- add / delete / rename entries where supported
- integrity test

### Acceptance Criteria

- Archive capabilities are surfaced honestly in the UI.
- Long-running archive rewrites use the normal job system.
- Unsupported mutations fail clearly, not silently.

## Phase 6 - Power Features

Goal: add the TC-specific tools that justify the project.

### Scope

- multi-rename
- find files / feed to listbox
- compare by content
- quick view
- thumbnails
- directory size
- compare/sync across panes

### Rule

Build these one at a time after the core workflow is stable. Do not open multiple major feature branches inside the codebase at once.

## Cross-Cutting Decisions

### 1. Command-first architecture

All user actions should route through command objects or command handlers rather than directly mutating UI widgets. This keeps keyboard shortcuts, menus, button bar, and future scripting aligned.

### 2. UI state vs domain state

- Domain state: panes, tabs, entries, selection, jobs, config, command context
- UI state: focused widget refs, splitter drag state, dialog visibility, temporary hover/preview state

Keep domain state serializable where practical.

### 3. Jobs as a real subsystem

Do not bury copy/move/delete progress logic inside widgets. Jobs need their own models, lifecycle, and event stream early.

### 4. Capabilities over special cases

Treat local FS and archives through capability checks rather than scattered `if zip` branches in the UI.

## Recommended First Vertical Slice

Implement this exact slice first after Phase 0 passes:

1. App shell
2. Two panes
3. Local directory listing
4. Cursor + selection
5. Copy / move / delete / mkdir
6. Job progress + backgrounding
7. Terminal toggle and focus

If this slice feels good, the rest of the product has a solid backbone.

## Immediate Next Tasks

1. Create Python project skeleton with `pyproject.toml`.
2. Add a `spikes/` directory and implement the 4 spike programs.
3. Record spike findings in `SPIKE_NOTES.md`.
4. Framework chosen: PySide6. Continue if the core shell remains comfortable to build in.
