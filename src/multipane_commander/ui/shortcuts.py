"""Window shortcut registration kept separate from command implementation."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut


def bind_window_shortcuts(window):
    window._next_pane_shortcut = QShortcut(
        QKeySequence(Qt.Key.Key_Tab), window, activated=window._focus_next_pane
    )
    window._previous_pane_shortcut = QShortcut(
        QKeySequence(Qt.Key.Key_Backtab), window, activated=window._focus_previous_pane
    )
    QShortcut(QKeySequence(Qt.Key.Key_F1), window, activated=window._show_help)
    QShortcut(QKeySequence(Qt.Key.Key_F2), window, activated=window._rename_in_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_F3), window, activated=window._toggle_passive_quick_view)
    QShortcut(QKeySequence(Qt.Key.Key_F4), window, activated=window._edit_in_active_pane)
    QShortcut(QKeySequence("Shift+F3"), window, activated=window._open_external_viewer)
    QShortcut(QKeySequence("Shift+F4"), window, activated=window._open_with_default_app)
    QShortcut(QKeySequence("Ctrl+Shift+R"), window, activated=window._toggle_quick_view_raw_mode)
    QShortcut(QKeySequence("Ctrl+R"), window, activated=window._refresh_active_pane)
    QShortcut(QKeySequence("Ctrl+I"), window, activated=window._toggle_quick_view_ai_mode)
    QShortcut(QKeySequence("Ctrl+T"), window, activated=window._new_tab_in_active_pane)
    QShortcut(QKeySequence("Ctrl+W"), window, activated=window._close_tab_in_active_pane)
    QShortcut(QKeySequence("Ctrl+Tab"), window, activated=window._next_tab_in_active_pane)
    QShortcut(QKeySequence("Ctrl+Shift+Tab"), window, activated=window._previous_tab_in_active_pane)
    QShortcut(
        QKeySequence("Ctrl+Shift+V"), window, activated=window._toggle_thumbnail_mode_in_active_pane
    )
    QShortcut(QKeySequence.StandardKey.Copy, window, activated=window._copy_selection_to_clipboard)
    QShortcut(QKeySequence.StandardKey.Cut, window, activated=window._cut_selection_to_clipboard)
    QShortcut(
        QKeySequence.StandardKey.Paste, window, activated=window._paste_clipboard_into_active_pane
    )
    QShortcut(QKeySequence(Qt.Key.Key_F5), window, activated=window._copy_from_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_F6), window, activated=window._move_from_active_pane)
    QShortcut(QKeySequence("Shift+F6"), window, activated=window._rename_in_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_F7), window, activated=window._mkdir_in_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_F8), window, activated=window._delete_from_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_Delete), window, activated=window._delete_from_active_pane)
    QShortcut(QKeySequence("Shift+F8"), window, activated=window._delete_from_active_pane_permanent)
    QShortcut(
        QKeySequence("Shift+Del"), window, activated=window._delete_from_active_pane_permanent
    )
    QShortcut(QKeySequence("Alt+1"), window, activated=window._apply_default_workspace_layout)
    QShortcut(QKeySequence("Alt+2"), window, activated=window._apply_focus_files_layout)
    QShortcut(QKeySequence("Alt+3"), window, activated=window._apply_focus_terminal_layout)
    QShortcut(QKeySequence("Alt+4"), window, activated=window._apply_terminal_right_layout)
    QShortcut(QKeySequence("Alt+5"), window, activated=window._apply_terminal_left_layout)
    QShortcut(QKeySequence("Alt+6"), window, activated=window._apply_balanced_layout)
    QShortcut(QKeySequence("Alt+7"), window, activated=window._apply_single_left_layout)
    QShortcut(
        QKeySequence("Ctrl+Return"), window, activated=window._paste_active_filename_to_terminal
    )
    QShortcut(
        QKeySequence("Ctrl+Enter"), window, activated=window._paste_active_filename_to_terminal
    )
    QShortcut(
        QKeySequence("Alt+Return"), window, activated=window._paste_active_full_path_to_terminal
    )
    QShortcut(
        QKeySequence("Alt+Enter"), window, activated=window._paste_active_full_path_to_terminal
    )
    QShortcut(QKeySequence("Alt+F1"), window, activated=window._show_drive_menu_for_active_pane)
    QShortcut(QKeySequence("Alt+F2"), window, activated=window._show_drive_menu_for_passive_pane)
    QShortcut(QKeySequence("Ctrl+S"), window, activated=window._show_quick_filter_in_active_pane)
    QShortcut(QKeySequence("Alt+Left"), window, activated=window._focus_pane_left)
    QShortcut(QKeySequence("Alt+Right"), window, activated=window._focus_pane_right)
    QShortcut(QKeySequence("Alt+Up"), window, activated=window._focus_pane_up)
    QShortcut(QKeySequence("Alt+Down"), window, activated=window._focus_pane_down)
    QShortcut(QKeySequence("Ctrl+Z"), window, activated=window._undo_last_operation)
    QShortcut(QKeySequence("Ctrl+M"), window, activated=window._multi_rename_in_active_pane)
    QShortcut(QKeySequence("Alt+F7"), window, activated=window._find_files_in_active_pane)
    QShortcut(QKeySequence(Qt.Key.Key_F9), window, activated=window._toggle_terminal)
    QShortcut(QKeySequence(Qt.Key.Key_F10), window, activated=window._show_main_menu)
    QShortcut(QKeySequence(Qt.Key.Key_F11), window, activated=window._show_layout_menu)
    QShortcut(QKeySequence(Qt.Key.Key_F12), window, activated=window._toggle_jobs_view)
    QShortcut(QKeySequence("Ctrl+`"), window, activated=window._toggle_terminal)
    QShortcut(QKeySequence("Ctrl+Shift+`"), window, activated=window._toggle_terminal_maximized)
    QShortcut(QKeySequence("Ctrl+Shift+K"), window, activated=window._force_kill_terminal_program)
    QShortcut(QKeySequence("Ctrl+K"), window, activated=window._open_ai_palette)
    QShortcut(QKeySequence("Ctrl+Shift+I"), window, activated=window._toggle_ai_pane)
    QShortcut(QKeySequence("Ctrl+Shift+C"), window, activated=window._toggle_ai_chat)
    QShortcut(QKeySequence("Ctrl+P"), window, activated=window._open_path_editor)
