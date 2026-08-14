# -*- mode: python ; coding: utf-8 -*-
# pyinstaller spec for the macOS .app. build on an actual Mac (pyinstaller
# can't cross-compile) with:
#   pip install -e ".[desktop]"
#   pyinstaller desktop/craniumpy_mac.spec
# from the repo root, with the venv active. produces dist/CraniumPy.app.
#
# BUNDLE()/COLLECT() instead of the windows spec's single-EXE onefile: a
# .app is the normal shape for a macOS GUI app (Finder/Dock expect one),
# and it sidesteps the windows onefile build's runtime-extract-to-temp
# step entirely - nothing gets extracted at launch, so there's nothing to
# fail to clean up at exit either.

from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent

datas = [
    # frontend/ is now a Vite project - bundle the built output, not the
    # source tree. `npm run build` in frontend/ has to happen before this
    # spec runs, or Analysis() fails fast here with the dist dir missing.
    (str(REPO_ROOT / "frontend" / "dist"), "frontend"),
    (str(REPO_ROOT / "src" / "craniumpy_core" / "templates"), "craniumpy_core/templates"),
]

# same reasoning as the windows spec - uvicorn/pymeshfix resolve some of
# their submodules dynamically at runtime, which pyinstaller's static
# import analysis doesn't see on its own.
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

icon_path = REPO_ROOT / "resources" / "CraniumPy_logo.icns"

a = Analysis(
    [str(REPO_ROOT / "desktop" / "app.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # see the windows spec for why - matplotlib's Agg-only, no Tk needed.
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CraniumPy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CraniumPy",
)
app = BUNDLE(
    coll,
    name="CraniumPy.app",
    icon=str(icon_path) if icon_path.exists() else None,
    bundle_identifier="nl.erasmusmc.craniumpy",
    info_plist={
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.medical",
    },
)
