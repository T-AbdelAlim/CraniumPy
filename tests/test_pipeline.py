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

from craniumpy_core.craniometrics import slice_center_of_mass
from craniumpy_core.io import load_mesh
from craniumpy_core.pipeline import (
    analyze,
    analyze_cranial,
    harmonize,
    measure_cranial,
    register,
    register_and_clip_cranial,
)
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE
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
