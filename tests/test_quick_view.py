"""Tests for the F3 Quick View widget.

Two groups, mirroring tests/test_keyboard_shortcuts.py:

* ``R0_3_*`` — regression tests for the QuickView behaviour that exists
  today (image / plain text / folder placeholder / binary placeholder /
  None reset / size presets / 80 KB truncation cap / unreadable file).
  These lock the current contract in place so the format-specific
  renderers (markdown, html, pdf, svg, syntax highlight, hex) can be
  layered on without regressing the baseline.

* ``F0_3_*`` — feature tests for new renderer branches added in the same
  PR. Each new branch lands with at least one failing test first.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal as _Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea, QWidget as _QWidget

from multipane_commander.services.ai import PaneRoots as _PaneRoots
from multipane_commander.services.ai.events import (
    AiError as _AiError,
    AiResult as _AiResult,
    TextChunk as _TextChunk,
    ToolCallStart as _ToolCallStart,
)
from multipane_commander.ui.quick_view import QuickViewWidget


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _make_png(path: Path, width: int = 4, height: int = 3) -> None:
    """Write a deterministic in-memory PNG to ``path``."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF3366)
    assert image.save(str(path), "PNG"), f"failed to write fixture PNG to {path}"


def _make_minimal_pdf(path: Path) -> None:
    """Write the smallest valid 1-page PDF QPdfDocument will accept."""
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    )
    obj1 = body.find(b"1 0 obj")
    obj2 = body.find(b"2 0 obj")
    obj3 = body.find(b"3 0 obj")
    xref_start = len(body)
    xref = (
        b"xref\n0 4\n0000000000 65535 f \n"
        + f"{obj1:010d} 00000 n \n".encode()
        + f"{obj2:010d} 00000 n \n".encode()
        + f"{obj3:010d} 00000 n \n".encode()
    )
    trailer = (
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n"
        + str(xref_start).encode()
        + b"\n%%EOF\n"
    )
    path.write_bytes(body + xref + trailer)


def _make_widget() -> QuickViewWidget:
    _qapp()
    return QuickViewWidget()


# ---------------------------------------------------------------------------
# Regression tests — current behaviour, must keep passing.
# ---------------------------------------------------------------------------


def test_R0_3_quick_view_image_png(tmp_path: Path) -> None:
    """PNG fixture renders into the image scroll area with dimensions in title meta."""
    image_path = tmp_path / "logo.png"
    _make_png(image_path, width=4, height=3)

    view = _make_widget()
    view.show_path(image_path)

    assert view.stack.currentWidget() is view.image_scroll
    assert view.title_label.text() == "logo.png"
    assert view.title_meta_label.text() == "4 x 3 px"
    assert view.meta_label.isHidden() is True
    assert view.image_label.pixmap() is not None and not view.image_label.pixmap().isNull()


def test_R0_3_quick_view_plain_text(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello\nworld", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.text_preview
    assert view.text_preview.toPlainText() == "hello\nworld"
    assert view.meta_label.text() == "Text file"


def test_R0_3_quick_view_directory_placeholder(tmp_path: Path) -> None:
    view = _make_widget()
    view.show_path(tmp_path)

    assert view.stack.currentWidget() is view.empty_label
    assert "Folder selected" in view.empty_label.text()
    assert view.meta_label.text() == "Folder selected"


def test_R0_3_quick_view_none_resets_state(tmp_path: Path) -> None:
    """Passing None must clear the title, meta, image cache, and text body."""
    target = tmp_path / "notes.txt"
    target.write_text("primed", encoding="utf-8")
    view = _make_widget()
    view.show_path(target)
    assert view.text_preview.toPlainText() == "primed"

    view.show_path(None)

    assert view.stack.currentWidget() is view.empty_label
    assert view.title_label.text() == "Quick View"
    assert view.title_meta_label.text() == ""
    assert view.text_preview.toPlainText() == ""
    assert view._current_pixmap is None


def test_R0_3_quick_view_unreadable_file(tmp_path: Path) -> None:
    target = tmp_path / "no-perm.txt"
    target.write_text("hidden", encoding="utf-8")
    target.chmod(0o000)
    try:
        view = _make_widget()
        view.show_path(target)

        assert view.stack.currentWidget() is view.empty_label
        assert "Unable to preview" in view.empty_label.text()
        assert str(target) in view.meta_label.text()
    finally:
        target.chmod(0o600)


def test_R0_3_quick_view_truncates_text_at_80kb(tmp_path: Path) -> None:
    """The reader caps at 80,000 bytes — large text files must not blow up the preview."""
    target = tmp_path / "big.txt"
    target.write_text("a" * 200_000, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.text_preview
    assert len(view.text_preview.toPlainText()) <= 80_000


def test_R0_3_quick_view_size_preset_changes_text_font(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("preset", encoding="utf-8")
    view = _make_widget()
    view.show_path(target)

    view.set_size_preset("Compact")
    assert view.text_preview.font().pointSize() == 9

    view.set_size_preset("Comfortable")
    assert view.text_preview.font().pointSize() == 10

    view.set_size_preset("Large")
    assert view.text_preview.font().pointSize() == 12


def test_R0_3_quick_view_set_size_preset_unknown_falls_back_to_comfortable(tmp_path: Path) -> None:
    view = _make_widget()
    view.set_size_preset("Compact")
    assert view.current_size_preset() == "Compact"

    view.set_size_preset("does-not-exist")

    assert view.current_size_preset() == "Comfortable"


def test_R0_3_quick_view_image_then_text_clears_image_state(tmp_path: Path) -> None:
    """Switching from image to text mid-session must not leave stale image meta visible."""
    image_path = tmp_path / "logo.png"
    _make_png(image_path)
    text_path = tmp_path / "notes.txt"
    text_path.write_text("after", encoding="utf-8")

    view = _make_widget()
    view.show_path(image_path)
    assert view.title_meta_label.text() != ""
    assert view.meta_label.isHidden() is True

    view.show_path(text_path)

    assert view.stack.currentWidget() is view.text_preview
    assert view.title_meta_label.text() == ""
    assert view.meta_label.isHidden() is False
    assert view.meta_label.text() == "Text file"


def test_R0_3_quick_view_widget_basic_shape() -> None:
    """The QuickView always exposes the title, meta, picker and stack."""
    view = _make_widget()

    assert isinstance(view.title_label, QLabel)
    assert isinstance(view.meta_label, QLabel)
    assert isinstance(view.text_preview, QPlainTextEdit)
    assert isinstance(view.image_scroll, QScrollArea)
    presets = [view.size_picker.itemText(i) for i in range(view.size_picker.count())]
    assert presets == ["Compact", "Comfortable", "Large"]
    assert view.size_picker.currentText() == "Comfortable"


# ---------------------------------------------------------------------------
# Feature tests — new renderer branches.
# ---------------------------------------------------------------------------


def test_F0_3_quick_view_renders_markdown(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("# Heading\n\nBody text with **bold**.\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.markdown_view
    plain = view.markdown_view.toPlainText()
    assert "Heading" in plain
    assert "Body text" in plain
    # Markdown was parsed (heading hash dropped, formatting interpreted).
    assert "# Heading" not in plain
    assert "**bold**" not in plain


def test_F0_3_quick_view_renders_markdown_alternate_extension(tmp_path: Path) -> None:
    target = tmp_path / "notes.markdown"
    target.write_text("# Other ext\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.markdown_view
    assert "Other ext" in view.markdown_view.toPlainText()


def test_F0_3_quick_view_renders_html(tmp_path: Path) -> None:
    target = tmp_path / "page.html"
    target.write_text(
        "<html><body><h1>Hi there</h1><p>Body para</p></body></html>",
        encoding="utf-8",
    )

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.html_view
    plain = view.html_view.toPlainText()
    assert "Hi there" in plain
    assert "Body para" in plain
    # HTML was parsed (tags stripped from plain projection).
    assert "<h1>" not in plain
    assert "<body>" not in plain


def test_F0_3_quick_view_renders_html_htm_extension(tmp_path: Path) -> None:
    target = tmp_path / "doc.htm"
    target.write_text("<p>legacy ext</p>", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.html_view
    assert "legacy ext" in view.html_view.toPlainText()


def test_F0_3_quick_view_renders_pdf(tmp_path: Path) -> None:
    from PySide6.QtPdf import QPdfDocument

    target = tmp_path / "sample.pdf"
    _make_minimal_pdf(target)

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.pdf_view
    assert view.pdf_document.status() == QPdfDocument.Status.Ready
    assert view.pdf_document.pageCount() == 1
    assert "PDF" in view.meta_label.text()


def test_F0_3_quick_view_handles_corrupt_pdf(tmp_path: Path) -> None:
    """A .pdf that fails to load must not raise; show the error placeholder."""
    target = tmp_path / "broken.pdf"
    target.write_bytes(b"%PDF-1.4\nnot really a pdf\n%%EOF\n")

    view = _make_widget()
    view.show_path(target)

    # Either the pdf_view is selected with an error status, or we fall back
    # to the empty placeholder. Both are acceptable; what's not acceptable
    # is an exception. Verify state is consistent either way.
    assert view.stack.currentWidget() in (view.pdf_view, view.empty_label)


def test_F0_3_quick_view_renders_svg(tmp_path: Path) -> None:
    target = tmp_path / "logo.svg"
    target.write_text(
        '<?xml version="1.0"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
        '<rect x="0" y="0" width="32" height="32" fill="#ff3366"/>'
        "</svg>",
        encoding="utf-8",
    )

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.svg_view
    # The renderer parsed the SVG (default size is non-empty for valid SVG).
    assert view.svg_view.renderer().isValid()
    assert "SVG" in view.meta_label.text()


def test_F0_3_quick_view_handles_corrupt_svg(tmp_path: Path) -> None:
    target = tmp_path / "bad.svg"
    target.write_text("not really svg", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    # Invalid SVG must not raise; either svg widget shows nothing or fallback.
    assert view.stack.currentWidget() in (view.svg_view, view.empty_label, view.text_preview)


def test_F0_3_quick_view_highlights_python(tmp_path: Path) -> None:
    target = tmp_path / "script.py"
    target.write_text("def greet(name):\n    return f\"hi {name}\"\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    plain = view.code_view.toPlainText()
    assert "def" in plain
    assert "greet" in plain
    # Pygments was applied (HTML output contains a span/style for keywords).
    html = view.code_view.toHtml()
    assert "span" in html.lower()
    assert "Python" in view.meta_label.text()


def test_F0_3_quick_view_highlights_typescript(tmp_path: Path) -> None:
    target = tmp_path / "app.ts"
    target.write_text("const x: number = 1;\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "const" in view.code_view.toPlainText()
    assert "TypeScript" in view.meta_label.text() or "Typescript" in view.meta_label.text()


def test_F0_3_quick_view_highlights_json(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    target.write_text('{"key": "value"}\n', encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "value" in view.code_view.toPlainText()


def test_F0_3_quick_view_highlights_xml(tmp_path: Path) -> None:
    target = tmp_path / "config.xml"
    target.write_text("<?xml version='1.0'?>\n<root><item>hi</item></root>\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    plain = view.code_view.toPlainText()
    assert "<root>" in plain
    assert "XML" in view.meta_label.text()


def test_F0_3_quick_view_highlights_yaml(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("key: value\nlist:\n  - one\n  - two\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "key: value" in view.code_view.toPlainText()
    assert "YAML" in view.meta_label.text()


def test_F0_3_quick_view_highlights_yml_extension(tmp_path: Path) -> None:
    target = tmp_path / "ci.yml"
    target.write_text("name: ci\non: push\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view


def test_F0_3_quick_view_highlights_css(tmp_path: Path) -> None:
    target = tmp_path / "style.css"
    target.write_text(".header { color: red; }\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert ".header" in view.code_view.toPlainText()
    assert "CSS" in view.meta_label.text()


def test_F0_3_quick_view_highlights_rust(tmp_path: Path) -> None:
    target = tmp_path / "lib.rs"
    target.write_text("fn greet(name: &str) -> String {\n    format!(\"hi {}\", name)\n}\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "fn greet" in view.code_view.toPlainText()
    assert "Rust" in view.meta_label.text()


def test_F0_3_quick_view_highlights_go(tmp_path: Path) -> None:
    target = tmp_path / "main.go"
    target.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "package main" in view.code_view.toPlainText()


def test_F0_3_quick_view_highlights_sql(tmp_path: Path) -> None:
    target = tmp_path / "schema.sql"
    target.write_text("CREATE TABLE users (id INT PRIMARY KEY);\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "CREATE" in view.code_view.toPlainText()
    assert "SQL" in view.meta_label.text()


def test_F0_3_quick_view_highlights_shell(tmp_path: Path) -> None:
    target = tmp_path / "deploy.sh"
    target.write_text("#!/bin/bash\nset -euo pipefail\necho hi\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "#!/bin/bash" in view.code_view.toPlainText()


def test_F0_3_quick_view_highlights_dockerfile(tmp_path: Path) -> None:
    target = tmp_path / "Dockerfile"
    target.write_text("FROM python:3.12\nRUN pip install pytest\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "FROM python" in view.code_view.toPlainText()
    assert "Docker" in view.meta_label.text()


def test_F0_3_quick_view_highlights_toml(tmp_path: Path) -> None:
    target = tmp_path / "pyproject.toml"
    target.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.code_view
    assert "[tool.ruff]" in view.code_view.toPlainText()


def test_F0_3_quick_view_image_tiff(tmp_path: Path) -> None:
    target = tmp_path / "scan.tiff"
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x00AAFF)
    assert image.save(str(target), "TIFF"), "failed to write fixture TIFF"

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.image_scroll
    assert "4 x 3 px" in view.title_meta_label.text()


def test_F0_3_quick_view_image_ico(tmp_path: Path) -> None:
    target = tmp_path / "favicon.ico"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    assert image.save(str(target), "ICO"), "failed to write fixture ICO"

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.image_scroll
    assert "16 x 16 px" in view.title_meta_label.text()


def test_F0_3_quick_view_lists_zip_contents(tmp_path: Path) -> None:
    import zipfile

    target = tmp_path / "bundle.zip"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("README.txt", "hello")
        zf.writestr("src/main.py", "print('hi')\n")
        zf.writestr("src/utils.py", "def helper(): pass\n")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.archive_view
    body = view.archive_view.toPlainText()
    assert "README.txt" in body
    assert "src/main.py" in body
    assert "src/utils.py" in body
    assert "Archive" in view.meta_label.text()
    assert "3" in view.meta_label.text()  # 3 entries


def test_F0_3_quick_view_lists_tar_gz_contents(tmp_path: Path) -> None:
    import tarfile

    target = tmp_path / "release.tar.gz"
    payload = tmp_path / "_payload"
    payload.mkdir()
    (payload / "VERSION").write_text("1.2.3")
    (payload / "bin").mkdir()
    (payload / "bin" / "tool").write_text("#!/bin/sh\n")
    with tarfile.open(target, "w:gz") as tf:
        tf.add(payload / "VERSION", arcname="release/VERSION")
        tf.add(payload / "bin" / "tool", arcname="release/bin/tool")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.archive_view
    body = view.archive_view.toPlainText()
    assert "release/VERSION" in body
    assert "release/bin/tool" in body


def test_F0_3_quick_view_lists_7z_contents(tmp_path: Path) -> None:
    import py7zr

    target = tmp_path / "bundle.7z"
    payload = tmp_path / "_payload7"
    payload.mkdir()
    (payload / "doc.txt").write_text("seven zip")
    with py7zr.SevenZipFile(target, "w") as sz:
        sz.writeall(payload, "bundle")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.archive_view
    body = view.archive_view.toPlainText()
    assert "doc.txt" in body


def test_F0_3_quick_view_handles_corrupt_archive(tmp_path: Path) -> None:
    """A .zip that fails to read must not raise; fall through to text/hex/empty."""
    target = tmp_path / "broken.zip"
    target.write_bytes(b"PK\x03\x04not really a zip")

    view = _make_widget()
    view.show_path(target)

    # Any sane fallback target is OK — what matters is no exception. libarchive
    # may raise, in which case show_path falls through to text or hex depending
    # on whether the bytes contain a null byte.
    assert view.stack.currentWidget() in (
        view.archive_view,
        view.hex_view,
        view.text_preview,
        view.empty_label,
    )


def test_F0_3_quick_view_routes_video_to_media_player(tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.media_view
    assert "Video" in view.meta_label.text()
    assert Path(view.media_player.source().toLocalFile()) == target


def test_F0_3_quick_view_routes_audio_to_media_player(tmp_path: Path) -> None:
    target = tmp_path / "song.mp3"
    target.write_bytes(b"ID3\x03" + b"\x00" * 32)

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.media_view
    assert "Audio" in view.meta_label.text()
    assert Path(view.media_player.source().toLocalFile()) == target


def test_F0_3_quick_view_video_does_not_autoplay(tmp_path: Path) -> None:
    """Loading the preview must NOT start playback — user has to press Play."""
    from PySide6.QtMultimedia import QMediaPlayer

    target = tmp_path / "clip.mp4"
    target.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)

    view = _make_widget()
    view.show_path(target)

    assert view.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState


def test_F0_3_quick_view_media_view_exposes_play_button(tmp_path: Path) -> None:
    target = tmp_path / "song.wav"
    target.write_bytes(b"RIFF" + b"\x00" * 32)

    view = _make_widget()
    view.show_path(target)

    # The media view should have a play/pause control reachable for tests.
    assert hasattr(view, "media_play_button")
    assert view.media_play_button.isEnabled()


def test_F0_3_quick_view_media_switching_resets_player(tmp_path: Path) -> None:
    """Switching from one media file to another must update the player source."""
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    a.write_bytes(b"ID3" + b"\x00" * 32)
    b.write_bytes(b"ID3" + b"\x00" * 32)

    view = _make_widget()
    view.show_path(a)
    assert Path(view.media_player.source().toLocalFile()) == a

    view.show_path(b)
    assert Path(view.media_player.source().toLocalFile()) == b


def test_F0_3_quick_view_leaving_media_stops_playback(tmp_path: Path) -> None:
    """Switching away from media (to a text file) must stop the player so audio doesn't keep playing."""
    from PySide6.QtMultimedia import QMediaPlayer

    media = tmp_path / "song.mp3"
    media.write_bytes(b"ID3" + b"\x00" * 32)
    text = tmp_path / "notes.txt"
    text.write_text("after", encoding="utf-8")

    view = _make_widget()
    view.show_path(media)
    view.media_player.play()  # simulate user pressing play

    view.show_path(text)

    assert view.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState


def test_F0_3_quick_view_renders_csv_as_table(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.csv_view
    assert view.csv_view.columnCount() == 3
    assert view.csv_view.rowCount() == 2  # header excluded — it's in horizontalHeader
    assert view.csv_view.horizontalHeaderItem(0).text() == "name"
    assert view.csv_view.horizontalHeaderItem(2).text() == "city"
    assert view.csv_view.item(0, 0).text() == "Alice"
    assert view.csv_view.item(1, 2).text() == "LA"
    assert "CSV" in view.meta_label.text()


def test_F0_3_quick_view_csv_handles_quoted_commas(tmp_path: Path) -> None:
    target = tmp_path / "addresses.csv"
    target.write_text('name,address\n"Alice","123 Main St, Apt 4"\n', encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.csv_view
    assert view.csv_view.item(0, 0).text() == "Alice"
    assert view.csv_view.item(0, 1).text() == "123 Main St, Apt 4"


def test_F0_3_quick_view_csv_caps_rows(tmp_path: Path) -> None:
    target = tmp_path / "huge.csv"
    lines = ["id,value"] + [f"{i},val{i}" for i in range(2500)]
    target.write_text("\n".join(lines), encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.csv_view
    assert view.csv_view.rowCount() <= 1000  # cap
    assert "more" in view.meta_label.text().lower()


def test_F0_3_quick_view_handles_empty_csv(tmp_path: Path) -> None:
    target = tmp_path / "empty.csv"
    target.write_text("", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    # Empty CSV should not crash; fall through to text view or empty placeholder.
    assert view.stack.currentWidget() in (view.csv_view, view.text_preview, view.empty_label)


def test_F0_3_quick_view_caps_archive_entries(tmp_path: Path) -> None:
    """Archives with thousands of entries must render within the cap."""
    import zipfile

    target = tmp_path / "huge.zip"
    with zipfile.ZipFile(target, "w") as zf:
        for i in range(2500):
            zf.writestr(f"entry_{i:05d}.txt", "")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.archive_view
    # Cap is at 1000 entries — body should mention truncation when exceeded.
    body = view.archive_view.toPlainText()
    line_count = body.count("\n") + 1
    assert line_count <= 1100, f"expected entry list capped, got {line_count} lines"
    assert "more" in view.meta_label.text().lower() or "trunc" in body.lower()


def test_F0_3_quick_view_falls_back_to_text_for_unknown_extension(tmp_path: Path) -> None:
    """Files with no pygments lexer must still render as plain text, not crash."""
    target = tmp_path / "notes.weirdext"
    target.write_text("plain content", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.text_preview
    assert view.text_preview.toPlainText() == "plain content"


def test_F0_3_quick_view_hex_view_for_binary(tmp_path: Path) -> None:
    """Binary files now render as a hex dump, replacing the placeholder."""
    target = tmp_path / "blob.bin"
    target.write_bytes(bytes(range(64)) + b"\x00" * 32)

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.hex_view
    body = view.hex_view.toPlainText()
    # Offset column.
    assert "00000000" in body
    # Hex bytes column (the first byte is 0x00).
    assert "00 01 02 03" in body
    assert "Binary" in view.meta_label.text()


def test_F0_3_quick_view_hex_view_renders_printable_column(tmp_path: Path) -> None:
    target = tmp_path / "ascii.bin"
    # 16 bytes: "ABCDEFGHIJKLMNOP" + a null byte to mark binary.
    target.write_bytes(b"ABCDEFGHIJKLMNOP\x00")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.hex_view
    body = view.hex_view.toPlainText()
    # Printable ASCII column on the first row.
    assert "ABCDEFGHIJKLMNOP" in body


# --- Raw toggle (Tab / button) ------------------------------------------------


def test_F0_3_raw_toggle_visible_for_markdown(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("# Heading\n\nbody\n", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.raw_button.isHidden() is False
    assert view.raw_button.isChecked() is False
    assert view.stack.currentWidget() is view.markdown_view


def test_F0_3_raw_toggle_swaps_to_raw_text_for_markdown(tmp_path: Path) -> None:
    body = "# Title\n\nHello **world**.\n"
    target = tmp_path / "doc.md"
    target.write_text(body, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    view.raw_button.toggle()  # turn ON
    assert view.raw_button.isChecked()
    assert view.stack.currentWidget() is view.raw_text_view
    assert view.raw_text_view.toPlainText() == body

    view.raw_button.toggle()  # turn OFF
    assert view.raw_button.isChecked() is False
    assert view.stack.currentWidget() is view.markdown_view


def test_F0_3_raw_toggle_swaps_to_raw_text_for_html(tmp_path: Path) -> None:
    body = "<h1>Hi</h1>\n<p>body</p>\n"
    target = tmp_path / "page.html"
    target.write_text(body, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    view.raw_button.toggle()

    assert view.stack.currentWidget() is view.raw_text_view
    assert view.raw_text_view.toPlainText() == body


def test_F0_3_raw_toggle_swaps_to_raw_source_for_code(tmp_path: Path) -> None:
    body = "def foo():\n    return 42\n"
    target = tmp_path / "script.py"
    target.write_text(body, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    view.raw_button.toggle()

    assert view.stack.currentWidget() is view.raw_text_view
    # Raw view shows un-highlighted source — exact bytes, no <span> tags.
    assert view.raw_text_view.toPlainText() == body
    assert "<span" not in view.raw_text_view.toPlainText()


def test_F0_3_raw_toggle_swaps_to_raw_text_for_csv(tmp_path: Path) -> None:
    body = "name,age\nAlice,30\nBob,25\n"
    target = tmp_path / "data.csv"
    target.write_text(body, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    view.raw_button.toggle()

    assert view.stack.currentWidget() is view.raw_text_view
    assert view.raw_text_view.toPlainText() == body


def test_F0_3_raw_toggle_hidden_for_image(tmp_path: Path) -> None:
    target = tmp_path / "pic.png"
    _make_png(target)

    view = _make_widget()
    view.show_path(target)

    assert view.raw_button.isHidden() is True


def test_F0_3_raw_toggle_hidden_for_plain_text(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("plain text", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    assert view.raw_button.isHidden() is True


def test_F0_3_raw_toggle_hidden_for_hex(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"ABC\x00DEF")

    view = _make_widget()
    view.show_path(target)

    assert view.stack.currentWidget() is view.hex_view
    assert view.raw_button.isHidden() is True


def test_F0_3_raw_toggle_hidden_for_directory(tmp_path: Path) -> None:
    view = _make_widget()
    view.show_path(tmp_path)

    assert view.raw_button.isHidden() is True


def test_F0_3_raw_toggle_hides_button_when_switching_to_non_rich(tmp_path: Path) -> None:
    """When switching to a file the toggle doesn't apply to, the button hides.

    The toggle's checked state is intentionally preserved (user preference
    persists across files); only the button visibility tracks applicability.
    """
    md = tmp_path / "doc.md"
    md.write_text("# hi", encoding="utf-8")
    txt = tmp_path / "notes.txt"
    txt.write_text("plain", encoding="utf-8")

    view = _make_widget()
    view.show_path(md)
    view.raw_button.toggle()
    assert view.raw_button.isChecked()

    view.show_path(txt)
    assert view.raw_button.isHidden() is True
    # Plain-text view shown (not the raw view), since the toggle doesn't apply.
    assert view.stack.currentWidget() is view.text_preview


def test_F0_3_raw_toggle_persists_state_when_switching_between_rich_files(
    tmp_path: Path,
) -> None:
    """If the user toggled Raw on, switching to another rich file keeps it on."""
    md1 = tmp_path / "a.md"
    md1.write_text("# one", encoding="utf-8")
    md2 = tmp_path / "b.md"
    md2.write_text("# two", encoding="utf-8")

    view = _make_widget()
    view.show_path(md1)
    view.raw_button.toggle()
    assert view.stack.currentWidget() is view.raw_text_view

    view.show_path(md2)
    # Raw mode persists; new file shown raw.
    assert view.raw_button.isChecked()
    assert view.stack.currentWidget() is view.raw_text_view
    assert view.raw_text_view.toPlainText() == "# two"


def test_F0_3_raw_toggle_via_tab_key_on_markdown_view(tmp_path: Path) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    target = tmp_path / "doc.md"
    target.write_text("# Heading", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    assert view.stack.currentWidget() is view.markdown_view

    tab_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.markdown_view, tab_press)

    assert view.raw_button.isChecked()
    assert view.stack.currentWidget() is view.raw_text_view


def test_F0_3_raw_toggle_via_tab_key_on_raw_view_returns_to_rich(tmp_path: Path) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    target = tmp_path / "doc.md"
    target.write_text("# Heading", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    view.raw_button.toggle()
    assert view.stack.currentWidget() is view.raw_text_view

    tab_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.raw_text_view, tab_press)

    assert view.raw_button.isChecked() is False
    assert view.stack.currentWidget() is view.markdown_view


# --- WebEngine HTML rendering -------------------------------------------------


def test_F0_3_web_button_visible_only_for_html(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# md", encoding="utf-8")
    html = tmp_path / "page.html"
    html.write_text("<h1>html</h1>", encoding="utf-8")

    view = _make_widget()

    view.show_path(md)
    assert view.web_button.isHidden() is True

    view.show_path(html)
    assert view.web_button.isHidden() is False


def test_F0_3_web_toggle_routes_html_to_web_view(tmp_path: Path) -> None:
    target = tmp_path / "page.html"
    target.write_text("<h1>Hello</h1>", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    assert view.stack.currentWidget() is view.html_view

    view.web_button.toggle()
    web_view = view._web_view
    assert web_view is not None
    assert view.stack.currentWidget() is web_view


def test_F0_3_web_toggle_off_returns_to_text_browser(tmp_path: Path) -> None:
    target = tmp_path / "page.html"
    target.write_text("<h1>Hello</h1>", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)
    view.web_button.toggle()
    assert view.stack.currentWidget() is view._web_view

    view.web_button.toggle()
    assert view.stack.currentWidget() is view.html_view


def test_F0_3_web_and_raw_compose_raw_wins(tmp_path: Path) -> None:
    """When both Web and Raw are toggled on, Raw view takes precedence."""
    body = "<h1>Hello</h1>"
    target = tmp_path / "page.html"
    target.write_text(body, encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    view.web_button.toggle()  # rich = web
    view.raw_button.toggle()  # raw on top
    assert view.stack.currentWidget() is view.raw_text_view
    assert view.raw_text_view.toPlainText() == body

    # Untoggle raw → back to rich (which is web).
    view.raw_button.toggle()
    assert view.stack.currentWidget() is view._web_view


def test_F0_3_web_button_hides_when_switching_to_non_html(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text("<h1>html</h1>", encoding="utf-8")
    md = tmp_path / "doc.md"
    md.write_text("# md", encoding="utf-8")

    view = _make_widget()
    view.show_path(html)
    view.web_button.toggle()
    assert view.web_button.isChecked()

    view.show_path(md)
    assert view.web_button.isHidden() is True
    # Markdown stays on its own rich widget; web preference is irrelevant.
    assert view.stack.currentWidget() is view.markdown_view


def test_F0_3_web_view_lazy_creation(tmp_path: Path) -> None:
    """The QWebEngineView is only created when the user toggles Web on."""
    target = tmp_path / "page.html"
    target.write_text("<h1>Hello</h1>", encoding="utf-8")

    view = _make_widget()
    view.show_path(target)

    # Showing an HTML file should NOT spin up Chromium.
    assert view._web_view is None

    view.web_button.toggle()
    assert view._web_view is not None


# ---------------------------------------------------------------------------
# AI tab (F3 AI mode) tests.
# ---------------------------------------------------------------------------


class _FakeRunner(_QWidget):
    """Minimal AgentRunner substitute that records calls and exposes signals."""

    event = _Signal(object)
    session_done = _Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[dict] = []
        self._cancelled: list[str] = []
        self._next_id = "fake-session-1"

    def start_session(self, *, prompt, system_prompt, allowed_tools, pane_roots):
        sid = self._next_id
        self._sessions.append({"id": sid, "prompt": prompt, "tools": allowed_tools})
        return sid

    def cancel(self, session_id: str) -> None:
        self._cancelled.append(session_id)


def _make_pane_roots(tmp_path: Path) -> _PaneRoots:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir(exist_ok=True)
    right.mkdir(exist_ok=True)
    return _PaneRoots(left=left, right=right)


def test_F3_ai_button_disabled_without_runner() -> None:
    """ai_button starts disabled when no AI runner is wired up."""
    view = _make_widget()
    assert view.ai_button.isEnabled() is False


def test_F3_ai_button_disabled_for_image(tmp_path: Path) -> None:
    """Images are not summarizable: ai_button must stay disabled."""
    image_path = tmp_path / "photo.png"
    _make_png(image_path)

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(image_path)

    assert view.ai_button.isEnabled() is False


def test_F3_ai_button_enabled_for_text_file(tmp_path: Path) -> None:
    """A plain text file makes the ai_button available."""
    target = tmp_path / "notes.txt"
    target.write_text("hello world", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)

    assert view.ai_button.isEnabled() is True


def test_F3_ai_button_enabled_for_python_source(tmp_path: Path) -> None:
    target = tmp_path / "script.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)

    assert view.ai_button.isEnabled() is True


def test_F3_ai_toggle_switches_stack_to_ai_view(tmp_path: Path) -> None:
    """Checking the AI toggle must show the ai_view page."""
    target = tmp_path / "notes.txt"
    target.write_text("content", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)

    view.ai_button.setChecked(True)

    assert view.stack.currentWidget() is view.ai_view
    assert len(runner._sessions) == 1
    assert runner._sessions[0]["tools"] == ["Read"]


def test_F3_ai_toggle_off_restores_prior_widget(tmp_path: Path) -> None:
    """Unchecking AI must bring back the widget that was showing before."""
    target = tmp_path / "notes.txt"
    target.write_text("content", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    prior = view.stack.currentWidget()

    view.ai_button.setChecked(True)
    assert view.stack.currentWidget() is view.ai_view

    view.ai_button.setChecked(False)
    assert view.stack.currentWidget() is prior


def test_F3_ai_text_chunk_streams_into_view(tmp_path: Path) -> None:
    """TextChunk events with the active session_id must appear in ai_text_view."""
    target = tmp_path / "readme.md"
    target.write_text("# readme", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    runner.event.emit(_TextChunk(session_id=sid, text="Hello "))
    runner.event.emit(_TextChunk(session_id=sid, text="world"))

    assert view.ai_text_view.toPlainText() == "Hello world"


def test_F3_ai_stale_session_chunks_ignored(tmp_path: Path) -> None:
    """Events for a different session_id must not pollute the display."""
    target = tmp_path / "notes.txt"
    target.write_text("x", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    runner.event.emit(_TextChunk(session_id="old-session-id", text="stale"))

    assert view.ai_text_view.toPlainText() == ""


def test_F3_ai_tool_call_updates_status_label(tmp_path: Path) -> None:
    target = tmp_path / "script.py"
    target.write_text("pass\n", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    runner.event.emit(_ToolCallStart(session_id=sid, tool_use_id="tu_1", name="Read", input={}))

    assert "Read" in view.ai_status_label.text()


def test_F3_ai_session_done_completed(tmp_path: Path) -> None:
    """A completed AiResult hides cancel, shows retry, updates status label."""
    target = tmp_path / "notes.txt"
    target.write_text("stuff", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    runner.event.emit(_TextChunk(session_id=sid, text="A summary."))
    runner.session_done.emit(
        _AiResult(session_id=sid, status="completed", text="A summary.", tool_calls=1)
    )

    assert view.ai_cancel_button.isHidden() is True
    assert view.ai_retry_button.isHidden() is False
    assert view.ai_status_label.text() == "Summary"


def test_F3_ai_session_done_error_shows_error(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("stuff", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    runner.session_done.emit(
        _AiResult(session_id=sid, status="error", text="", tool_calls=0, error="timeout")
    )

    assert "timeout" in view.ai_status_label.text()
    assert view.ai_cancel_button.isHidden() is True
    assert view.ai_retry_button.isHidden() is False


def test_F3_ai_cancel_button_calls_runner_cancel(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("stuff", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    view.ai_cancel_button.click()

    assert sid in runner._cancelled


def test_F3_ai_cache_hit_skips_second_session(tmp_path: Path, monkeypatch) -> None:
    """Second toggle open of the same file uses the cached text (no new session)."""
    import multipane_commander.ui.quick_view as _qv_mod

    # Redirect disk cache to tmp_path so tests are hermetic.
    _store: dict[str, str] = {}

    def _fake_load(path):
        import multipane_commander.services.ai.cache as _c
        k = _c._key(path)
        return _store.get(k) if k else None

    def _fake_save(path, text):
        import multipane_commander.services.ai.cache as _c
        k = _c._key(path)
        if k:
            _store[k] = text

    monkeypatch.setattr(_qv_mod, "load_summary", _fake_load)
    monkeypatch.setattr(_qv_mod, "save_summary", _fake_save)

    target = tmp_path / "notes.txt"
    target.write_text("original content", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    # Simulate session completing with text.
    sid = runner._sessions[0]["id"]
    runner.event.emit(_TextChunk(session_id=sid, text="Cached summary text."))
    runner.session_done.emit(
        _AiResult(session_id=sid, status="completed", text="Cached summary text.", tool_calls=0)
    )

    # Toggle off then on again — same file.
    view.ai_button.setChecked(False)
    view.ai_button.setChecked(True)

    # Only one session was ever started; status label confirms cache hit.
    assert len(runner._sessions) == 1
    assert "Cached" in view.ai_status_label.text()


def test_F3_ai_show_path_image_auto_unchecks(tmp_path: Path) -> None:
    """Navigating to an unsummarizable file while AI is on must uncheck the button."""
    text_path = tmp_path / "notes.txt"
    text_path.write_text("text", encoding="utf-8")
    image_path = tmp_path / "photo.png"
    _make_png(image_path)

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(text_path)
    view.ai_button.setChecked(True)

    view.show_path(image_path)

    assert view.ai_button.isChecked() is False
    assert view.ai_button.isEnabled() is False
    assert view.stack.currentWidget() is view.image_scroll


def test_F3_ai_error_event_shown_in_status(tmp_path: Path) -> None:
    """AiError events update the status label."""
    target = tmp_path / "notes.txt"
    target.write_text("content", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    view.ai_button.setChecked(True)

    sid = runner._sessions[0]["id"]
    runner.event.emit(_AiError(session_id=sid, message="transport failed"))

    assert "transport failed" in view.ai_status_label.text()


def test_F3_ai_set_runtime_none_disables_button(tmp_path: Path) -> None:
    """Passing (None, None) to set_ai_runtime must disable the AI button."""
    target = tmp_path / "notes.txt"
    target.write_text("content", encoding="utf-8")

    runner = _FakeRunner()
    roots = _make_pane_roots(tmp_path)
    view = _make_widget()
    view.set_ai_runtime(runner, roots)
    view.show_path(target)
    assert view.ai_button.isEnabled() is True

    view.set_ai_runtime(None, None)

    assert view.ai_button.isEnabled() is False
