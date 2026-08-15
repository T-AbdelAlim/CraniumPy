import * as THREE from "three";

// blue (dented, negative) - white (0) - red (protruded, positive)
// diverging scale, matching results_bundle.py's _asymmetry_figure ("bwr"
// colormap) so the live viewer and the saved figure read the same way.
function divergingColor(t) {
  const clamped = Math.max(-1, Math.min(1, t));
  const color = new THREE.Color();
  if (clamped < 0) color.setRGB(1 + clamped, 1 + clamped, 1);
  else color.setRGB(1, 1 - clamped, 1 - clamped);
  return color;
}

// same beige plainMaterial() (three/meshDisplay.js) uses for an ordinary,
// not-yet-colored mesh - used below for vertices the asymmetry calculation
// zeroed out rather than actually measured (see calculate_asymmetry's own
// docstring: the mirrored half is always set to exactly 0.0, by design, not
// a real "zero asymmetry" reading). coloring those through the diverging
// scale like any other value renders that whole half a flat, stark white,
// which reads as a broken/missing render rather than "not evaluated here" -
// matching the plain-mesh color instead makes that half look like normal,
// untouched geometry, and reserves the diverging colors for the half that
// actually carries data.
const NEUTRAL_COLOR = new THREE.Color(0xe8d9c0);

// the largest |deviation| in the heatmap - the diverging scale's range is
// always [-maxAbs, +maxAbs]. exported so the scalar-bar legend's min/max
// labels are guaranteed to match what applyHeatmap actually rendered,
// instead of recomputing the same thing separately and risking drift.
export function heatmapMaxAbs(heatmap) {
  return Math.max(...heatmap.map(Math.abs), 1e-6);
}

// colors vertices by the per-vertex asymmetry heatmap and swaps in a
// vertex-colored material, returning a handle to pass to removeHeatmap.
// heatmap is per-vertex signed distance (mm), same order as the mesh's own
// vertices (see craniumpy_core.asymmetry.calculate_asymmetry) - assumes a
// single-mesh GLB (mesh_to_glb always produces one), so no per-child index
// offsetting is needed.
export function applyHeatmap(meshObject, heatmap) {
  const maxAbs = heatmapMaxAbs(heatmap);
  const handle = { originals: [] };

  meshObject.traverse((child) => {
    if (!child.isMesh) return;
    const count = child.geometry.attributes.position.count;
    const colors = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const value = heatmap[i] ?? 0;
      const c = value === 0 ? NEUTRAL_COLOR : divergingColor(value / maxAbs);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    child.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    handle.originals.push({ child, material: child.material });
    child.material = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide });
  });

  return handle;
}

export function removeHeatmap(handle) {
  if (!handle) return;
  for (const { child, material } of handle.originals) {
    child.material.dispose();
    child.material = material;
    child.geometry.deleteAttribute("color");
  }
}

function addSpan(group, a, b, color, markerRadius) {
  const pa = new THREE.Vector3(a.x, a.y, a.z);
  const pb = new THREE.Vector3(b.x, b.y, b.z);
  const geo = new THREE.BufferGeometry().setFromPoints([pa, pb]);
  const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ color, dashSize: 3, gapSize: 2 }));
  line.computeLineDistances();
  group.add(line);
  for (const p of [pa, pb]) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(markerRadius, 12, 12), new THREE.MeshBasicMaterial({ color }));
    marker.position.copy(p);
    group.add(marker);
  }
}

// the HC-slice ring (closed red loop) plus the BPD (blue) and OFD (green)
// spans with endpoint markers - same visual as
// results_bundle.py's _measurement_figure, live on the mesh instead of a
// static PNG. hcPolygon may be null (a slice plane that missed the mesh -
// see craniumpy_core.craniometrics.hc_slice_polygon), in which case just
// the two spans show.
export function addMeasurementsOverlay({ sceneBag, hcPolygon, frontOpt, occOpt, lhOpt, rhOpt, markerRadius }) {
  const group = new THREE.Group();

  if (hcPolygon && hcPolygon.length > 2) {
    const points = hcPolygon.map((p) => new THREE.Vector3(p.x, p.y, p.z));
    points.push(points[0].clone());
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xd1453d })));
  }

  addSpan(group, lhOpt, rhOpt, 0x2563eb, markerRadius); // BPD (breadth)
  addSpan(group, occOpt, frontOpt, 0x16a34a, markerRadius); // OFD (depth)

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
