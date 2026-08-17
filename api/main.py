"""this FastAPI app is shared by both the web version and the desktop app.

desktop/app.py just runs this exact same app via uvicorn on localhost and
points a pywebview window at it. same backend, same frontend, two ways to
run it, no duplicated code.
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers.cohort import router as cohort_router
from api.routers.mesh import router as mesh_router
from api.routers.mesh import templates_router

# when this is running out of a pyinstaller-built exe, __file__-relative
# paths don't point at the source tree anymore - everything's unpacked
# under sys._MEIPASS instead. see desktop/craniumpy.spec for where
# "frontend" actually gets put in the bundle.
#
# non-frozen also always serves the *built* React bundle now, not the
# source tree - frontend/ is a Vite project, so `npm run build` in there
# is a required one-time step or this StaticFiles mount raises immediately
# at import (check_dir=True), taking every test and both run modes down
# with it. live frontend iteration is `npm run dev` (Vite's own dev
# server, proxying /api/* to this backend) instead, not this path.
if getattr(sys, "frozen", False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"
else:
    FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="CraniumPy")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


app.include_router(mesh_router)
app.include_router(templates_router)
app.include_router(cohort_router)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
