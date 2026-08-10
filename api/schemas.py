from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LandmarkPoint(BaseModel):
    x: float
    y: float
    z: float


class ClippingConfig(BaseModel):
    # leave as None to get the usual clip for the target (cranial for cranium,
    # facial for face). "manual" needs both plane fields below - comes from
    # the plane widget in the viewer
    mode: Literal["cranial", "facial", "manual"] | None = None
    manual_plane_normal: tuple[float, float, float] | None = None
    manual_plane_origin: tuple[float, float, float] | None = None


class HarmonizeConfig(BaseModel):
    n_vertices: int | None = 10_000
    repair: bool = True
    repair_method: Literal["pymeshfix", "trimesh"] = "pymeshfix"


class AnalyzeRequest(BaseModel):
    target: Literal["cranium", "face"] = "cranium"
    # nasion, left_tragus, right_tragus in that order, in the mesh's own
    # coordinates. always required now, always picked manually - see
    # pipeline.py for why I dropped automatic detection
    landmarks: list[LandmarkPoint] = Field(min_length=3, max_length=3)
    # optional, cranium-only: an alternate frontal point (e.g. subnasale)
    # that takes over as the registration/clip/display frame for
    # everything shown/saved, while nasion (still mandatory above) stays
    # the anchor for the actual measurements and the saved 2D figure - see
    # craniumpy_core.pipeline.analyze_cranial for why nasion can't just be
    # swapped out for this instead of adding it alongside.
    alt_frontal_landmark: LandmarkPoint | None = None
    com_translation: bool = True
    clipping: ClippingConfig = ClippingConfig()
    harmonize: HarmonizeConfig = HarmonizeConfig()


class TemplateInfo(BaseModel):
    name: str
    description: str


class UploadResponse(BaseModel):
    session_id: str
    vertex_count: int
    face_count: int


class OpenFromPathsRequest(BaseModel):
    # absolute local filesystem paths - the mesh plus, optionally, its
    # .mtl/texture companions, all picked in one go by the desktop app's
    # native (multi-select) file dialog. see api/routers/mesh.py's
    # open_mesh_from_paths and desktop/app.py's pick_file.
    paths: list[str] = Field(min_length=1)


class SaveResultsResponse(BaseModel):
    saved_to: str


class ProgressInfo(BaseModel):
    stage: str
    detail: str


class StatusResponse(BaseModel):
    status: Literal["idle", "running", "done", "error"]
    error: str | None = None
    progress: ProgressInfo | None = None


class CraniometricsResponse(BaseModel):
    slice_height: float
    depth_mm: float
    breadth_mm: float
    cephalic_index: float
    circumference_cm: float
    mesh_volume_cc: float
    # the HC slice outline, so the viewer can draw the red line overlay -
    # see craniumpy_core.craniometrics.hc_slice_polygon
    hc_slice_polygon: list[LandmarkPoint]


class AsymmetryResponse(BaseModel):
    mean_asymmetry_index: float
    # one signed distance (mm) per vertex of the result mesh, same order -
    # see craniumpy_core.asymmetry.calculate_asymmetry. zeroed out on one
    # half by design (see that module's docstring), for the viewer's
    # blue(dent)/red(protruded) heatmap overlay.
    heatmap: list[float]


class ResultsResponse(BaseModel):
    landmarks: list[LandmarkPoint]
    vertex_count: int
    craniometrics: CraniometricsResponse | None = None
    asymmetry: AsymmetryResponse | None = None
    # True when an alt_frontal_landmark was given and the shown/saved mesh
    # is in that frame instead of the nasion one - see AnalyzeRequest
    used_alt_frontal: bool = False
