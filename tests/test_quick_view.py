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

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea

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
