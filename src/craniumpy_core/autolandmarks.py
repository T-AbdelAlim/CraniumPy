"""automated landmarking: sellion, left and right tragus and subnasale on a
raw head scan, whatever its orientation or position.

two stages:
1. pose - the head template (template_xy) is fitted to the scan from a few
   hundred starting rotations with a trimmed, scaled ICP. only the face and
   ears are used for the fit: the vault is close to a ball and fits in
   almost any orientation, the face and ears don't. the best fit gives a
   head frame (x left, y up, z forward) and a first guess of every
   landmark.
2. refinement - around each guess the scan is turned into a 1 mm relief
   map (outer surface height over a plane) and matched against an average
   relief patch (templates/landmark_patches.npz, built from manually
   landmarked scans) by normalised cross-correlation: once with a large
   patch to find the ear/nose, then with a small one for the point itself.
   the sellion then follows from the midline profile in the frame the
   subnasale and tragi define: the deepest point between nose tip and
   glabella.

scans are assumed to be in mm. every landmark comes with a matching score
and a flag when it looks unreliable (ear hidden by a shoulder or clothing,
no clear nasal root) so the caller can ask for a manual check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import trimesh
from numpy.lib.stride_tricks import sliding_window_view
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from .registration.rigid import REFERENCE_TRIANGLE, landmark_align
from .template_registry import TEMPLATES_DIR

POSE_TEMPLATE = "template_xy.ply"
PATCHES_FILE = "landmark_patches.npz"

RELIEF_HALF = 50  # relief maps cover +-50 mm around the first guess
HIGHPASS_SIGMA = 10.0  # mm - removes the overall head curvature
COARSE_HALF, COARSE_SEARCH = 25, 24
FINE_HALF = {"ear": 7, "nose": 10}
FINE_SEARCH = 6
DISTANCE_PRIOR = 0.005  # score penalty per mm away from the expected spot

# below these the match is flagged for a manual check
MIN_SCORE = {"ear": 0.6, "nose": 0.6}
MAX_TRAGUS_ASYMMETRY = 5.0  # mm

# relief map axes per landmark, rows: in-plane u, in-plane w, height. the
# ears are looked at from the side. the subnasale is looked at from below
# the nose at 45 degrees: straight from the front the nose tip overhangs
# it, and the surface found along the line of sight is the columella a
# few mm in front of the actual point.
_S = 0.5**0.5
_AXES = {
    "left_tragus": np.array([[0.0, 1, 0], [0, 0, 1], [1, 0, 0]]),
    "right_tragus": np.array([[0.0, 1, 0], [0, 0, 1], [-1, 0, 0]]),
    "subnasale": np.array([[1.0, 0, 0], [0, _S, _S], [0, -_S, _S]]),
}


@dataclass
class AutoLandmarks:
    sellion: np.ndarray
    left_tragus: np.ndarray
    right_tragus: np.ndarray
    subnasale: np.ndarray
    scores: dict[str, float] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "sellion": self.sellion.tolist(),
            "left_tragus": self.left_tragus.tolist(),
            "right_tragus": self.right_tragus.tolist(),
            "subnasale": self.subnasale.tolist(),
            "scores": {k: round(float(v), 3) for k, v in self.scores.items()},
            "flags": dict(self.flags),
        }


# --------------------------------------------------------------------------
# surface sampling
# --------------------------------------------------------------------------


def sample_surface(mesh: trimesh.Trimesh, n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """n area-weighted points on the surface plus their face normals. not
    trimesh.sample - this one is seeded and skips degenerate faces."""
    tri = np.asarray(mesh.triangles)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cross, axis=1)
    keep = area > 0
    tri, cross, area = tri[keep], cross[keep], area[keep]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(tri), n, p=area / area.sum())
    u, v = rng.random((2, n))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    t = tri[idx]
    points = t[:, 0] + u[:, None] * (t[:, 1] - t[:, 0]) + v[:, None] * (t[:, 2] - t[:, 0])
    return points, cross[idx] / area[idx][:, None]


def head_centre(points: np.ndarray, normals: np.ndarray, cell: float = 6.0) -> np.ndarray:
    """rough centre of the head: a head is close to a ball, so stepping
    65-95 mm along the normal from every surface point piles up around the
    same spot (both directions, scans don't agree on face winding). the
    densest 3x3x3 block of a 6 mm vote grid wins - shoulders and neck vote
    for a much more spread out set of centres."""
    votes = np.vstack([points + s * r * normals for r in (65.0, 75.0, 85.0, 95.0) for s in (-1, 1)])
    cells = np.floor(votes / cell).astype(np.int64)
    lo = cells.min(axis=0)
    dims = cells.max(axis=0) - lo + 1
    grid = np.zeros(dims, dtype=np.float32)
    np.add.at(grid, tuple((cells - lo).T), 1)
    block = ndimage.uniform_filter(grid, size=3, mode="constant")
    best = np.unravel_index(int(np.argmax(block)), block.shape)
    return (np.asarray(best) + lo + 0.5) * cell


# --------------------------------------------------------------------------
# pose search
# --------------------------------------------------------------------------


def _start_rotations(n_axes: int = 64, n_spin: int = 10) -> np.ndarray:
    """roughly uniform rotations: fibonacci-sphere directions for the
    template's forward axis, each with n_spin turns around it."""
    i = np.arange(n_axes) + 0.5
    phi = np.arccos(1 - 2 * i / n_axes)
    theta = np.pi * (1 + 5**0.5) * i
    axes = np.c_[np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)]
    spins = Rotation.from_rotvec(np.c_[np.zeros(n_spin), np.zeros(n_spin), 2 * np.pi * np.arange(n_spin) / n_spin])
    out = []
    for a in axes:
        base = Rotation.align_vectors([a], [[0.0, 0.0, 1.0]])[0]
        out.extend((base * spins).as_matrix())
    return np.asarray(out)


def _batched_similarity(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """umeyama for a batch of matched point sets, (B, m, 3) each.
    returns rotation (B,3,3), scale (B,), translation (B,3)."""
    a, b = src.mean(axis=1), dst.mean(axis=1)
    x, y = src - a[:, None], dst - b[:, None]
    u, s, vt = np.linalg.svd(np.einsum("bmi,bmj->bij", y, x))
    d = np.sign(np.linalg.det(u @ vt))
    signs = np.ones((len(d), 3))
    signs[:, 2] = d
    R = u @ (signs[:, :, None] * vt)
    scale = (s * signs).sum(axis=1) / (x * x).sum(axis=(1, 2))
    return R, scale, a, b


def _icp(R, s, t, src, tree, iters, trim, free_scale, scale_range=(0.6, 1.3)):
    """trimmed (scaled) ICP from a batch of starts. template points src are
    matched to their nearest scan point; the worst (1 - trim) are left out
    each round so neck, shoulders or a missing chin don't drag the fit."""
    keep_n = int(len(src) * trim)
    for _ in range(iters):
        moved = s[:, None, None] * np.einsum("ij,bkj->bik", src, R) + t[:, None]
        d, j = tree.query(moved.reshape(-1, 3), workers=-1)
        d, j = d.reshape(len(R), -1), j.reshape(len(R), -1)
        order = np.argsort(d, axis=1)[:, :keep_n]
        matched_src = src[order]
        matched_dst = tree.data[np.take_along_axis(j, order, axis=1)]
        R, s_new, a, b = _batched_similarity(matched_src, matched_dst)
        s = np.clip(s_new, *scale_range) if free_scale else s
        t = b - s[:, None] * np.einsum("bij,bj->bi", R, a)
    return R, s, t


def _fit_score(R, s, t, src, src_normals, tree, normals, sigma=4.0):
    """how well the template lies on the scan: gaussian of the distance,
    times agreement of the normals (sign ignored)."""
    moved = s[:, None, None] * np.einsum("ij,bkj->bik", src, R) + t[:, None]
    d, j = tree.query(moved.reshape(-1, 3), workers=-1)
    d, j = d.reshape(len(R), -1), j.reshape(len(R), -1)
    n_moved = np.einsum("ij,bkj->bik", src_normals, R)
    agree = np.abs((n_moved * normals[j]).sum(axis=2))
    return (np.exp(-0.5 * (d / sigma) ** 2) * agree**2).mean(axis=1)


@lru_cache(maxsize=1)
def _pose_template():
    mesh = trimesh.load(TEMPLATES_DIR / POSE_TEMPLATE, process=False)
    points, normals = sample_surface(mesh, 6000, seed=1)
    x, y, z = points.T
    face = (z > 5) & (y > -70) & (y < 55)
    ears = (np.abs(x) > 50) & (y > -45) & (y < 40) & (np.abs(z + 28) < 40)
    distinctive = np.nonzero(face | ears)[0]
    vault = np.nonzero(y > -40)[0]
    return points, normals, head_centre(points, normals), distinctive, vault


@dataclass
class HeadPose:
    """template frame -> scan: scan = scale * template @ rotation.T + translation"""

    rotation: np.ndarray
    scale: float
    translation: np.ndarray
    score: float
    runner_up: float

    def to_scan(self, p: np.ndarray) -> np.ndarray:
        return self.scale * (np.asarray(p) @ self.rotation.T) + self.translation

    def to_head(self, p: np.ndarray) -> np.ndarray:
        """scan -> head frame in mm (template orientation, not rescaled)"""
        return (np.asarray(p) - self.translation) @ self.rotation


def find_head_pose(mesh: trimesh.Trimesh) -> HeadPose:
    tp, tn, tc, distinctive, vault = _pose_template()
    sp, sn = sample_surface(mesh, 40000)
    tree = cKDTree(sp)
    centre = head_centre(sp, sn)

    rng = np.random.default_rng(0)
    coarse = rng.choice(distinctive, 400, replace=False)
    starts = _start_rotations()
    candidates = []
    for s0 in (0.85, 1.0):  # an infant's face is quite a bit smaller than the template's
        R = starts
        s = np.full(len(R), s0)
        t = centre - s0 * np.einsum("bij,j->bi", R, tc)
        R, s, t = _icp(R, s, t, tp[coarse], tree, 6, trim=0.85, free_scale=False)
        score = _fit_score(R, s, t, tp[coarse], tn[coarse], tree, sn)
        candidates.append((score, R, s, t))
    score = np.concatenate([c[0] for c in candidates])
    R = np.concatenate([c[1] for c in candidates])
    s = np.concatenate([c[2] for c in candidates])
    t = np.concatenate([c[3] for c in candidates])

    top = np.argsort(-score)[:32]
    R, s, t = _icp(R[top], s[top], t[top], tp[distinctive], tree, 25, trim=0.85, free_scale=True)
    # the face/ears decide, the vault breaks ties (an upside-down face fit
    # leaves the vault hanging in the air)
    total = _fit_score(R, s, t, tp[distinctive], tn[distinctive], tree, sn) + _fit_score(
        R, s, t, tp[vault], tn[vault], tree, sn
    )
    order = np.argsort(-total)
    best = order[0]
    # the best fit that is a genuinely different pose, for the confidence margin
    probe = tp[::50]
    best_points = s[best] * probe @ R[best].T + t[best]
    runner_up = 0.0
    for k in order[1:]:
        if np.linalg.norm(s[k] * probe @ R[k].T + t[k] - best_points, axis=1).mean() > 15:
            runner_up = float(total[k])
            break
    return HeadPose(R[best], float(s[best]), t[best], float(total[best]), runner_up)


# --------------------------------------------------------------------------
# local refinement
# --------------------------------------------------------------------------


def relief_map(points: np.ndarray, centre: np.ndarray, axes: np.ndarray) -> np.ndarray:
    """outer surface height (along axes[2]) over a 1 mm grid in the
    (axes[0], axes[1]) plane, +-RELIEF_HALF around centre. small gaps are
    filled from the nearest cell, anything further than 4 mm from data is
    nan."""
    a, b, h = ((points - centre) @ axes.T).T
    keep = (np.abs(a) <= RELIEF_HALF) & (np.abs(b) <= RELIEF_HALF) & (h > -45)
    i = np.round(a[keep]).astype(int) + RELIEF_HALF
    j = np.round(b[keep]).astype(int) + RELIEF_HALF
    size = 2 * RELIEF_HALF + 1
    img = np.full((size, size), -np.inf)
    np.maximum.at(img, (i, j), h[keep])
    empty = np.isinf(img)
    if empty.all():
        return np.full((size, size), np.nan)
    dist, (ii, jj) = ndimage.distance_transform_edt(empty, return_indices=True)
    filled = img[ii, jj]
    filled[dist > 4] = np.nan
    return filled


def highpass(img: np.ndarray, sigma: float = HIGHPASS_SIGMA) -> np.ndarray:
    known = ~np.isnan(img)
    if not known.any():
        return np.zeros_like(img)
    flat = np.where(known, img, np.nanmedian(img))
    return (flat - ndimage.gaussian_filter(flat, sigma)) * known


def _ncc(img, patch, ci, cj, search, prior):
    """normalised cross-correlation of patch over img, centred on (ci, cj)
    +-search cells. returns (score, i, j) with sub-cell i, j."""
    half = patch.shape[0] // 2
    windows = sliding_window_view(img, patch.shape)[
        ci - search - half : ci + search - half + 1, cj - search - half : cj + search - half + 1
    ]
    shape = windows.shape[:2]
    w = windows.reshape(*shape, -1)
    w = w - w.mean(axis=-1, keepdims=True)
    p = (patch - patch.mean()).ravel()
    p = p / (np.linalg.norm(p) + 1e-9)
    c = (w * p).sum(axis=-1) / (np.linalg.norm(w, axis=-1) + 1e-6)
    I, J = np.indices(shape)
    i, j = np.unravel_index(int(np.argmax(c - prior * np.hypot(I - search, J - search))), shape)
    di = dj = 0.0
    if 0 < i < shape[0] - 1:
        curv = c[i - 1, j] - 2 * c[i, j] + c[i + 1, j]
        di = 0.5 * (c[i - 1, j] - c[i + 1, j]) / curv if curv < 0 else 0.0
    if 0 < j < shape[1] - 1:
        curv = c[i, j - 1] - 2 * c[i, j] + c[i, j + 1]
        dj = 0.5 * (c[i, j - 1] - c[i, j + 1]) / curv if curv < 0 else 0.0
    return float(c[i, j]), ci - search + i + di, cj - search + j + dj


def _warp(patch: np.ndarray, angle_deg: float, scale: float) -> np.ndarray:
    half = patch.shape[0] // 2
    th = np.deg2rad(angle_deg)
    M = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]) / scale
    return ndimage.affine_transform(patch, M, offset=np.array([half, half]) - M @ [half, half], order=1, mode="nearest")


def match_patch(img_hp: np.ndarray, coarse: np.ndarray, fine: np.ndarray, warps: bool) -> tuple[float, float, float]:
    """coarse patch (rotated/scaled a little when warps) to find the
    structure, then the fine one to place the point. returns (coarse
    score, i, j) in relief-map cells."""
    c0 = RELIEF_HALF
    angles, scales = ((-20, -10, 0, 10, 20), (0.85, 1.0, 1.15)) if warps else ((0,), (1.0,))
    best = None
    for a in angles:
        for s in scales:
            patch = coarse if (a == 0 and s == 1.0) else _warp(coarse, a, s)
            v, i, j = _ncc(img_hp, patch, c0, c0, COARSE_SEARCH, DISTANCE_PRIOR)
            ranked = v - DISTANCE_PRIOR * np.hypot(i - c0, j - c0)
            if best is None or ranked > best[0]:
                best = (ranked, v, i, j)
    _, v, i, j = best
    _, fi, fj = _ncc(img_hp, fine, int(round(i)), int(round(j)), FINE_SEARCH, DISTANCE_PRIOR)
    return v, fi, fj


@lru_cache(maxsize=1)
def load_patches() -> dict[str, np.ndarray]:
    with np.load(TEMPLATES_DIR / PATCHES_FILE) as f:
        return {k: f[k] for k in f.files}


def _surface_height(img: np.ndarray, i: float, j: float) -> float | None:
    v = ndimage.map_coordinates(img, [[i], [j]], order=1, mode="nearest")[0]
    if np.isnan(v):
        near = img[int(round(i)) - 1 : int(round(i)) + 2, int(round(j)) - 1 : int(round(j)) + 2]
        return float(np.nanmean(near)) if np.isfinite(near).any() else None
    return float(v)


# --------------------------------------------------------------------------
# sellion
# --------------------------------------------------------------------------


def _front_profile(v, half_width=3.0, y_lo=-10.0, y_hi=110.0, step=1.0):
    """per 1 mm height bin: the most anterior midline point."""
    mid = v[(np.abs(v[:, 0]) < half_width) & (v[:, 1] > y_lo) & (v[:, 1] < y_hi) & (v[:, 2] > -20)]
    ys = np.arange(y_lo, y_hi, step)
    z = np.full(len(ys), np.nan)
    if len(mid):
        idx = np.floor((mid[:, 1] - y_lo) / step).astype(int)
        for k in np.unique(idx):
            z[k] = mid[idx == k, 2].max()
    return ys + step / 2, z


def find_sellion(points: np.ndarray, subnasale, left_tragus, right_tragus) -> tuple[np.ndarray | None, float, str | None]:
    """deepest point of the midline profile between nose tip and glabella,
    in the frame the subnasale and tragi define (y up, z forward, origin at
    the subnasale). depth is measured behind the tip-glabella chord, which
    doesn't depend on how far the head is tipped back in that frame.
    returns (point in scan coordinates, nasal root depth in mm, problem)."""
    T = landmark_align(np.array([subnasale, left_tragus, right_tragus]))
    sub = T.apply(np.asarray(subnasale)[None])[0]
    v = T.apply(points) - sub
    ys, z = _front_profile(v)
    ok = ~np.isnan(z)
    zs = z.copy()
    for i in np.nonzero(ok)[0]:
        zs[i] = np.nanmean(z[max(0, i - 1) : i + 2])
    tip_win = ok & (ys >= 0) & (ys <= 25)
    if not tip_win.any():
        return None, 0.0, "no nose tip found"
    tip = np.nonzero(tip_win)[0][np.argmax(zs[tip_win])]
    fh_win = ok & (ys >= ys[tip] + 40) & (ys <= ys[tip] + 50)
    if not fh_win.any():
        return None, 0.0, "no forehead found"
    gl = np.nonzero(fh_win)[0][-1]
    se_win = ok & (ys > ys[tip] + 5) & (ys < ys[gl] - 5)
    if not se_win.any():
        return None, 0.0, "no nasal root found"
    a = np.array([zs[tip], ys[tip]])
    u = np.array([zs[gl], ys[gl]]) - a
    u /= np.linalg.norm(u)
    behind = -((np.stack([zs, ys], axis=1) - a) @ np.array([u[1], -u[0]]))
    cand = np.nonzero(se_win)[0]
    se = cand[np.argmax(behind[cand])]
    guess = np.array([0.0, ys[se], zs[se]]) + sub
    return T.inverse_apply(guess[None])[0], float(behind[se]), None


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def _dense_points(mesh: trimesh.Trimesh) -> np.ndarray:
    """the vertices plus enough surface samples for a gap-free 1 mm relief
    map, whatever the mesh resolution."""
    area = float(mesh.area)
    n = int(np.clip(area * 1.5, 50_000, 600_000))
    samples, _ = sample_surface(mesh, n, seed=2)
    return np.vstack([np.asarray(mesh.vertices, dtype=np.float64), samples])


def _refine(head_pose: HeadPose, guesses: dict, points, vertex_tree, patches):
    """relief-map matching around each guess (head-frame coordinates)."""
    head = head_pose.to_head(points)
    scores: dict[str, float] = {}
    flags: dict[str, str] = {}
    found: dict[str, np.ndarray] = {}
    for name, centre in guesses.items():
        kind = "nose" if name == "subnasale" else "ear"
        axes = _AXES[name]
        img = relief_map(head, centre, axes)
        score, i, j = match_patch(highpass(img), patches[f"{kind}_coarse"], patches[f"{kind}_fine"], warps=kind == "ear")
        scores[name] = score
        height = _surface_height(img, i, j)
        if height is None:
            flags[name] = "no surface at the matched spot"
            height = 0.0
        if score < MIN_SCORE[kind]:
            flags.setdefault(name, "ear not clearly visible" if kind == "ear" else "nose not clearly visible")
        q = np.asarray(centre, dtype=np.float64) + np.array([i - RELIEF_HALF, j - RELIEF_HALF, height]) @ axes
        scan_point = q @ head_pose.rotation.T + head_pose.translation
        found[name] = np.asarray(vertex_tree.data[vertex_tree.query(scan_point)[1]])
    return found, scores, flags


def _sellion(points, vertex_tree, found, fallback, flags, scores):
    sellion, depth, problem = find_sellion(points, found["subnasale"], found["left_tragus"], found["right_tragus"])
    scores["sellion"] = depth
    if sellion is None:
        flags["sellion"] = problem
        sellion = fallback
    elif depth < 2.0:
        flags["sellion"] = "shallow nasal root"
    return np.asarray(vertex_tree.data[vertex_tree.query(sellion)[1]])


def _landmark_frame(sellion, left_tragus, right_tragus, scale: float) -> HeadPose:
    """the head frame the sellion and tragi define (the frame "align" puts a
    scan in) - same orientation as the template frame the pose search uses,
    but it no longer depends on where that search happened to settle."""
    T = landmark_align(np.array([sellion, left_tragus, right_tragus]))
    return HeadPose(T.rotation.T, scale, -T.translation @ T.rotation, 0.0, 0.0)


def detect_landmarks(mesh: trimesh.Trimesh, patches: dict[str, np.ndarray] | None = None) -> AutoLandmarks:
    patches = patches if patches is not None else load_patches()
    pose = find_head_pose(mesh)
    points = _dense_points(mesh)
    vertex_tree = cKDTree(np.asarray(mesh.vertices))

    guesses = {
        "left_tragus": pose.scale * REFERENCE_TRIANGLE[1],
        "right_tragus": pose.scale * REFERENCE_TRIANGLE[2],
        "subnasale": pose.scale * patches["subnasale"],
    }
    found, scores, flags = _refine(pose, guesses, points, vertex_tree, patches)
    sellion = _sellion(points, vertex_tree, found, pose.to_scan(REFERENCE_TRIANGLE[0]), flags, scores)

    # second pass in the frame the first-pass landmarks define: the pose
    # search settles a degree or two differently depending on how the scan
    # was oriented, and that was enough to move a tragus by a few mm
    frame = _landmark_frame(sellion, found["left_tragus"], found["right_tragus"], pose.scale)
    guesses = {name: frame.to_head(p) for name, p in found.items()}
    found, scores, flags = _refine(frame, guesses, points, vertex_tree, patches)
    sellion = _sellion(points, vertex_tree, found, sellion, flags, scores)

    # the tragi of one head sit at nearly the same distance from the
    # sellion; on the benchmark scans a difference over 5 mm meant one of
    # them had latched onto the wrong part of the ear far more often than
    # it reflected a real asymmetry
    lopsided = abs(np.linalg.norm(sellion - found["left_tragus"]) - np.linalg.norm(sellion - found["right_tragus"]))
    if lopsided > MAX_TRAGUS_ASYMMETRY:
        for name in ("left_tragus", "right_tragus"):
            flags.setdefault(name, f"left and right differ by {lopsided:.0f} mm from the sellion")
    if pose.score - pose.runner_up < 0.02:
        flags.setdefault("pose", "head orientation uncertain")
    scores["pose"] = pose.score

    return AutoLandmarks(
        sellion=sellion,
        left_tragus=found["left_tragus"],
        right_tragus=found["right_tragus"],
        subnasale=found["subnasale"],
        scores=scores,
        flags=flags,
    )
