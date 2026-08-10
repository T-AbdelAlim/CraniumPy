"""the list of template meshes that ship with the app (src/craniumpy_core/templates/).
used by the "show template overlay" viewer feature, to compare a patient's
registered mesh against the reference it was aligned to.
"""

from __future__ import annotations

import sys
from pathlib import Path

import trimesh

from .io import load_mesh

# same deal as api/main.py's FRONTEND_DIR - __file__ doesn't point at the
# source tree once this is running out of a pyinstaller exe
if getattr(sys, "frozen", False):
    TEMPLATES_DIR = Path(sys._MEIPASS) / "craniumpy_core" / "templates"
else:
    TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

SHIPPED_TEMPLATES: dict[str, str] = {
    # the plain (no "_com") full-head templates - template_xy / template_xy_com -
    # used to be listed here too, but they're really just intermediate assets
    # the clipped/face variants below were built from, not something a user
    # picking a comparison template needs to see - dropped from this dict to
    # shorten the dropdown. the files are still on disk (tests load them
    # directly by path), just not offered as a named shipped template anymore.
    "template_xy_subanasal_com": "Full head (average, subnasale landmark variant, center-of-mass shifted)",
    "clipped_template_xy": "Cranium region only",
    "clipped_template_xy_com": "Cranium region only, center-of-mass shifted",
    "template_face": "Face region only",
    "template_face_subnasale": "Face region only (subnasale variant)",
}


def load_shipped_template(name: str) -> trimesh.Trimesh:
    if name not in SHIPPED_TEMPLATES:
        raise ValueError(f"unknown template {name!r}; available: {sorted(SHIPPED_TEMPLATES)}")
    return load_mesh(TEMPLATES_DIR / f"{name}.ply")
