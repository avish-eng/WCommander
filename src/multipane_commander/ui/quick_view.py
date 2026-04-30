from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QFont, QKeyEvent, QPixmap
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

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self.title_label)
        header_row.addWidget(self.title_meta_label)
        header_row.addStretch(1)
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
        self._apply_size_preset(self.size_picker.currentText())

    def current_size_preset(self) -> str:
        return self.size_picker.currentText()

    def set_size_preset(self, preset_name: str) -> None:
        if preset_name not in self._size_presets:
            preset_name = "Comfortable"
        self.size_picker.setCurrentText(preset_name)

    def show_path(self, path: Path | None) -> None:
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
