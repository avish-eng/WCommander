from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from multipane_commander.platform import app_data_dir

_LOG_FILE: Path | None = None


def log_file_path() -> Path:
    return app_data_dir() / "wcommander.log"


def setup_logging(level: int = logging.DEBUG) -> None:
    global _LOG_FILE
    log_path = log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = log_path

    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Rotating file: 2 MB × 3 backups
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)

    root.setLevel(level)
    root.addHandler(fh)

    # Also propagate WARNING+ to stderr so the terminal shows important stuff.
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)

    logging.getLogger("multipane_commander").info(
        "Logging started — writing to %s", log_path
    )
