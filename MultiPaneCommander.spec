# -*- mode: python ; coding: utf-8 -*-

import importlib.util
from pathlib import Path

project_root = Path(SPECPATH)


def _winpty_helper_datas():
    spec = importlib.util.find_spec("winpty")
    if spec is None or spec.submodule_search_locations is None:
        return []

    winpty_dir = Path(next(iter(spec.submodule_search_locations)))
    datas = []
    for filename in ("winpty-agent.exe", "OpenConsole.exe"):
        helper = winpty_dir / filename
        if helper.is_file():
            datas.append((str(helper), "winpty"))
    return datas


datas = []
help_file = project_root / "HELP.html"
if help_file.is_file():
    datas.append((str(help_file), "."))
xterm_assets = project_root / "src" / "multipane_commander" / "assets" / "xterm"
if xterm_assets.is_dir():
    datas.append((str(xterm_assets), "multipane_commander/assets/xterm"))
datas.extend(_winpty_helper_datas())

a = Analysis(
    ["run_app.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "libarchive",
        "mistune",
        "py7zr",
        "pygments.formatters",
        "pygments.lexers",
        "send2trash",
        "watchdog",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "ruff",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MultiPaneCommander",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MultiPaneCommander",
)
