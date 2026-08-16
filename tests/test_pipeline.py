"""tests for pipeline.py.

landmarks are always manual now (see pipeline.py for why automatic detection
got dropped). fast tests use a synthetic ellipsoid with hand-placed
landmarks, and/or template_xy_com.ply (already in the frame the clip
constants assume, since it's literally the mesh the app displays as the
registration target) so harmonize() has something real to chew on without
needing a full register() pass first.
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from craniumpy_core.clipping import landmark_plane
from craniumpy_core.craniometrics import slice_center_of_mass
from craniumpy_core.io import load_mesh
from craniumpy_core.pipeline import (
    NicpTemplateConfig,
    _clip_frontal_ellipse,
    _recenter_com_z,
    analyze,
    analyze_cranial,
    harmonize,
    measure_cranial,
    register,
    register_and_clip_cranial,
    rough_bounding_clip,
)
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE, landmark_align
from craniumpy_core.remesh import repair_mesh

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "src" / "craniumpy_core" / "templates"
TEST_MESH_PATH = REPO_ROOT / "tests" / "fixtures" / "test_mesh.ply"


def _ellipsoid_with_landmarks(asymmetric: bool = False) -> tuple[trimesh.Trimesh, np.ndarray]:
    """head-scale ellipsoid with 3 landmarks in roughly the same layout as
    REFERENCE_TRIANGLE, but starting off in its own arbitrary pose - enough
    for landmark_align to have a real rotation/translation to solve without
    needing an actual scan. asymmetric=True skews the front lobe out, so the
    CoM correction actually has something to do - a plain ellipsoid is
    symmetric enough that CoM correction would just be a no-op on it."""
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    v = np.asarray(mesh.vertices).copy()
    if asymmetric:
        front = v[:, 2] > 0
        v[front, 2] *= 1.6
    mesh.vertices = v * np.array([70.0, 90.0, 60.0]) + np.array([5.0, -20.0, 8.0])
    landmarks = REFERENCE_TRIANGLE * np.array([0.9, 1.1, 0.95]) + np.array([5.0, -20.0, 8.0])
    return mesh, landmarks


def test_register_preserves_texture():
    # regression test: register() used to rebuild the mesh as bare
    # vertices+faces with no visual=, silently dropping texture/UV on every
    # analysis - a rigid transform doesn't touch UV at all, so there was
    # never a reason for that.
    mesh, landmarks = _ellipsoid_with_landmarks()
    uv = np.random.default_rng(0).random((len(mesh.vertices), 2))
    material = trimesh.visual.material.SimpleMaterial(image=Image.new("RGB", (4, 4)))
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    result = register(mesh, landmarks, target="cranium")
    assert result.mesh.visual.kind == "texture"
    np.testing.assert_array_equal(result.mesh.visual.uv, uv)


def test_register_applies_com_translation_by_default():
    mesh, landmarks = _ellipsoid_with_landmarks()
    result = register(mesh, landmarks, target="cranium", com_translation=True)

    com = slice_center_of_mass(result.mesh)
    assert com[2] == pytest.approx(0.0, abs=1.0)


def test_register_skips_com_translation_when_disabled():
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    with_com = register(mesh, landmarks, target="cranium", com_translation=True)
    without_com = register(mesh, landmarks, target="cranium", com_translation=False)

    com_with = slice_center_of_mass(with_com.mesh)
    com_without = slice_center_of_mass(without_com.mesh)
    assert com_with[2] == pytest.approx(0.0, abs=1.0)
    assert abs(com_without[2]) > 3.0


def test_register_face_target_centers_sellion_at_origin():
    mesh, landmarks = _ellipsoid_with_landmarks()
    result = register(mesh, landmarks, target="face", com_translation=True)
    np.testing.assert_allclose(result.landmarks[0], [0.0, 0.0, 0.0], atol=1e-8)


def test_register_rejects_wrong_landmark_count():
    mesh, landmarks = _ellipsoid_with_landmarks()
    with pytest.raises(ValueError):
        register(mesh, landmarks[:2], target="cranium")


def test_rough_bounding_clip_crops_far_away_geometry():
    # bolt a blob well past every margin onto the head-scale ellipsoid and
    # confirm it gets cropped, not just left there.
    mesh, landmarks = _ellipsoid_with_landmarks()
    transform = landmark_align(landmarks)
    aligned_landmarks = transform.apply(landmarks)
    plane_normal, plane_origin = landmark_plane(aligned_landmarks)

    far_point_aligned = plane_origin - plane_normal * 300.0
    far_point_raw = transform.inverse_apply(far_point_aligned.reshape(1, 3))[0]
    blob = trimesh.creation.icosphere(subdivisions=2, radius=20.0)
    blob.vertices = np.asarray(blob.vertices) + far_point_raw
    combined = trimesh.util.concatenate([mesh, blob])

    clipped = rough_bounding_clip(combined, landmarks)

    assert len(clipped.vertices) < len(combined.vertices)
    clipped_aligned = transform.apply(np.asarray(clipped.vertices))
    signed_dist = np.dot(clipped_aligned - plane_origin, plane_normal)
    assert signed_dist.min() >= -100.0 - 1e-6


def test_rough_bounding_clip_stays_within_requested_margins():
    mesh, landmarks = _ellipsoid_with_landmarks()
    clipped = rough_bounding_clip(mesh, landmarks, side_margin=50.0, front_margin=50.0, bottom_margin=100.0)

    transform = landmark_align(landmarks)
    sellion, left_tragus, right_tragus = transform.apply(landmarks)
    plane_normal, plane_origin = landmark_plane(transform.apply(landmarks))

    aligned = transform.apply(np.asarray(clipped.vertices))
    assert aligned[:, 0].max() <= left_tragus[0] + 50.0 + 1e-6
    assert aligned[:, 0].min() >= right_tragus[0] - 50.0 - 1e-6
    assert aligned[:, 2].max() <= sellion[2] + 50.0 + 1e-6
    signed_dist = np.dot(aligned - plane_origin, plane_normal)
    assert signed_dist.min() >= -100.0 - 1e-6


def test_rough_bounding_clip_front_margin_uses_whichever_landmark_is_further_forward():
    mesh, landmarks = _ellipsoid_with_landmarks()
    transform = landmark_align(landmarks)
    aligned_landmarks = transform.apply(landmarks)
    sellion_aligned = aligned_landmarks[0]

    # an alt-frontal landmark placed well forward of sellion, in raw
    # coordinates - the front margin should extend past IT, not sellion
    alt_aligned = sellion_aligned + np.array([0.0, 0.0, 40.0])
    alt_raw = transform.inverse_apply(alt_aligned.reshape(1, 3))[0]

    clipped = rough_bounding_clip(mesh, landmarks, alt_frontal_landmark=alt_raw, front_margin=5.0)
    aligned = transform.apply(np.asarray(clipped.vertices))
    assert aligned[:, 2].max() <= alt_aligned[2] + 5.0 + 1e-6
    # and it actually extended past plain sellion - otherwise this test
    # wouldn't be checking anything the sellion-only path doesn't already
    without_alt = rough_bounding_clip(mesh, landmarks, front_margin=5.0)
    aligned_without_alt = transform.apply(np.asarray(without_alt.vertices))
    assert aligned[:, 2].max() > aligned_without_alt[:, 2].max()


def test_rough_bounding_clip_returns_mesh_in_original_frame():
    mesh, landmarks = _ellipsoid_with_landmarks()
    clipped = rough_bounding_clip(mesh, landmarks, side_margin=10.0, front_margin=10.0, bottom_margin=10.0)

    bounds = mesh.bounds
    clipped_vertices = np.asarray(clipped.vertices)
    assert len(clipped_vertices) > 0
    assert len(clipped_vertices) < len(mesh.vertices)  # tight margins actually cropped something
    assert np.all(clipped_vertices >= bounds[0] - 1e-6)
    assert np.all(clipped_vertices <= bounds[1] + 1e-6)


def test_clip_frontal_ellipse_rounds_off_corners_but_keeps_cardinal_reach():
    # rough_bounding_clip's own front/side cuts collapse to an ellipse
    # rather than a box (see its docstring) - this exercises that ellipse
    # directly: a point out at the box's old diagonal CORNER (far to the
    # side AND far forward at once) should now be dropped, while a point
    # the same distance out along a single cardinal direction (straight to
    # the side, or straight ahead) stays kept - the exact same reach the
    # box always had there, just with the corners rounded off. a point
    # behind the ellipse's own back edge is kept regardless of how far to
    # the side it is, same "nothing bounds the back" property the box had.
    x_center, z_center = 0.0, 0.0
    x_semi_axis, z_semi_axis = 100.0, 60.0

    def _point_mesh(point: np.ndarray) -> trimesh.Trimesh:
        v = np.array([point, point + [1.0, 0.0, 0.0], point + [0.0, 1.0, 0.0]])
        return trimesh.Trimesh(vertices=v, faces=[[0, 1, 2]], process=False)

    corner = _point_mesh(np.array([x_semi_axis * 0.9, 0.0, z_semi_axis * 0.9]))
    clipped = _clip_frontal_ellipse(corner, x_center, x_semi_axis, z_center, z_semi_axis)
    assert len(clipped.vertices) == 0

    straight_side = _point_mesh(np.array([x_semi_axis - 1.0, 0.0, z_center]))
    clipped = _clip_frontal_ellipse(straight_side, x_center, x_semi_axis, z_center, z_semi_axis)
    assert len(clipped.vertices) > 0

    straight_ahead = _point_mesh(np.array([x_center, 0.0, z_center + z_semi_axis - 1.0]))
    clipped = _clip_frontal_ellipse(straight_ahead, x_center, x_semi_axis, z_center, z_semi_axis)
    assert len(clipped.vertices) > 0

    behind = _point_mesh(np.array([x_semi_axis * 5.0, 0.0, z_center - z_semi_axis - 1.0]))
    clipped = _clip_frontal_ellipse(behind, x_center, x_semi_axis, z_center, z_semi_axis)
    assert len(clipped.vertices) > 0


def test_harmonize_com_translation_corrects_z_only_not_x():
    # regression test: harmonize()'s own CoM re-centering step used to also
    # subtract com[0] (X, left-right), silently erasing genuine left-right
    # asymmetry (plagiocephaly, facial asymmetry) along with the intended
    # forward/back correction. only Z should move - same axis register()'s
    # own com_translation step corrects (Y was already never touched).
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    v = np.asarray(mesh.vertices).copy()
    v[v[:, 0] > 0, 0] *= 1.6  # skew mass to the +X side
    mesh.vertices = v * np.array([70.0, 90.0, 60.0]) + np.array([5.0, -20.0, 8.0])
    landmarks = REFERENCE_TRIANGLE * np.array([0.9, 1.1, 0.95]) + np.array([5.0, -20.0, 8.0])

    reg = register(mesh, landmarks, target="cranium", com_translation=False)
    result = harmonize(reg.mesh, target="cranium", landmarks=reg.landmarks, n_vertices=3000, com_translation=True)

    com = slice_center_of_mass(result)
    assert com[2] == pytest.approx(0.0, abs=1.0)
    assert abs(com[0]) > 3.0


def test_recenter_com_z_shifts_landmarks_by_the_same_offset_without_mutating_the_input():
    # regression: _recenter_com_z shifted the mesh in Z but left the
    # landmarks the caller passed in completely untouched - measure_cranial
    # then fed those now-stale (pre-shift) landmarks into frontal_bossing
    # against the ALREADY-shifted sellion_mesh, so the sellion marker would
    # visibly drift off the mesh's own sagittal profile by exactly the CoM
    # offset whenever com_translation was on (the cranial run only - the
    # facial run has no such recenter step, which is why the bug only
    # showed up on one of the two). the fix returns landmarks shifted by
    # the same offset the mesh got, and leaves the original array alone -
    # measure_cranial can be re-run (a fresh /run without a fresh /clip)
    # against the same stored clip_result, so mutating that shared array in
    # place would double-apply the offset on a second call.
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    original_landmarks = landmarks.copy()
    original_vertices = np.asarray(mesh.vertices).copy()

    shifted_landmarks, offset = _recenter_com_z(mesh, landmarks)

    offset_z = np.asarray(mesh.vertices)[:, 2] - original_vertices[:, 2]
    assert np.allclose(offset_z, offset_z[0])  # every vertex moved by the same amount (Z-only, uniform)
    assert abs(offset_z[0]) > 1.0  # the asymmetric lobe guarantees a real, non-trivial offset

    expected_landmarks = original_landmarks.copy()
    expected_landmarks[:, 2] += offset_z[0]
    np.testing.assert_allclose(shifted_landmarks, expected_landmarks)
    # the returned offset is what actually got subtracted off the mesh (and
    # added to the landmarks) - measure_cranial needs it standalone to map
    # points between two independently-recentered frames (see there)
    np.testing.assert_allclose(offset, np.array([0.0, 0.0, -offset_z[0]]))

    # the caller's own array is untouched
    np.testing.assert_array_equal(landmarks, original_landmarks)


def test_measure_cranial_threads_recenter_com_z_return_value_into_frontal_bossing(monkeypatch):
    # whitebox regression test for the wiring itself, not dependent on this
    # fixture's geometry producing a real CoM drift at this exact stage
    # (register_and_clip_cranial's own earlier com_translation may already
    # leave little or nothing left for measure_cranial's post-resample
    # recenter to correct) - monkeypatches a deliberate offset so the
    # assertion doesn't depend on incidental geometry, only on
    # measure_cranial actually using _recenter_com_z's return value for
    # craniometrics/frontal_bossing instead of the original clip_result
    # landmarks.
    #
    # frontal_bossing.sellion is snapped onto the mesh's own surface (see
    # its docstring) rather than being the given landmark verbatim, so it
    # can't be checked against raw_sellion_z - offset_z directly - on this
    # synthetic ellipsoid the landmark isn't necessarily close to the
    # surface at all, snapped or not. instead, run measure_cranial twice -
    # once unshifted, once with the deliberate offset - and check the
    # snapped sellion moves by exactly that offset between the two: a
    # uniform Z shift applied identically to the mesh and the landmark
    # shifts the snapped result by that same exact amount too, since the
    # section is cut along X and both the "above sellion" comparison and
    # the resulting dy/dz angle only ever look at RELATIVE z - so this is
    # still an exact check that measure_cranial fed the recentered (not the
    # original clip_result) landmarks into frontal_bossing, decoupled from
    # whatever the baseline snap distance happens to be on this fixture.
    import craniumpy_core.pipeline as pipeline_module

    def _fake_recenter(offset_z):
        def fake_recenter(mesh, landmarks):
            offset = np.array([0.0, 0.0, offset_z])
            mesh.vertices = np.asarray(mesh.vertices) - offset
            return (landmarks - offset if landmarks is not None else None), offset

        return fake_recenter

    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    clip_result = register_and_clip_cranial(mesh, landmarks, com_translation=True)
    raw_sellion_z = clip_result.sellion_registered_landmarks[0][2]

    monkeypatch.setattr(pipeline_module, "_recenter_com_z", _fake_recenter(0.0))
    baseline = measure_cranial(clip_result, com_translation=True, n_vertices=3000)

    offset_z = 37.5
    monkeypatch.setattr(pipeline_module, "_recenter_com_z", _fake_recenter(offset_z))
    shifted = measure_cranial(clip_result, com_translation=True, n_vertices=3000)

    assert shifted.sellion_landmarks[0][2] == pytest.approx(raw_sellion_z - offset_z, abs=1e-6)
    assert shifted.frontal_bossing.sellion[2] == pytest.approx(
        baseline.frontal_bossing.sellion[2] - offset_z, abs=1e-6
    )


def test_harmonize_cranium_on_reference_template():
    # template_xy_com.ply is already in the frame the clip constants
    # assume, so no need to run register() first just to test harmonize()
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = harmonize(template, target="cranium", landmarks=REFERENCE_TRIANGLE, n_vertices=3000)
    assert 0 < len(result.vertices) < len(template.vertices)


def test_harmonize_cranium_requires_landmarks_for_default_clip():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    with pytest.raises(ValueError):
        harmonize(template, target="cranium")


def test_harmonize_face_requires_landmarks_for_default_clip():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    with pytest.raises(ValueError):
        harmonize(template, target="face")


def test_harmonize_face_with_reference_landmarks():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = harmonize(template, target="face", landmarks=REFERENCE_TRIANGLE, n_vertices=3000)
    assert 0 < len(result.vertices) < len(template.vertices)


def test_harmonize_cranial_clip_stays_open():
    # repair runs before clipping now, specifically so it doesn't cap the
    # hole clipping just cut - regression test for that ordering bug.
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = harmonize(template, target="cranium", landmarks=REFERENCE_TRIANGLE, n_vertices=3000)
    assert not result.is_watertight


def test_harmonize_cranial_clip_cuts_near_landmark_plane():
    # regression test for the plane sitting at the actual landmark plane
    # (~y=0 for REFERENCE_TRIANGLE) instead of the old hardcoded y=-21.
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = harmonize(
        template, target="cranium", landmarks=REFERENCE_TRIANGLE, n_vertices=3000, repair=False
    )
    assert result.vertices[:, 1].min() > -10


def test_harmonize_manual_clip_mode():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = harmonize(
        template,
        target="cranium",
        clip_mode="manual",
        manual_plane_normal=[0, 1, 0],
        manual_plane_origin=[0, 0, 0],
        n_vertices=3000,
        repair=False,
    )
    assert result.vertices[:, 1].min() >= -1e-6


def test_harmonize_manual_clip_requires_plane():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    with pytest.raises(ValueError):
        harmonize(template, target="cranium", clip_mode="manual")


def test_harmonize_repair_false_skips_repair():
    template = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    # shouldn't raise even though pymeshfix never gets called here
    result = harmonize(template, target="cranium", landmarks=REFERENCE_TRIANGLE, repair=False, n_vertices=3000)
    assert len(result.vertices) > 0


def test_analyze_cranial_without_alt_frontal_uses_sellion_mesh_as_display():
    mesh, landmarks = _ellipsoid_with_landmarks()
    result = analyze_cranial(mesh, landmarks, n_vertices=3000)

    assert result.used_alt_frontal is False
    assert result.display_mesh is result.sellion_mesh
    np.testing.assert_array_equal(result.display_landmarks, result.sellion_landmarks)
    if result.sellion_hc_polygon is not None:
        np.testing.assert_array_equal(result.display_hc_polygon, result.sellion_hc_polygon)


def test_analyze_cranial_with_alt_frontal_uses_alt_mesh_as_display():
    mesh, landmarks = _ellipsoid_with_landmarks()
    # a different point on the ellipsoid surface, well clear of the real
    # landmark triangle - stands in for "subnasale instead of sellion"
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    without_alt = analyze_cranial(mesh, landmarks, n_vertices=3000)
    with_alt = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)

    assert with_alt.used_alt_frontal is True
    # the display mesh actually changed - different pose, not just a copy
    assert not np.allclose(
        np.asarray(with_alt.display_mesh.vertices).mean(axis=0),
        np.asarray(without_alt.display_mesh.vertices).mean(axis=0),
    )
    # but the numbers themselves are unaffected by which frame gets shown -
    # they always come from the sellion pass, see analyze_cranial's docstring
    assert with_alt.craniometrics.depth_mm == pytest.approx(without_alt.craniometrics.depth_mm)
    assert with_alt.craniometrics.breadth_mm == pytest.approx(without_alt.craniometrics.breadth_mm)
    assert with_alt.craniometrics.circumference_cm == pytest.approx(without_alt.craniometrics.circumference_cm)


def test_analyze_cranial_display_frontal_bossing_transforms_with_alt_frontal():
    # frontal_bossing's angle is measured against "horizontal" (the
    # frame's own z-axis), which is a genuinely different axis in the
    # display frame than the sellion one whenever a different frontal
    # landmark rotates the display frame relative to it - unlike
    # craniometrics' scalar numbers, this one is supposed to change with
    # the display frame, not just move position. sellion_frontal_bossing
    # (the sellion-pass one, used for the saved report/figure) must stay
    # exactly what it always was; display_frontal_bossing (live viewer/
    # panel) is the one that reflects the display frame.
    mesh, landmarks = _ellipsoid_with_landmarks()
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    without_alt = analyze_cranial(mesh, landmarks, n_vertices=3000)
    with_alt = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)

    assert without_alt.frontal_bossing is not None
    assert without_alt.display_frontal_bossing is without_alt.frontal_bossing  # no alt frontal - same object

    assert with_alt.frontal_bossing is not None
    assert with_alt.display_frontal_bossing is not None
    # the sellion-pass value is untouched by the alt-frontal landmark
    assert with_alt.frontal_bossing.angle_deg == pytest.approx(without_alt.frontal_bossing.angle_deg)
    np.testing.assert_allclose(with_alt.frontal_bossing.sellion, without_alt.frontal_bossing.sellion, atol=1e-6)
    # the display-frame value is positioned in the display frame, not the
    # sellion one - genuinely different coordinates, but the SAME angle,
    # carried across rather than re-derived from the transformed points
    assert not np.allclose(with_alt.display_frontal_bossing.sellion, with_alt.frontal_bossing.sellion)
    assert not np.allclose(
        with_alt.display_frontal_bossing.frontal_point, with_alt.frontal_bossing.frontal_point
    )
    assert with_alt.display_frontal_bossing.angle_deg == pytest.approx(with_alt.frontal_bossing.angle_deg)
    # "horizontal" is carried across as a rotated direction, not the display
    # frame's own +z - it has to differ from the sellion one whenever the
    # alt frontal landmark actually rotates the display frame, otherwise the
    # dashed reference line drawn from it wouldn't match the reported angle
    assert not np.allclose(with_alt.display_frontal_bossing.horizontal, with_alt.frontal_bossing.horizontal)
    np.testing.assert_allclose(np.linalg.norm(with_alt.display_frontal_bossing.horizontal), 1.0, atol=1e-6)
    # sanity: the transformed sellion sits right on the display mesh's own
    # surface (it was snapped there), not floating off it
    _, distances, _ = trimesh.proximity.closest_point(
        with_alt.display_mesh, with_alt.display_frontal_bossing.sellion[np.newaxis, :]
    )
    assert distances[0] < 1e-6


def test_analyze_cranial_asymmetry_computed_and_carried_to_display_frame():
    # same mirror-and-ICP method as facial asymmetry (see
    # craniumpy_core.asymmetry.calculate_asymmetry), applied to the cranial
    # cap - mean_asymmetry_index is a property of the sellion mesh's own
    # shape, so it's identical with or without an alt frontal landmark and
    # carried (not recomputed) into the display frame, same reasoning as
    # frontal_bossing.angle_deg above. the heatmap can't be carried the same
    # way (no vertex correspondence between the independently resampled
    # sellion/display meshes) - each display_mesh vertex borrows its value
    # from the nearest transformed sellion-mesh vertex instead, so it comes
    # out the same LENGTH as display_mesh's own vertices, not sellion_mesh's.
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    without_alt = analyze_cranial(mesh, landmarks, n_vertices=3000)
    with_alt = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)

    assert without_alt.asymmetry is not None
    assert without_alt.display_asymmetry is without_alt.asymmetry  # no alt frontal - same object

    assert with_alt.asymmetry is not None
    assert with_alt.display_asymmetry is not None
    # the sellion-pass value is unaffected by the alt-frontal landmark
    assert with_alt.asymmetry.mean_asymmetry_index == pytest.approx(without_alt.asymmetry.mean_asymmetry_index)
    # carried across, not recomputed against the display mesh
    assert with_alt.display_asymmetry.mean_asymmetry_index == pytest.approx(with_alt.asymmetry.mean_asymmetry_index)
    # heatmap is resampled onto display_mesh's own vertex count, not a copy
    # of sellion_mesh's
    assert len(with_alt.display_asymmetry.heatmap) == len(with_alt.display_mesh.vertices)
    assert len(with_alt.asymmetry.heatmap) == len(with_alt.sellion_mesh.vertices)


def test_analyze_cranial_com_correction_sellion_pass_unaffected_by_alt_frontal():
    # regression test: the sellion pass has to come out byte-identical
    # whether or not an alt_frontal_landmark is given - analyze_cranial's
    # com_translation fix bakes the sellion-tragus-plane CoM correction into
    # the raw mesh once, up front, specifically so it doesn't disturb the
    # sellion pass's own result (see the function's docstring). asymmetric
    # ellipsoid so the CoM correction actually moves something, not a no-op.
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    without_alt = analyze_cranial(mesh, landmarks, com_translation=True, n_vertices=3000)
    with_alt = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, com_translation=True, n_vertices=3000)

    np.testing.assert_allclose(
        np.asarray(without_alt.sellion_mesh.vertices), np.asarray(with_alt.sellion_mesh.vertices), atol=1e-6
    )
    np.testing.assert_allclose(without_alt.sellion_landmarks, with_alt.sellion_landmarks, atol=1e-6)
    assert without_alt.craniometrics.depth_mm == with_alt.craniometrics.depth_mm
    assert without_alt.craniometrics.breadth_mm == with_alt.craniometrics.breadth_mm
    assert without_alt.craniometrics.circumference_cm == with_alt.craniometrics.circumference_cm


def test_analyze_cranial_alt_frontal_com_uses_sellion_plane_not_independent():
    # regression test: the alt-frontal pass used to call register() with its
    # own independent com_translation, scanning slices in whatever frame the
    # alt (e.g. subnasale-tragus) triangle produced - a genuinely different,
    # more forward-tilted plane than sellion-tragus. now it always reuses the
    # sellion-plane-derived correction (see analyze_cranial's docstring /
    # _sellion_com_z_offset). checking the alt DISPLAY registration lands
    # somewhere different from what independently-computed alt-plane CoM
    # would have given confirms the correction source actually changed, not
    # just that com_translation still does *something*.
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])
    alt_landmarks = np.array([alt_frontal, landmarks[1], landmarks[2]])

    result = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, com_translation=True, n_vertices=3000)
    independent_alt_reg = register(mesh, alt_landmarks, target="cranium", com_translation=True)

    assert not np.allclose(
        np.asarray(result.display_registered_mesh.vertices).mean(axis=0),
        np.asarray(independent_alt_reg.mesh.vertices).mean(axis=0),
        atol=1e-3,
    )


def test_analyze_cranial_alt_frontal_com_correction_does_not_leak_into_x_or_y():
    # a vector that's purely Z in the sellion-aligned frame generally has
    # nonzero X/Y once expressed in the alt frame's own (differently
    # rotated) coordinates - _sellion_com_z_offset avoids that by applying
    # the same Z magnitude along each frame's own Z axis separately, never
    # rotating it between frames. checking here that turning com_translation
    # on only ever moves the alt registration's mesh centroid in Z, never X
    # or Y, relative to turning it off.
    mesh, landmarks = _ellipsoid_with_landmarks(asymmetric=True)
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    with_com = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, com_translation=True, n_vertices=3000)
    without_com = analyze_cranial(
        mesh, landmarks, alt_frontal_landmark=alt_frontal, com_translation=False, n_vertices=3000
    )

    delta = np.asarray(with_com.display_registered_mesh.vertices).mean(axis=0) - np.asarray(
        without_com.display_registered_mesh.vertices
    ).mean(axis=0)
    assert delta[0] == pytest.approx(0.0, abs=1e-6)
    assert delta[1] == pytest.approx(0.0, abs=1e-6)
    assert abs(delta[2]) > 1.0  # confirms com_translation is doing something


def test_analyze_cranial_hc_polygon_lands_on_display_mesh_surface():
    mesh, landmarks = _ellipsoid_with_landmarks()
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])
    result = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)

    assert result.display_hc_polygon is not None
    # the transformed ring shouldn't be flat in Y anymore - a rotation
    # between the two frames is exactly what "translate and angle back with
    # the clipping plane" means
    assert np.ptp(result.display_hc_polygon[:, 1]) > 1.0

    # analyze_cranial snaps the transformed ring onto alt_mesh's own surface
    # after fitting the rigid transform (see its docstring) - the two
    # independent passes' repair/clip/resample steps don't stay in exact
    # correspondence on their own, so without the snap there'd be a gap
    # between ring and mesh, worst near the boundary. should be exact (up
    # to floating point), not just close.
    _, dist, _ = trimesh.proximity.closest_point(result.display_mesh, result.display_hc_polygon)
    assert dist.max() < 1e-6


@pytest.mark.slow
def test_analyze_cranial_alt_frontal_display_mesh_has_no_rear_gouge():
    # registering on subnasale instead of sellion tips the whole head into a
    # different pose (landmark_align only pins the 3 chosen points to
    # REFERENCE_TRIANGLE, not the rest of the anatomy), and cranial_clip's
    # rear/neck safety plane is hardcoded for the sellion pose - it'll gouge
    # the occiput instead of cutting cleanly through the neck unless
    # analyze_cranial's alt pass calls harmonize with trim_rear_neck=False
    # (see clipping.cranial_clip's docstring).
    from craniumpy_core.remesh import _boundary_loops
    from craniumpy_core.template_registry import load_shipped_template

    mesh = load_shipped_template("template_xy_subanasal_com")
    sellion = np.array([0.38218775629162527, -0.4543644444793813, 80.3018352613874])
    left_tragus = np.array([61.0, -1.2, -4.1])
    right_tragus = np.array([-60.6, -1.7, -6.3])
    subnasale = np.array([0.2, -37.4, 73.4])
    landmarks = np.array([sellion, left_tragus, right_tragus])

    result = analyze_cranial(mesh, landmarks, alt_frontal_landmark=subnasale, n_vertices=None)

    loops = _boundary_loops(result.display_mesh)
    assert len(loops) == 1
    boundary_y = result.display_mesh.vertices[loops[0]][:, 1]
    # some Y-spread here is legitimate and expected even on a clean cut -
    # the alt-frame boundary is genuinely tilted relative to the sellion
    # frame (see analyze_cranial's docstring, "angle back with the clipping
    # plane"), so this can't be pinned as tight as the sellion-only case's
    # couple-mm bound. 20mm is comfortably above normal tilt noise and
    # comfortably below what a real rear gouge produces.
    assert np.ptp(boundary_y) < 20.0


@pytest.mark.slow
def test_analyze_cranial_alt_frontal_hc_ring_flush_with_real_click_coords():
    # uses real landmark coordinates from a saved report.json rather than an
    # idealized guess - exercises analyze_cranial's snap-onto-alt_mesh-surface
    # step against actual click precision, not just synthetic points.
    from craniumpy_core.template_registry import load_shipped_template

    mesh = load_shipped_template("template_xy_subanasal_com")
    sellion = np.array([0.15707502561413453, -3.7892594673064153, 80.08047788925751])
    left_tragus = np.array([61.086913285524034, -0.20366638084653843, -3.517742714574581])
    right_tragus = np.array([-60.78038313441493, -0.7896673874549753, -5.6494919282106935])
    subnasale = np.array([0.28453607942679215, -36.80986701817919, 73.6710765540875])
    landmarks = np.array([sellion, left_tragus, right_tragus])

    result = analyze_cranial(mesh, landmarks, alt_frontal_landmark=subnasale, n_vertices=None)
    _, dist, _ = trimesh.proximity.closest_point(result.display_mesh, result.display_hc_polygon)
    assert dist.max() < 1e-6


@pytest.mark.slow
def test_analyze_cranial_com_translation_off_has_no_gash():
    # with com_translation=False, the raw landmark-only registration (no
    # Z-nudge) leaves the head sitting further back than the CoM-corrected
    # pose - both cranial_clip's sphere trim and its rear/neck safety plane
    # are hardcoded against the CoM-corrected pose, so without matching
    # trim_rear_neck to com_translation they cut into real occiput instead
    # of background/neck junk. the sphere trim doesn't disconnect what it
    # cuts, so keep_largest_component can't catch it either - it shows up
    # as a genuine torn gash (see clipping.cranial_clip and
    # pipeline.analyze_cranial's docstrings).
    #
    # uses template_xy_com.ply (RAW, unclipped) rather than the shipped
    # template_xy_subanasal_com: that one got replaced mid-session with an
    # already-once-clipped mesh (see the alt-frontal tests below, which DO
    # use it, for real click coordinates against that specific file).
    # re-clipping an already-clipped mesh at the same plane removes
    # nothing, which - combined with repair sealing the resulting "no-op"
    # mesh's open boundary shut before any real clip ever reopens it -
    # produces a fully watertight result regardless of com_translation, a
    # real but unrelated pipeline gap this test isn't trying to cover.
    from craniumpy_core.remesh import _boundary_loops

    mesh = load_mesh(TEMPLATES_DIR / "template_xy_com.ply")
    result = analyze_cranial(mesh, REFERENCE_TRIANGLE, com_translation=False, n_vertices=None)

    loops = _boundary_loops(result.display_mesh)
    assert len(loops) == 1
    boundary_y = result.display_mesh.vertices[loops[0]][:, 1]
    assert np.ptp(boundary_y) < 5.0


def _split_analyze_cranial(mesh, landmarks, **kwargs):
    """register_and_clip_cranial + measure_cranial, wired up the same way
    the API's /clip and /run endpoints do it - repair happens once, up
    front, by the caller, same as analyze_cranial does internally. used to
    check the split gives the same answer as the original one-call
    analyze_cranial, since the API layer now always goes through the split
    version - see pipeline.py's module docs for why this split exists."""
    com_translation = kwargs.pop("com_translation", True)
    n_vertices = kwargs.pop("n_vertices", 10_000)
    resample_method = kwargs.pop("resample_method", "quadric")
    repaired = repair_mesh(mesh)
    clip_result = register_and_clip_cranial(repaired, landmarks, com_translation=com_translation, **kwargs)
    return measure_cranial(clip_result, com_translation=com_translation, n_vertices=n_vertices, resample_method=resample_method)


def test_register_and_clip_cranial_plus_measure_cranial_matches_analyze_cranial():
    mesh, landmarks = _ellipsoid_with_landmarks()

    expected = analyze_cranial(mesh, landmarks, n_vertices=3000)
    actual = _split_analyze_cranial(mesh, landmarks, n_vertices=3000)

    assert actual.used_alt_frontal is False
    np.testing.assert_allclose(
        np.asarray(actual.display_mesh.vertices), np.asarray(expected.display_mesh.vertices), atol=1e-6
    )
    assert actual.craniometrics.depth_mm == pytest.approx(expected.craniometrics.depth_mm)
    assert actual.craniometrics.breadth_mm == pytest.approx(expected.craniometrics.breadth_mm)
    assert actual.craniometrics.circumference_cm == pytest.approx(expected.craniometrics.circumference_cm)
    assert actual.craniometrics.mesh_volume_cc == pytest.approx(expected.craniometrics.mesh_volume_cc)


def test_register_and_clip_cranial_plus_measure_cranial_matches_analyze_cranial_with_alt_frontal():
    mesh, landmarks = _ellipsoid_with_landmarks()
    alt_frontal = landmarks[0] + np.array([0.0, -15.0, -5.0])

    expected = analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)
    actual = _split_analyze_cranial(mesh, landmarks, alt_frontal_landmark=alt_frontal, n_vertices=3000)

    assert actual.used_alt_frontal is True
    np.testing.assert_allclose(
        np.asarray(actual.display_mesh.vertices), np.asarray(expected.display_mesh.vertices), atol=1e-6
    )
    np.testing.assert_allclose(
        np.asarray(actual.sellion_mesh.vertices), np.asarray(expected.sellion_mesh.vertices), atol=1e-6
    )
    assert actual.craniometrics.depth_mm == pytest.approx(expected.craniometrics.depth_mm)
    assert actual.craniometrics.breadth_mm == pytest.approx(expected.craniometrics.breadth_mm)
    np.testing.assert_allclose(actual.display_hc_polygon, expected.display_hc_polygon, atol=1e-6)


def test_register_and_clip_cranial_does_not_resample():
    # the whole point of splitting analyze_cranial: the clip stage leaves
    # resampling for measure_cranial, so a caller iterating on the clip
    # plane never pays for quadric decimation until it actually runs the
    # final stage. n_vertices=50 here is deliberately far below the
    # clipped mesh's real vertex count, so resample_mesh (called inside
    # measure_cranial, never inside register_and_clip_cranial) has
    # something real to do rather than being a same-size no-op.
    mesh, landmarks = _ellipsoid_with_landmarks()
    repaired = repair_mesh(mesh)
    clip_result = register_and_clip_cranial(repaired, landmarks)
    clipped_count = len(clip_result.sellion_clipped_mesh.vertices)
    assert clipped_count > 50

    measured = measure_cranial(clip_result, n_vertices=50)
    assert len(measured.sellion_mesh.vertices) < clipped_count


def test_measure_cranial_with_nicp_preserves_template_topology():
    # a small synthetic template (not a real shipped one - runtime, not
    # realism, is what this test needs) stands in for what /run's
    # NicpConfig resolves server-side. the point: measure_cranial's
    # nicp_config branch returns the TEMPLATE's own topology, not
    # whatever the plain resample path would have produced.
    mesh, landmarks = _ellipsoid_with_landmarks()
    repaired = repair_mesh(mesh)
    clip_result = register_and_clip_cranial(repaired, landmarks)

    template = trimesh.creation.icosphere(subdivisions=2, radius=50.0)
    nicp_config = NicpTemplateConfig(template=template, alphas=np.linspace(50, 1, 5), inner_iters=1, dist_threshold=100.0)
    result = measure_cranial(clip_result, nicp_config=nicp_config)

    assert len(result.sellion_mesh.vertices) == len(template.vertices)
    np.testing.assert_array_equal(result.sellion_mesh.faces, template.faces)
    # craniometrics still computed cleanly off the deformed mesh
    assert result.craniometrics.depth_mm > 0


@pytest.mark.slow
def test_analyze_end_to_end_real_mesh():
    """real run on the actual test mesh: rigid registration -> harmonize ->
    craniometrics. landmarks here are just a reasonable manual guess on this
    mesh, not ground truth, so this is checking the pipeline runs clean end
    to end and gives plausible numbers - not a tight regression baseline.
    """
    mesh = load_mesh(TEST_MESH_PATH)
    landmarks = np.array([[0.0, -30.0, 90.0], [55.0, -30.0, 0.0], [-55.0, -30.0, 0.0]])
    result = analyze(mesh, landmarks, target="cranium")

    m = result.craniometrics
    assert 100 < m.depth_mm < 250
    assert 100 < m.breadth_mm < 250
    assert 40 < m.circumference_cm < 70
