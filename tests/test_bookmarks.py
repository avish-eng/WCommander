from pathlib import Path

from multipane_commander.services.bookmarks import BookmarkStore


def test_bookmark_store_toggles_paths() -> None:
    store = BookmarkStore()
    path = Path(r"C:\temp")

    store.toggle(path)
    assert store.is_bookmarked(path) is True

    store.toggle(path)
    assert store.is_bookmarked(path) is False
