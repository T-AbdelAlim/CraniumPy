import * as THREE from "three";

// blue (dented, negative) - white (0) - red (protruded, positive) diverging
// scale, matching results_bundle.py's _asymmetry_figure ("bwr" colormap) so
// the live viewer and the saved figure read the same way. gamma <1 on the
// normalized magnitude pushes moderate deviations toward full saturation
// sooner - pure blue/red at the extremes are already maxed out, it's the
// middle of the range that reads as washed-out near-white without this.
// ported from frontend_legacy/app.js's heatmapColor (the old app's own
// version), which this used to be a plain linear blend of and looked
// noticeably paler than.
function divergingColor(t) {
  let clamped = Math.max(-1, Math.min(1, t));
  clamped = Math.sign(clamped) * Math.abs(clamped) ** 0.6;
  const color = new THREE.Color();
  if (clamped < 0) color.setRGB(1 + clamped, 1 + clamped, 1);
  else color.setRGB(1, 1 - clamped, 1 - clamped);
  return color;
}

// the largest |deviation| in the heatmap - the diverging scale's range is
// always [-maxAbs, +maxAbs]. exported so the scalar-bar legend's min/max
// labels are guaranteed to match what applyHeatmap actually rendered,
// instead of recomputing the same thing separately and risking drift.
export function heatmapMaxAbs(heatmap) {
  return Math.max(...heatmap.map(Math.abs), 1e-6);
}

// white (0) -> --accent-teal (max) sequential scale, for heatmaps that are
// an unsigned MAGNITUDE (e.g. the cohort mean-shape's inter-patient spread
// - how far a point wandered, with no "direction") rather than a signed
// deviation. deliberately NOT the diverging blue-white-red scale below,
// which reads as "which way" as much as "how much" - reusing it for
// magnitude-only data would visually claim a direction that isn't there.
// same gamma<1 shaping as divergingColor, for the same reason (push
// moderate values toward saturation sooner instead of washing out near
// white in the middle of the range).
const SEQUENTIAL_MAX_COLOR = new THREE.Color(0x178c83);
function sequentialColor(t) {
  const clamped = Math.max(0, Math.min(1, t)) ** 0.6;
  return new THREE.Color(1, 1, 1).lerp(SEQUENTIAL_MAX_COLOR, clamped);
}

// the largest value in a non-negative (magnitude) heatmap - the sequential
// scale's range is always [0, max]. same "exported so the scalar-bar
// legend can't drift from what actually got rendered" reasoning as
// heatmapMaxAbs.
export function heatmapMax(heatmap) {
  return Math.max(...heatmap, 1e-6);
}

// shared vertex-color tinting: multiplies whichever material(s) the mesh
// is already showing (textured, plain skin-toned, vertex-colored) by a
// per-vertex color computed from `colorFn(value)`, rather than swapping in
// a separate flat/unlit material - ported from frontend_legacy/app.js's
// applyAsymmetryHeatmap, which did the same multiplicative tint. white is
// the multiplicative identity, so a colorFn that returns white at its
// "neutral" value (0 deviation, 0 spread) passes the mesh's own normal lit
// shading straight through unchanged there - real surface detail stays
// visible under the tinted areas too, instead of going flat.
function tintMesh(meshObject, values, colorFn) {
  meshObject.traverse((child) => {
    if (!child.isMesh) return;
    const count = child.geometry.attributes.position.count;
    const colors = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const c = colorFn(values[i] ?? 0);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    child.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    for (const mat of [child.material, child.userData.texturedMaterial, child.userData.plainMaterial]) {
      if (!mat) continue;
      mat.vertexColors = true;
      mat.needsUpdate = true;
    }
  });
}

// colors vertices by a per-vertex signed heatmap (mm), diverging blue
// (negative/inward) - white (0) - red (positive/outward/protruded) - used
// for both the per-patient asymmetry heatmap (calculate_asymmetry's
// mirrored-half distance) and the cohort mean-shape's reference-template
// diff (see craniumpy_core.cohort.reference_diff). divergingColor(0) is
// pure white; see tintMesh for why that matters for the half
// calculate_asymmetry zeroes out by design (see that function's own
// docstring). heatmap is per-vertex, same order as the mesh's own vertices
// - assumes a single-mesh GLB (mesh_to_glb always produces one), so no
// per-child index offsetting is needed.
//
// maxAbs normally comes from the given heatmap itself (heatmapMaxAbs) - the
// color scale always spans exactly what's being shown. fixedMaxAbs
// overrides that with an explicit value instead, for a caller that redraws
// the SAME diverging scale against a heatmap whose own magnitude changes
// from call to call (see the Longitudinal workspace's morph animation,
// LongitudinalMorphViewer.jsx) - without a fixed reference, a heatmap
// scaled down by some factor would renormalize right back to full
// saturation against its own (now smaller) max, and the color would never
// visibly change at all.
export function applyHeatmap(meshObject, heatmap, fixedMaxAbs) {
  const maxAbs = fixedMaxAbs ?? heatmapMaxAbs(heatmap);
  tintMesh(meshObject, heatmap, (v) => divergingColor(v / maxAbs));
}

// colors vertices by a per-vertex non-negative MAGNITUDE heatmap (mm) - the
// cohort mean-shape's inter-patient spread (see
// craniumpy_core.cohort.mean_shape's variability). uses the sequential
// (not diverging) scale above, deliberately distinct from applyHeatmap's
// red/blue - see sequentialColor's own comment for why.
export function applySequentialHeatmap(meshObject, heatmap) {
  const max = heatmapMax(heatmap);
  tintMesh(meshObject, heatmap, (v) => sequentialColor(v / max));
}

export function removeHeatmap(meshObject) {
  if (!meshObject) return;
  meshObject.traverse((child) => {
    if (!child.isMesh) return;
    for (const mat of [child.material, child.userData.texturedMaterial, child.userData.plainMaterial]) {
      if (!mat) continue;
      mat.vertexColors = false;
      mat.needsUpdate = true;
    }
    child.geometry.deleteAttribute("color");
  });
}

function addSpan(group, a, b, color, markerRadius) {
  const pa = new THREE.Vector3(a.x, a.y, a.z);
  const pb = new THREE.Vector3(b.x, b.y, b.z);
  const geo = new THREE.BufferGeometry().setFromPoints([pa, pb]);
  const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ color, dashSize: 3, gapSize: 2, linewidth: 2 }));
  line.computeLineDistances();
  group.add(line);
  for (const p of [pa, pb]) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(markerRadius, 12, 12), new THREE.MeshBasicMaterial({ color }));
    marker.position.copy(p);
    group.add(marker);
  }
}

// default palette, matching results_bundle.py's _measurement_figure exactly
// - overridable per call (see colors param below) so the Longitudinal
// workspace can draw two timepoints' overlays in two distinct, legend-
// matched palettes in the same viewer without them being indistinguishable.
const DEFAULT_MEASUREMENTS_COLORS = { hc: 0xd1453d, bpd: 0x2563eb, ofd: 0x16a34a };

// the HC-slice ring (closed red loop) plus the BPD (blue) and OFD (green)
// spans with endpoint markers - same visual as
// results_bundle.py's _measurement_figure, live on the mesh instead of a
// static PNG. hcPolygon may be null (a slice plane that missed the mesh -
// see craniumpy_core.craniometrics.hc_slice_polygon), in which case just
// the two spans show. colors optionally overrides the default red/blue/
// green palette (see DEFAULT_MEASUREMENTS_COLORS) - any keys left out fall
// back to their default.
export function addMeasurementsOverlay({ sceneBag, hcPolygon, frontOpt, occOpt, lhOpt, rhOpt, markerRadius, colors }) {
  const c = { ...DEFAULT_MEASUREMENTS_COLORS, ...colors };
  const group = new THREE.Group();

  if (hcPolygon && hcPolygon.length > 2) {
    const points = hcPolygon.map((p) => new THREE.Vector3(p.x, p.y, p.z));
    points.push(points[0].clone());
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: c.hc, linewidth: 2 })));
  }

  addSpan(group, lhOpt, rhOpt, c.bpd, markerRadius); // BPD (breadth)
  addSpan(group, occOpt, frontOpt, c.ofd, markerRadius); // OFD (depth)

  sceneBag.scene.add(group);
  return group;
}

export function removeMeasurementsOverlay(sceneBag, group) {
  if (!group) return;
  sceneBag.scene.remove(group);
  group.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
