from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from multipane_commander.config.model import ThemeDefinition
from multipane_commander.platform import app_data_dir


def theme_backup_dir() -> Path:
    return app_data_dir() / "backup themes"


def backup_theme_definition(
    theme: ThemeDefinition,
    *,
    backup_dir: Path | None = None,
) -> Path:
    destination_dir = backup_dir or theme_backup_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{theme.id}.json"
    destination.write_text(
        json.dumps(asdict(theme), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
