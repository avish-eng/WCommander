from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArchiveCapabilities:
    browse: bool = True
    extract: bool = True
    create: bool = False
    add: bool = False
    delete: bool = False
    rename: bool = False
    test: bool = False
