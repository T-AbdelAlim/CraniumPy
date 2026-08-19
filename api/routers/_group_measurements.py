"""shared reshaping helper: craniumpy_core.cohort.GroupMeasurements (the
dataclass measure_mean_shape returns) -> CohortMeanShapeMeasurementsResponse
(the same per-metric response models ResultsResponse uses). factored out of
api/routers/cohort.py's own get_mean_shape_measurements so
api/routers/longitudinal.py can reuse the exact same reshaping for a
Longitudinal comparison's "measure this already-registered mesh" endpoint,
instead of a second copy of this same field-by-field mapping.
"""

from __future__ import annotations

import trimesh

from craniumpy_core import cohort
from craniumpy_core.craniometrics import hc_slice_polygon
from api.schemas import (
    AsymmetryResponse,
    CohortMeanShapeMeasurementsResponse,
    CraniometricsResponse,
    FrontalBossingResponse,
    LandmarkPoint,
    MetopicResponse,
    Point2D,
)


def group_measurements_response(mesh: trimesh.Trimesh, gm: cohort.GroupMeasurements) -> CohortMeanShapeMeasurementsResponse:
    craniometrics = None
    if gm.craniometrics is not None:
        m = gm.craniometrics
        polygon = hc_slice_polygon(mesh, m.slice_height)
        craniometrics = CraniometricsResponse(
            slice_height=m.slice_height,
            depth_mm=m.depth_mm,
            breadth_mm=m.breadth_mm,
            cephalic_index=m.cephalic_index,
            circumference_cm=m.circumference_cm,
            mesh_volume_cc=float(m.mesh_volume_cc),
            hc_slice_polygon=[LandmarkPoint(x=p[0], y=p[1], z=p[2]) for p in (polygon if polygon is not None else [])],
            front_opt=LandmarkPoint(x=m.front_opt[0], y=m.front_opt[1], z=m.front_opt[2]),
            occ_opt=LandmarkPoint(x=m.occ_opt[0], y=m.occ_opt[1], z=m.occ_opt[2]),
            lh_opt=LandmarkPoint(x=m.lh_opt[0], y=m.lh_opt[1], z=m.lh_opt[2]),
            rh_opt=LandmarkPoint(x=m.rh_opt[0], y=m.rh_opt[1], z=m.rh_opt[2]),
        )

    asymmetry = AsymmetryResponse(
        mean_asymmetry_index=gm.asymmetry.mean_asymmetry_index, heatmap=gm.asymmetry.heatmap.tolist()
    )

    metopic = None
    if gm.metopic is not None:
        mp = gm.metopic
        metopic = MetopicResponse(
            slice_height=gm.slice_height,
            contour=[Point2D(x=p[0], z=p[1]) for p in mp.contour],
            arc_length=mp.arc_length.tolist(),
            normalized_arc_length=mp.normalized_arc_length.tolist(),
            midline_u=mp.midline_u,
            parabola_a=mp.parabola_a,
            parabola_c=mp.parabola_c,
            deviation_profile=mp.deviation_profile.tolist(),
            gradient_profile=mp.gradient_profile.tolist(),
            curvature_profile=mp.curvature_profile.tolist(),
            frontal_angle_deg=mp.frontal_angle_deg,
            frontal_angle_points=[Point2D(x=p[0], z=p[1]) for p in mp.frontal_angle_points],
            forehead_width_mm=mp.forehead_width_mm,
            midline_curvature_concentration=mp.midline_curvature_concentration,
            midline_max_curvature=mp.midline_max_curvature,
            midline_max_curvature_position=mp.midline_max_curvature_position,
            ridge_protrusion_mm=mp.ridge_protrusion_mm,
            ridge_protrusion_position=mp.ridge_protrusion_position,
            ridge_area_mm2=mp.ridge_area_mm2,
            ridge_area_normalized=mp.ridge_area_normalized,
            left_temporal_hollowing=mp.left_temporal_hollowing,
            right_temporal_hollowing=mp.right_temporal_hollowing,
            mean_temporal_hollowing=mp.mean_temporal_hollowing,
            left_max_temporal_depth_mm=mp.left_max_temporal_depth_mm,
            right_max_temporal_depth_mm=mp.right_max_temporal_depth_mm,
            parabolic_deviation_index=mp.parabolic_deviation_index,
            central_window=mp.central_window,
            left_temporal_window=mp.left_temporal_window,
            right_temporal_window=mp.right_temporal_window,
        )

    frontal_bossing_response = None
    if gm.frontal_bossing is not None:
        fb = gm.frontal_bossing
        frontal_bossing_response = FrontalBossingResponse(
            angle_deg=fb.angle_deg,
            sellion=LandmarkPoint(x=fb.sellion[0], y=fb.sellion[1], z=fb.sellion[2]),
            frontal_point=LandmarkPoint(x=fb.frontal_point[0], y=fb.frontal_point[1], z=fb.frontal_point[2]),
            profile=[LandmarkPoint(x=p[0], y=p[1], z=p[2]) for p in fb.profile],
            horizontal=LandmarkPoint(x=fb.horizontal[0], y=fb.horizontal[1], z=fb.horizontal[2]),
        )

    return CohortMeanShapeMeasurementsResponse(
        craniometrics=craniometrics, asymmetry=asymmetry, metopic=metopic, frontal_bossing=frontal_bossing_response,
    )
