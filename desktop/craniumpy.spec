# -*- mode: python ; coding: utf-8 -*-
# pyinstaller spec for the standalone exe. build with:
#   pyinstaller desktop/craniumpy.spec
# from the repo root, with the venv active.
#
# built and actually launched this once with console=True to make sure it
# doesn't just silently die on startup - it worked (full upload -> landmark
# -> analyze -> results bundle flow, all confirmed against the real exe, not
# just "it built"). console=False now for the real build.

from pathlib import Path

# SPECPATH is the dir containing this .spec file (desktop/), so go up one
REPO_ROOT = Path(SPECPATH).parent

datas = [
    # frontend/ is now a Vite project - bundle the built output, not the
    # source tree. `npm run build` in frontend/ has to happen before this
    # spec runs, or Analysis() fails fast here with the dist dir missing.
    (str(REPO_ROOT / "frontend" / "dist"), "frontend"),
    (str(REPO_ROOT / "src" / "craniumpy_core" / "templates"), "craniumpy_core/templates"),
]

# uvicorn picks its event loop / protocol implementations dynamically at
# runtime, which pyinstaller's static import analysis doesn't see on its
# own - has to be told about these by hand or the bundled exe fails on
# startup with a "no module named uvicorn.loops.auto" type error.
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "pymeshfix._meshfix",
]

icon_path = REPO_ROOT / "resources" / "CraniumPy_logo.ico"

a = Analysis(
    [str(REPO_ROOT / "desktop" / "app.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # results_bundle.py only ever uses matplotlib's headless Agg canvas
    # directly (FigureCanvasAgg) - no pyplot, no interactive window. without
    # this, pyinstaller's matplotlib hook auto-discovers and drags in a
    # whole Tk GUI backend (plus tkinter itself) that never actually gets
    # used, just bloats the exe.
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CranioSuite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path) if icon_path.exists() else None,
)
