from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
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

        self.archive_view = QPlainTextEdit()
        self.archive_view.setObjectName("quickViewArchive")
        self.archive_view.setReadOnly(True)
        archive_font = QFont("Menlo")
        archive_font.setStyleHint(QFont.StyleHint.Monospace)
        archive_font.setPointSize(10)
        self.archive_view.setFont(archive_font)

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

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self.title_label)
        header_row.addWidget(self.title_meta_label)
        header_row.addStretch(1)
        header_row.addWidget(self.size_picker)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(header_row)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.stack, 1)

        self._current_pixmap: QPixmap | None = None
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
            self.meta_label.setText("Markdown")
            self.markdown_view.setMarkdown(raw.decode("utf-8", errors="replace"))
            self.stack.setCurrentWidget(self.markdown_view)
            return

        if suffix in _HTML_SUFFIXES and b"\x00" not in raw:
            self.meta_label.setText("HTML")
            self.html_view.setHtml(raw.decode("utf-8", errors="replace"))
            self.stack.setCurrentWidget(self.html_view)
            return

        if b"\x00" not in raw:
            text = raw[:80_000].decode("utf-8", errors="replace")
            lexer = _resolve_code_lexer(path.name)
            if lexer is not None:
                formatter = HtmlFormatter(noclasses=True, nobackground=True)
                rendered = highlight(text, lexer, formatter)
                self.meta_label.setText(f"{lexer.name} source")
                self.code_view.setHtml(rendered)
                self.stack.setCurrentWidget(self.code_view)
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
