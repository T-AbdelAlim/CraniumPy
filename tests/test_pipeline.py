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

from craniumpy_core.craniometrics import slice_center_of_mass
from craniumpy_core.io import load_mesh
from craniumpy_core.pipeline import analyze, harmonize, register
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "src" / "craniumpy_core" / "templates"
TEST_MESH_PATH = REPO_ROOT / "resources" / "test_mesh" / "test_mesh.ply"


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


def test_register_face_target_centers_nasion_at_origin():
    mesh, landmarks = _ellipsoid_with_landmarks()
    result = register(mesh, landmarks, target="face", com_translation=True)
    np.testing.assert_allclose(result.landmarks[0], [0.0, 0.0, 0.0], atol=1e-8)


def test_register_rejects_wrong_landmark_count():
    mesh, landmarks = _ellipsoid_with_landmarks()
    with pytest.raises(ValueError):
        register(mesh, landmarks[:2], target="cranium")


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
