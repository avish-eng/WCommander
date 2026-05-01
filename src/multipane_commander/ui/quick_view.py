from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import QFont, QKeyEvent, QPixmap, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound

from multipane_commander.services.ai import (
    AgentRunner,
    AiError,
    AiResult,
    AiUnavailable,
    PaneRoots,
    TextChunk,
    ToolCallStart,
)
from multipane_commander.services.ai.cache import load_summary, save_summary

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _WEB_ENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    QWebEngineView = None  # type: ignore[assignment, misc]
    _WEB_ENGINE_AVAILABLE = False


_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".heic",
}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_HTML_SUFFIXES = {".html", ".htm"}
_PDF_SUFFIXES = {".pdf"}
_SVG_SUFFIXES = {".svg"}
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".7z", ".rar", ".jar"}
_ARCHIVE_COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")
_ARCHIVE_ENTRY_CAP = 1000

_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".aiff"}

_CSV_SUFFIXES = {".csv", ".tsv"}
_CSV_ROW_CAP = 1000
_CSV_COL_CAP = 100


def _is_archive_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in _ARCHIVE_SUFFIXES:
        return True
    name = path.name.lower()
    return any(name.endswith(compound) for compound in _ARCHIVE_COMPOUND_SUFFIXES)


_AI_SUMMARIZE_SYSTEM_PROMPT = (
    "You are inspecting a file in a file manager's quick-view pane. "
    "Use the Read tool to view the file at the path the user gives you, "
    "then write a concise summary of what it is and what it contains using Markdown. "
    "Use headers, bullet points, and inline code where they help readability. "
    "For code: say what the module/script does and list key functions/classes. "
    "For data files: describe the shape and notable columns. "
    "For documents: give the gist with key points as bullets. "
    "Don't quote the file verbatim. Don't apologize. "
    "If the file is empty, unreadable, or denied by the sandbox, say so plainly."
)

_MAX_BACKGROUND_AI_SESSIONS = 3

_AI_HTML_TEMPLATE = """\
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{background:#1e1e1e;color:#d4d4d4;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:13px;line-height:1.65;padding:14px 18px;margin:0}}
h1,h2,h3{{color:#c8d0e0;margin-top:1.1em;margin-bottom:.3em}}
h1{{font-size:1.2em}}h2{{font-size:1.1em}}h3{{font-size:1em}}
code{{background:#2a2d2e;padding:.1em .35em;border-radius:3px;
  font-family:"SF Mono",Menlo,monospace;font-size:.9em}}
pre{{background:#2a2d2e;padding:10px 12px;border-radius:4px;overflow-x:auto}}
pre code{{background:none;padding:0}}
ul,ol{{padding-left:1.4em;margin:.4em 0}}
li{{margin:.2em 0}}
a{{color:#4ec9b0}}
blockquote{{border-left:3px solid #4ec9b0;margin:0;padding-left:12px;color:#9da5b4}}
hr{{border:none;border-top:1px solid #3a3a3a;margin:.8em 0}}
p{{margin:.5em 0}}
</style></head><body>{body}</body></html>"""


def _markdown_to_html(text: str) -> str:
    import mistune  # local import keeps startup fast
    return _AI_HTML_TEMPLATE.format(body=mistune.html(text))


def _is_ai_summarizable(path: Path) -> bool:
    """Whether this file type makes sense to summarize with the AI tab.

    True for text-shaped files (text, code, markdown, html, csv, plain).
    False for images, video, audio, PDFs, SVGs, archives, and anything
    with a null byte in the first 4 KB (binary).
    """
    suffix = path.suffix.lower()
    if (
        suffix in _IMAGE_SUFFIXES
        or suffix in _PDF_SUFFIXES
        or suffix in _SVG_SUFFIXES
        or suffix in _VIDEO_SUFFIXES
        or suffix in _AUDIO_SUFFIXES
    ):
        return False
    if _is_archive_path(path):
        return False
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError:
        return False
    return b"\x00" not in sample


def _list_archive_entries(path: Path, cap: int) -> tuple[list[str], int]:
    """Return up to ``cap`` entry names from ``path`` and the total count.

    Uses libarchive-c, which understands zip / tar / tar.gz / 7z / rar /
    jar / jar transparently.
    """
    import libarchive  # local import — keeps test startup snappy

    entries: list[str] = []
    total = 0
    with libarchive.file_reader(str(path)) as reader:
        for entry in reader:
            total += 1
            if len(entries) < cap:
                size = getattr(entry, "size", None)
                pathname = entry.pathname
                if size is not None:
                    entries.append(f"{pathname:<60s}  {size:>12,d} bytes")
                else:
                    entries.append(pathname)
    return entries, total


def _resolve_code_lexer(filename: str) -> Lexer | None:
    """Return a pygments lexer for ``filename`` or None for plain/unknown text."""
    try:
        lexer = get_lexer_for_filename(filename)
    except ClassNotFound:
        return None
    if isinstance(lexer, TextLexer):
        return None
    return lexer


def _format_hex_dump(data: bytes, bytes_per_row: int = 16) -> str:
    """Return a classic offset/hex/ascii dump of ``data``."""
    lines: list[str] = []
    for offset in range(0, len(data), bytes_per_row):
        chunk = data[offset : offset + bytes_per_row]
        hex_part = " ".join(f"{b:02x}" for b in chunk).ljust(bytes_per_row * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part}  {ascii_part}")
    return "\n".join(lines)


class QuickViewWidget(QFrame):
    ai_badges_changed = Signal(object)  # frozenset[Path] of currently-processing paths

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("quickView")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._size_presets = {
            "Compact": {"image_scale": 0.72, "text_points": 9},
            "Comfortable": {"image_scale": 1.0, "text_points": 10},
            "Large": {"image_scale": 1.28, "text_points": 12},
        }

        self.title_label = QLabel("Quick View")
        self.title_label.setObjectName("quickViewTitle")
        self.title_meta_label = QLabel("")
        self.title_meta_label.setObjectName("quickViewMeta")
        self.meta_label = QLabel("Select a file to preview.")
        self.meta_label.setObjectName("quickViewMeta")
        self.meta_label.setWordWrap(True)
        self.size_picker = QComboBox()
        self.size_picker.setObjectName("quickViewSizePicker")
        self.size_picker.addItems(list(self._size_presets))
        self.size_picker.setCurrentText("Comfortable")
        self.size_picker.currentTextChanged.connect(self._apply_size_preset)

        self.stack = QStackedWidget()

        self.empty_label = QLabel("No preview available.")
        self.empty_label.setObjectName("quickViewEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_preview = QPlainTextEdit()
        self.text_preview.setObjectName("quickViewText")
        self.text_preview.setReadOnly(True)

        self.image_label = QLabel()
        self.image_label.setObjectName("quickViewImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setWidget(self.image_label)

        self.markdown_view = QTextBrowser()
        self.markdown_view.setObjectName("quickViewMarkdown")
        self.markdown_view.setOpenExternalLinks(True)

        self.html_view = QTextBrowser()
        self.html_view.setObjectName("quickViewHtml")
        self.html_view.setOpenExternalLinks(True)

        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setObjectName("quickViewPdf")
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)

        self.svg_view = QSvgWidget()
        self.svg_view.setObjectName("quickViewSvg")

        self.code_view = QTextBrowser()
        self.code_view.setObjectName("quickViewCode")

        self.hex_view = QPlainTextEdit()
        self.hex_view.setObjectName("quickViewHex")
        self.hex_view.setReadOnly(True)
        hex_font = QFont("Menlo")
        hex_font.setStyleHint(QFont.StyleHint.Monospace)
        hex_font.setPointSize(10)
        self.hex_view.setFont(hex_font)

        self.csv_view = QTableWidget()
        self.csv_view.setObjectName("quickViewCsv")
        self.csv_view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.csv_view.horizontalHeader().setStretchLastSection(False)
        self.csv_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.csv_view.verticalHeader().setVisible(True)

        self.archive_view = QPlainTextEdit()
        self.archive_view.setObjectName("quickViewArchive")
        self.archive_view.setReadOnly(True)
        archive_font = QFont("Menlo")
        archive_font.setStyleHint(QFont.StyleHint.Monospace)
        archive_font.setPointSize(10)
        self.archive_view.setFont(archive_font)

        self.raw_text_view = QPlainTextEdit()
        self.raw_text_view.setObjectName("quickViewRawText")
        self.raw_text_view.setReadOnly(True)
        raw_font = QFont("Menlo")
        raw_font.setStyleHint(QFont.StyleHint.Monospace)
        raw_font.setPointSize(10)
        self.raw_text_view.setFont(raw_font)

        self.media_view = QWidget()
        self.media_view.setObjectName("quickViewMedia")
        self.media_player = QMediaPlayer(self)
        self.media_audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.media_audio_output)
        self.media_video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.media_video_widget)
        self.media_play_button = QPushButton("Play")
        self.media_play_button.setObjectName("quickViewMediaPlay")
        self.media_play_button.clicked.connect(self._toggle_media_playback)
        self.media_seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.media_seek_slider.setObjectName("quickViewMediaSeek")
        self.media_seek_slider.setRange(0, 0)
        self.media_seek_slider.sliderMoved.connect(self.media_player.setPosition)
        self.media_player.positionChanged.connect(self._on_media_position_changed)
        self.media_player.durationChanged.connect(self._on_media_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_media_state_changed)
        media_layout = QVBoxLayout(self.media_view)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(6)
        media_layout.addWidget(self.media_video_widget, 1)
        media_controls = QHBoxLayout()
        media_controls.setContentsMargins(0, 0, 0, 0)
        media_controls.addWidget(self.media_play_button)
        media_controls.addWidget(self.media_seek_slider, 1)
        media_layout.addLayout(media_controls)

        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.text_preview)
        self.stack.addWidget(self.image_scroll)
        self.stack.addWidget(self.markdown_view)
        self.stack.addWidget(self.html_view)
        self.stack.addWidget(self.pdf_view)
        self.stack.addWidget(self.svg_view)
        self.stack.addWidget(self.code_view)
        self.stack.addWidget(self.hex_view)
        self.stack.addWidget(self.archive_view)
        self.stack.addWidget(self.media_view)
        self.stack.addWidget(self.csv_view)
        self.stack.addWidget(self.raw_text_view)

        self.raw_button = QPushButton("Raw")
        self.raw_button.setObjectName("quickViewRawToggle")
        self.raw_button.setCheckable(True)
        self.raw_button.setVisible(False)
        self.raw_button.setToolTip("Toggle rendered ↔ raw source (Tab)")
        self.raw_button.toggled.connect(self._on_raw_toggled)

        self.web_button = QPushButton("Web")
        self.web_button.setObjectName("quickViewWebToggle")
        self.web_button.setCheckable(True)
        self.web_button.setVisible(False)
        self.web_button.setEnabled(_WEB_ENGINE_AVAILABLE)
        self.web_button.setToolTip("Render HTML with full Chromium engine")
        self.web_button.toggled.connect(self._on_web_toggled)

        self.ai_button = QPushButton("AI")
        self.ai_button.setObjectName("quickViewAiToggle")
        self.ai_button.setCheckable(True)
        self.ai_button.setEnabled(False)
        self.ai_button.setToolTip("Summarize this file with Claude (Ctrl+I)")
        self.ai_button.toggled.connect(self._on_ai_toggled)

        self.ai_view = QWidget()
        self.ai_view.setObjectName("quickViewAi")
        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("quickViewAiStatus")
        # Inner stack: index 0 = plain-text streaming view, index 1 = rendered HTML
        self.ai_inner_stack = QStackedWidget()
        self.ai_text_view = QPlainTextEdit()
        self.ai_text_view.setObjectName("quickViewAiText")
        self.ai_text_view.setReadOnly(True)
        self.ai_inner_stack.addWidget(self.ai_text_view)   # index 0
        self.ai_spinner = QProgressBar()
        self.ai_spinner.setObjectName("quickViewAiSpinner")
        self.ai_spinner.setRange(0, 0)
        self.ai_spinner.setTextVisible(False)
        self.ai_spinner.setMaximumHeight(5)
        self.ai_spinner.setVisible(False)
        self.ai_cancel_button = QPushButton("Cancel")
        self.ai_cancel_button.setObjectName("quickViewAiCancel")
        self.ai_cancel_button.setVisible(False)
        self.ai_cancel_button.clicked.connect(self._cancel_ai_summary)
        self.ai_retry_button = QPushButton("Retry")
        self.ai_retry_button.setObjectName("quickViewAiRetry")
        self.ai_retry_button.setVisible(False)
        self.ai_retry_button.clicked.connect(self._on_ai_retry_clicked)
        ai_layout = QVBoxLayout(self.ai_view)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(6)
        ai_layout.addWidget(self.ai_status_label)
        ai_layout.addWidget(self.ai_spinner)
        ai_layout.addWidget(self.ai_inner_stack, 1)
        ai_buttons_row = QHBoxLayout()
        ai_buttons_row.addStretch(1)
        ai_buttons_row.addWidget(self.ai_cancel_button)
        ai_buttons_row.addWidget(self.ai_retry_button)
        ai_layout.addLayout(ai_buttons_row)
        self.stack.addWidget(self.ai_view)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self.title_label)
        header_row.addWidget(self.title_meta_label)
        header_row.addStretch(1)
        header_row.addWidget(self.ai_button)
        header_row.addWidget(self.web_button)
        header_row.addWidget(self.raw_button)
        header_row.addWidget(self.size_picker)

        for view in (
            self.markdown_view,
            self.html_view,
            self.code_view,
            self.csv_view,
            self.raw_text_view,
        ):
            view.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(header_row)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.stack, 1)

        self._current_pixmap: QPixmap | None = None
        self._raw_source: str | None = None
        self._rich_widget: QWidget | None = None
        self._web_view: "QWebEngineView | None" = None
        self._current_html_path: Path | None = None
        self._ai_runner: AgentRunner | None = None
        self._ai_pane_roots: PaneRoots | None = None
        self._ai_current_path: Path | None = None
        # session_id → file path for every in-flight session (background + active)
        self._ai_sessions: dict[str, Path] = {}
        # session whose streaming output is shown in the UI right now
        self._ai_active_session_id: str | None = None
        self._ai_pre_widget: QWidget | None = None
        self._ai_text_buffer: list[str] = []
        # session_id → accumulated text chunks (kept for background sessions too)
        self._ai_session_buffers: dict[str, list[str]] = {}
        self._ai_rendered_view: "QWebEngineView | None" = None
        self._apply_size_preset(self.size_picker.currentText())

    def is_raw_toggle_available(self) -> bool:
        return not self.raw_button.isHidden()

    def is_web_toggle_available(self) -> bool:
        return not self.web_button.isHidden()

    def is_raw_mode(self) -> bool:
        return self.raw_button.isChecked()

    def is_web_mode(self) -> bool:
        return self.web_button.isChecked()

    def toggle_raw_mode(self) -> None:
        if self.is_raw_toggle_available():
            self.raw_button.toggle()

    def toggle_web_mode(self) -> None:
        if self.is_web_toggle_available():
            self.web_button.toggle()

    def current_size_preset(self) -> str:
        return self.size_picker.currentText()

    def set_size_preset(self, preset_name: str) -> None:
        if preset_name not in self._size_presets:
            preset_name = "Comfortable"
        self.size_picker.setCurrentText(preset_name)

    def show_path(self, path: Path | None) -> None:
        self._ai_current_path = path
        try:
            self._show_path_inner(path)
        finally:
            self._refresh_ai_state()

    def _show_path_inner(self, path: Path | None) -> None:
        # Stop any currently-playing media before switching pages so audio
        # doesn't keep playing when the user navigates to a different file.
        if self.stack.currentWidget() is self.media_view:
            self.media_player.stop()

        # Clear raw-toggle state by default; rich-renderer branches re-arm it.
        self._clear_raw_state()

        if path is None:
            self.title_label.setText("Quick View")
            self.title_meta_label.clear()
            self.meta_label.setText("Select a file to preview.")
            self.meta_label.setVisible(True)
            self.stack.setCurrentWidget(self.empty_label)
            self.text_preview.clear()
            self.image_label.clear()
            self._current_pixmap = None
            return

        self.title_label.setText(path.name or str(path))
        self.title_meta_label.clear()
        self.meta_label.setVisible(True)
        if path.is_dir():
            self.meta_label.setText("Folder selected")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Folder selected.\nOpen it to browse its contents.")
            return

        suffix = path.suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._current_pixmap = pixmap
                self.title_meta_label.setText(f"{pixmap.width()} x {pixmap.height()} px")
                self.meta_label.clear()
                self.meta_label.setVisible(False)
                self._update_scaled_pixmap()
                self.stack.setCurrentWidget(self.image_scroll)
                return

        if suffix in _PDF_SUFFIXES:
            self.pdf_document.load(str(path))
            if self.pdf_document.status() == QPdfDocument.Status.Ready:
                self.meta_label.setText(f"PDF • {self.pdf_document.pageCount()} page(s)")
                self.stack.setCurrentWidget(self.pdf_view)
                return
            self.meta_label.setText("PDF • failed to load")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Unable to preview this PDF.")
            return

        if suffix in _SVG_SUFFIXES:
            self.svg_view.load(str(path))
            if self.svg_view.renderer().isValid():
                size = self.svg_view.renderer().defaultSize()
                self.meta_label.setText(f"SVG • {size.width()} x {size.height()}")
                self.stack.setCurrentWidget(self.svg_view)
                return
            self.meta_label.setText("SVG • failed to parse")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Unable to preview this SVG.")
            return

        if suffix in _VIDEO_SUFFIXES or suffix in _AUDIO_SUFFIXES:
            kind = "Video" if suffix in _VIDEO_SUFFIXES else "Audio"
            self.media_player.setSource(QUrl.fromLocalFile(str(path)))
            self.media_video_widget.setVisible(suffix in _VIDEO_SUFFIXES)
            self.meta_label.setText(f"{kind} • press Play to start")
            self.media_play_button.setText("Play")
            self.media_play_button.setEnabled(True)
            self.stack.setCurrentWidget(self.media_view)
            return

        if _is_archive_path(path):
            try:
                entries, total = _list_archive_entries(path, _ARCHIVE_ENTRY_CAP)
            except Exception:  # libarchive raises ArchiveError, OSError, etc.
                entries, total = [], -1
            if total >= 0:
                shown = len(entries)
                if total > shown:
                    self.meta_label.setText(
                        f"Archive • {total:,} entries ({total - shown:,} more not shown)"
                    )
                else:
                    self.meta_label.setText(f"Archive • {total:,} entries")
                self.archive_view.setPlainText("\n".join(entries))
                self.stack.setCurrentWidget(self.archive_view)
                return
            # libarchive choked — fall through to the binary/hex view below.

        try:
            file_size = path.stat().st_size
            with path.open("rb") as handle:
                raw = handle.read(80_000)
        except OSError as exc:
            self.meta_label.setText(f"{path}\n{exc}")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Unable to preview this item.")
            return

        if suffix in _MARKDOWN_SUFFIXES and b"\x00" not in raw:
            text = raw.decode("utf-8", errors="replace")
            self.meta_label.setText("Markdown")
            self.markdown_view.setMarkdown(text)
            self._show_with_raw_toggle(self.markdown_view, text)
            return

        if suffix in _HTML_SUFFIXES and b"\x00" not in raw:
            text = raw.decode("utf-8", errors="replace")
            self.meta_label.setText("HTML")
            self.html_view.setHtml(text)
            self._current_html_path = path
            self.web_button.setVisible(_WEB_ENGINE_AVAILABLE)
            rich = self._resolve_html_rich_widget(text, path)
            self._show_with_raw_toggle(rich, text)
            return

        if suffix in _CSV_SUFFIXES and b"\x00" not in raw:
            text = raw[:80_000].decode("utf-8", errors="replace")
            if text.strip():
                self._populate_csv_view(text, suffix)
                self._show_with_raw_toggle(self.csv_view, text)
                return
            # Empty CSV — fall through to text view, which will render as blank.

        if b"\x00" not in raw:
            text = raw[:80_000].decode("utf-8", errors="replace")
            lexer = _resolve_code_lexer(path.name)
            if lexer is not None:
                formatter = HtmlFormatter(noclasses=True, nobackground=True)
                rendered = highlight(text, lexer, formatter)
                self.meta_label.setText(f"{lexer.name} source")
                self.code_view.setHtml(rendered)
                self._show_with_raw_toggle(self.code_view, text)
                return
            self.meta_label.setText("Text file")
            self.text_preview.setPlainText(text)
            self.stack.setCurrentWidget(self.text_preview)
            return

        self.meta_label.setText(f"Binary • {file_size:,} bytes")
        self.hex_view.setPlainText(_format_hex_dump(raw[:4096]))
        self.stack.setCurrentWidget(self.hex_view)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._update_scaled_pixmap()
        super().resizeEvent(event)

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return
        preset = self._size_presets[self.size_picker.currentText()]
        viewport_size = self.image_scroll.viewport().size()
        target_size = viewport_size.expandedTo(viewport_size)
        target_size.setWidth(max(1, int(viewport_size.width() * preset["image_scale"])))
        target_size.setHeight(max(1, int(viewport_size.height() * preset["image_scale"])))
        scaled = self._current_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _apply_size_preset(self, preset_name: str) -> None:
        preset = self._size_presets[preset_name]
        font = QFont(self.text_preview.font())
        font.setPointSize(preset["text_points"])
        self.text_preview.setFont(font)
        self._update_scaled_pixmap()

    def _populate_csv_view(self, text: str, suffix: str) -> None:
        import csv
        import io

        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows: list[list[str]] = []
        total_rows = 0
        header: list[str] = []
        for index, row in enumerate(reader):
            if index == 0:
                header = row[:_CSV_COL_CAP]
                continue
            total_rows += 1
            if len(rows) < _CSV_ROW_CAP:
                rows.append(row[:_CSV_COL_CAP])
        col_count = len(header) if header else (max((len(r) for r in rows), default=0))
        self.csv_view.clear()
        self.csv_view.setColumnCount(col_count)
        self.csv_view.setRowCount(len(rows))
        if header:
            self.csv_view.setHorizontalHeaderLabels(header[:col_count])
        for row_idx, row in enumerate(rows):
            for col_idx in range(col_count):
                cell = row[col_idx] if col_idx < len(row) else ""
                self.csv_view.setItem(row_idx, col_idx, QTableWidgetItem(cell))
        self.csv_view.resizeColumnsToContents()
        kind = "TSV" if suffix == ".tsv" else "CSV"
        if total_rows > len(rows):
            self.meta_label.setText(
                f"{kind} • {total_rows:,} rows ({total_rows - len(rows):,} more not shown)"
            )
        else:
            self.meta_label.setText(f"{kind} • {total_rows:,} rows")

    def _toggle_media_playback(self) -> None:
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _on_media_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.media_play_button.setText(
            "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
        )

    def _on_media_position_changed(self, position: int) -> None:
        if not self.media_seek_slider.isSliderDown():
            self.media_seek_slider.setValue(position)

    def _on_media_duration_changed(self, duration: int) -> None:
        self.media_seek_slider.setRange(0, max(0, duration))

    def _clear_raw_state(self) -> None:
        # Hide the toggle and forget the source/widget pair, but keep the
        # checked state so the user's preference persists across files.
        self._raw_source = None
        self._rich_widget = None
        self._current_html_path = None
        self.raw_button.setVisible(False)
        self.web_button.setVisible(False)

    def _ensure_web_view(self) -> "QWebEngineView | None":
        if not _WEB_ENGINE_AVAILABLE:
            return None
        if self._web_view is None:
            assert QWebEngineView is not None
            view = QWebEngineView()
            view.setObjectName("quickViewWebEngine")
            self.stack.addWidget(view)
            view.installEventFilter(self)
            self._web_view = view
        return self._web_view

    def _resolve_html_rich_widget(self, text: str, path: Path) -> QWidget:
        if self.web_button.isChecked():
            web = self._ensure_web_view()
            if web is not None:
                base_url = QUrl.fromLocalFile(str(path.parent) + "/")
                web.setHtml(text, base_url)
                return web
        return self.html_view

    def _on_web_toggled(self, checked: bool) -> None:
        # When the web toggle flips on an HTML file, swap the rich widget
        # between QTextBrowser and QWebEngineView (re-routing through the
        # raw toggle so user preference is preserved).
        if self._current_html_path is None or self._raw_source is None:
            return
        rich = self._resolve_html_rich_widget(self._raw_source, self._current_html_path)
        self._rich_widget = rich
        if not self.raw_button.isChecked():
            self.stack.setCurrentWidget(rich)

    def _show_with_raw_toggle(self, rich_widget: QWidget, raw_source: str) -> None:
        self._rich_widget = rich_widget
        self._raw_source = raw_source
        self.raw_button.setVisible(True)
        if self.raw_button.isChecked():
            self.raw_text_view.setPlainText(raw_source)
            self.stack.setCurrentWidget(self.raw_text_view)
        else:
            self.stack.setCurrentWidget(rich_widget)

    def _on_raw_toggled(self, checked: bool) -> None:
        if self._rich_widget is None or self._raw_source is None:
            return
        if checked:
            self.raw_text_view.setPlainText(self._raw_source)
            self.stack.setCurrentWidget(self.raw_text_view)
        else:
            self.stack.setCurrentWidget(self._rich_widget)

    # ----- AI summary tab -------------------------------------------------

    def set_ai_runtime(
        self,
        runner: AgentRunner | None,
        pane_roots: PaneRoots | None,
    ) -> None:
        """Wire (or unwire) the AI runner. Call from main_window when the
        active pane changes, or pass (None, None) to disable AI features."""
        if self._ai_runner is not None and self._ai_runner is not runner:
            try:
                self._ai_runner.event.disconnect(self._on_ai_event)
            except (TypeError, RuntimeError):
                pass
            try:
                self._ai_runner.session_done.disconnect(self._on_ai_session_done)
            except (TypeError, RuntimeError):
                pass
        if runner is not None and runner is not self._ai_runner:
            runner.event.connect(self._on_ai_event)
            runner.session_done.connect(self._on_ai_session_done)
        self._ai_runner = runner
        self._ai_pane_roots = pane_roots
        self._refresh_ai_state()

    def is_ai_toggle_available(self) -> bool:
        return self.ai_button.isEnabled()

    def is_ai_mode(self) -> bool:
        return self.ai_button.isChecked()

    def toggle_ai_mode(self) -> None:
        if self.ai_button.isEnabled():
            self.ai_button.toggle()

    def _can_summarize_now(self) -> bool:
        if self._ai_runner is None or self._ai_pane_roots is None:
            return False
        if self._ai_current_path is None or self._ai_current_path.is_dir():
            return False
        return _is_ai_summarizable(self._ai_current_path)

    def _refresh_ai_state(self) -> None:
        """Called after every show_path. Updates the AI button enabled state
        and, if AI mode is on, swaps the stack to ai_view and starts (or
        cache-hits) a summary for the current file."""
        runner_ok = self._ai_runner is not None and self._ai_pane_roots is not None
        can = self._can_summarize_now()
        self.ai_button.setEnabled(can)
        if not runner_ok:
            self.ai_button.setToolTip("Claude Code AI unavailable")
        elif not can:
            self.ai_button.setToolTip("AI summary not available for this file")
        else:
            self.ai_button.setToolTip("Summarize this file with Claude (Ctrl+I)")

        if self.ai_button.isChecked():
            if not can:
                # Auto-uncheck. The natural-view widget is already on the
                # stack from _show_path_inner; suppress the "restore" path.
                self._ai_pre_widget = None
                self.ai_button.setChecked(False)
                return
            # AI is on AND file is summarizable. Capture the just-rendered
            # natural view, then route the stack to ai_view.
            self._ai_pre_widget = self.stack.currentWidget()
            self.stack.setCurrentWidget(self.ai_view)
            self._start_ai_summary()

    def _on_ai_toggled(self, checked: bool) -> None:
        if checked:
            if not self._can_summarize_now():
                self.ai_button.setChecked(False)
                return
            self._ai_pre_widget = self.stack.currentWidget()
            self.stack.setCurrentWidget(self.ai_view)
            self._start_ai_summary()
        else:
            self._cancel_all_ai_sessions()
            self._ai_sessions.clear()
            self._ai_session_buffers.clear()
            self._ai_active_session_id = None
            self.ai_spinner.setVisible(False)
            self._emit_ai_badges_changed()
            if self._ai_pre_widget is not None:
                self.stack.setCurrentWidget(self._ai_pre_widget)
            self._ai_pre_widget = None

    def _start_ai_summary(self) -> None:
        if (
            self._ai_runner is None
            or self._ai_pane_roots is None
            or self._ai_current_path is None
        ):
            self._ai_show_error("AI runtime unavailable.")
            return

        # Already have an in-flight session for this file — reattach to it.
        # (_refresh_ai_state fires twice per navigation; this prevents duplicates.)
        for sid, path in self._ai_sessions.items():
            if path == self._ai_current_path:
                self._ai_active_session_id = sid
                # Restore whatever text has already streamed in for this session.
                buf = self._ai_session_buffers.setdefault(sid, [])
                self._ai_text_buffer = buf
                self.ai_text_view.setPlainText("".join(buf))
                self.ai_inner_stack.setCurrentIndex(0)
                self.ai_status_label.setText("Summarizing…")
                self.ai_spinner.setVisible(True)
                self.ai_cancel_button.setVisible(True)
                self.ai_retry_button.setVisible(False)
                return

        # Cache hit: render instantly, no new session needed.
        cached = load_summary(self._ai_current_path)
        if cached is not None:
            self._ai_render_markdown(cached)
            self.ai_status_label.setText("Cached summary (no token cost)")
            self.ai_spinner.setVisible(False)
            self.ai_cancel_button.setVisible(False)
            self.ai_retry_button.setVisible(True)
            return

        # Cap background sessions: cancel the oldest non-active one if full.
        if len(self._ai_sessions) >= _MAX_BACKGROUND_AI_SESSIONS:
            oldest = next(
                (s for s in self._ai_sessions if s != self._ai_active_session_id),
                None,
            )
            if oldest:
                self._ai_runner.cancel(oldest)
                self._ai_sessions.pop(oldest, None)

        # Start a fresh session. Previous session for a different file keeps running.
        new_buf: list[str] = []
        self._ai_text_buffer = new_buf
        self.ai_text_view.clear()
        self.ai_inner_stack.setCurrentIndex(0)  # show streaming text view
        self.ai_status_label.setText("Summarizing…")
        self.ai_spinner.setVisible(True)
        self.ai_cancel_button.setVisible(True)
        self.ai_retry_button.setVisible(False)

        try:
            sid = self._ai_runner.start_session(
                prompt=str(self._ai_current_path),
                system_prompt=_AI_SUMMARIZE_SYSTEM_PROMPT,
                allowed_tools=["Read"],
                pane_roots=self._ai_pane_roots,
            )
            self._ai_sessions[sid] = self._ai_current_path
            self._ai_session_buffers[sid] = new_buf
            self._ai_active_session_id = sid
            self._emit_ai_badges_changed()
        except AiUnavailable as exc:
            self._ai_show_error(str(exc))

    def _on_ai_retry_clicked(self) -> None:
        # Force a fresh session for the current file, discarding any in-flight one.
        if self._ai_current_path is not None and self._ai_runner is not None:
            stale = [s for s, p in self._ai_sessions.items() if p == self._ai_current_path]
            for sid in stale:
                self._ai_runner.cancel(sid)
                self._ai_sessions.pop(sid, None)
                self._ai_session_buffers.pop(sid, None)
            if self._ai_active_session_id in stale:
                self._ai_active_session_id = None
            if stale:
                self._emit_ai_badges_changed()
        self._start_ai_summary()

    def _on_ai_event(self, event: object) -> None:
        if not isinstance(event, (TextChunk, ToolCallStart, AiError)):
            return
        sid = getattr(event, "session_id", None)
        if sid is None or sid not in self._ai_sessions:
            return
        # Accumulate text for all sessions so reattach can restore it.
        if isinstance(event, TextChunk):
            self._ai_session_buffers.setdefault(sid, []).append(event.text)
        # Only update the visible UI for the session the user is watching.
        if sid != self._ai_active_session_id:
            return
        if isinstance(event, TextChunk):
            self.ai_text_view.setPlainText("".join(self._ai_session_buffers.get(sid, [])))
            cursor = self.ai_text_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.ai_text_view.setTextCursor(cursor)
        elif isinstance(event, ToolCallStart):
            self.ai_status_label.setText(f"{event.name}…")
        elif isinstance(event, AiError):
            self._ai_show_error(event.message)

    def _on_ai_session_done(self, result: object) -> None:
        if not isinstance(result, AiResult):
            return
        sid = result.session_id
        if sid not in self._ai_sessions:
            return

        file_path = self._ai_sessions.pop(sid)
        self._ai_session_buffers.pop(sid, None)
        self._emit_ai_badges_changed()

        # Always save completed summaries — even for files we've navigated away from.
        if result.status == "completed" and result.text:
            save_summary(file_path, result.text)

        # Only update the UI for the session the user is currently watching.
        if sid != self._ai_active_session_id:
            return

        self._ai_active_session_id = None
        self.ai_spinner.setVisible(False)
        self.ai_cancel_button.setVisible(False)
        if result.status == "completed":
            self._ai_render_markdown(result.text)
            self.ai_status_label.setText("Summary")
            self.ai_retry_button.setVisible(True)
        elif result.status == "cancelled":
            self.ai_status_label.setText("Cancelled.")
            self.ai_retry_button.setVisible(True)
        else:
            self._ai_show_error(result.error or "Summary failed.")

    def _cancel_ai_summary(self) -> None:
        if self._ai_active_session_id is not None and self._ai_runner is not None:
            self._ai_runner.cancel(self._ai_active_session_id)

    def _cancel_all_ai_sessions(self) -> None:
        if self._ai_runner is None:
            return
        for sid in list(self._ai_sessions):
            self._ai_runner.cancel(sid)

    def _ensure_ai_rendered_view(self) -> "QWebEngineView":
        if self._ai_rendered_view is None:
            assert QWebEngineView is not None
            view = QWebEngineView()
            view.setObjectName("quickViewAiRendered")
            self.ai_inner_stack.addWidget(view)  # index 1
            self._ai_rendered_view = view
        return self._ai_rendered_view

    def _ai_render_markdown(self, text: str) -> None:
        if _WEB_ENGINE_AVAILABLE:
            view = self._ensure_ai_rendered_view()
            view.setHtml(_markdown_to_html(text))
            self.ai_inner_stack.setCurrentWidget(view)
        else:
            self.ai_text_view.setPlainText(text)
            self.ai_inner_stack.setCurrentIndex(0)

    def _ai_show_error(self, message: str) -> None:
        self.ai_status_label.setText(f"Error: {message}")
        self.ai_spinner.setVisible(False)
        self.ai_inner_stack.setCurrentIndex(0)
        self.ai_cancel_button.setVisible(False)
        self.ai_retry_button.setVisible(True)

    def _emit_ai_badges_changed(self) -> None:
        self.ai_badges_changed.emit(frozenset(self._ai_sessions.values()))

    # ----- key handling ---------------------------------------------------

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            # `isHidden()` reflects the explicit setVisible(False) call,
            # independent of whether the parent widget chain is shown
            # (which matters for offscreen tests).
            if event.key() == Qt.Key.Key_Tab and not self.raw_button.isHidden():
                self.raw_button.toggle()
                return True
        return super().eventFilter(obj, event)
