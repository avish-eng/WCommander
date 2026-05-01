from __future__ import annotations

import os
from pathlib import Path

import pytest

from multipane_commander.services.ai.sandbox import PaneRoots


@pytest.fixture
def roots(tmp_path: Path) -> tuple[PaneRoots, Path, Path]:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return PaneRoots(left=left, right=right), left, right


def test_contains_path_inside_left_root(roots) -> None:
    pane_roots, left, _ = roots
    inner = left / "sub" / "file.txt"
    inner.parent.mkdir(parents=True)
    inner.write_text("x")
    assert pane_roots.contains(inner) is True


def test_contains_path_inside_right_root(roots) -> None:
    pane_roots, _, right = roots
    inner = right / "deep" / "nested" / "file.bin"
    inner.parent.mkdir(parents=True)
    inner.write_text("x")
    assert pane_roots.contains(inner) is True


def test_contains_root_itself(roots) -> None:
    pane_roots, left, right = roots
    assert pane_roots.contains(left) is True
    assert pane_roots.contains(right) is True


def test_contains_rejects_outside_path(roots, tmp_path) -> None:
    pane_roots, _, _ = roots
    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("nope")
    assert pane_roots.contains(outside) is False


def test_contains_rejects_dotdot_escape(roots, tmp_path) -> None:
    pane_roots, left, _ = roots
    # Path("left/../../escape") resolves to outside both roots.
    escape = left / ".." / ".." / "escape"
    assert pane_roots.contains(escape) is False


def test_contains_rejects_absolute_root(roots) -> None:
    pane_roots, _, _ = roots
    # Absolute path well outside both roots.
    assert pane_roots.contains(Path("/etc/passwd")) is False


def test_contains_resolves_symlink_pointing_outside(roots, tmp_path) -> None:
    pane_roots, left, _ = roots
    if os.name == "nt":
        pytest.skip("symlink semantics differ on Windows; not required for this test")
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = left / "link.txt"
    link.symlink_to(outside)
    # Realpath escapes the sandbox -> denied.
    assert pane_roots.contains(link) is False


def test_contains_handles_nonexistent_path_inside_root(roots) -> None:
    pane_roots, left, _ = roots
    # Non-existent file under left; resolve(strict=False) keeps it inside.
    assert pane_roots.contains(left / "ghost.txt") is True
