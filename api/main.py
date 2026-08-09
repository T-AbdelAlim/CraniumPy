"""this FastAPI app is shared by both the web version and the desktop app.

desktop/app.py just runs this exact same app via uvicorn on localhost and
points a pywebview window at it. same backend, same frontend, two ways to
run it, no duplicated code.
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers.mesh import router as mesh_router
from api.routers.mesh import templates_router

# when this is running out of a pyinstaller-built exe, __file__-relative
# paths don't point at the source tree anymore - everything's unpacked
# under sys._MEIPASS instead. see desktop/craniumpy.spec for where
# "frontend" actually gets put in the bundle.
if getattr(sys, "frozen", False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"
else:
    FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="CraniumPy")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


app.include_router(mesh_router)
app.include_router(templates_router)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
