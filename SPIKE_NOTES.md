# Spike Notes

Record results here before continuing past Phase 0.

## Flet List Spike

Historical note: this was the pre-pivot experiment. The project has now switched to PySide6.

- Script: `spikes/flet_list_spike.py`
- Goal: judge whether a 100k-row file list is viable enough to keep Flet.

### Run

```powershell
python spikes/flet_list_spike.py
```

### Record

- Initial render/build time: window opened quickly; small dataset rendered correctly.
- Scroll smoothness: acceptable at low counts; felt heavy from roughly 1,000 rows upward.
- Cursor movement responsiveness: usable at low counts; likely tied to full-list rebuild cost in this spike.
- Memory/CPU observations: not formally measured yet.
- Verdict: uncertain
- Notes: This spike used a naive "create controls for every row" approach, so the result does not reject Flet outright. It does show that the final file list cannot brute-force thousands of controls and will need genuine virtualization or a different rendering strategy.

## Remaining Phase 0 Spikes

- Replace these with Qt equivalents if Phase 0 resumes:
- `spikes/qt_keys_spike.py`
- `spikes/qt_layout_dnd_spike.py`
- `spikes/qt_terminal_spike/`
