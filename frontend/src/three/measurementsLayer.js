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

// colors vertices by the per-vertex asymmetry heatmap, tinting whichever
// material(s) the mesh is already showing (textured, plain skin-toned,
// vertex-colored) rather than swapping in a separate flat/unlit material -
// ported from frontend_legacy/app.js's applyAsymmetryHeatmap, which did the
// same multiplicative tint. divergingColor(0) is pure white, the
// multiplicative identity, so the half the asymmetry calculation zeroed out
// by design (see calculate_asymmetry's own docstring - the mirrored half is
// always set to exactly 0.0, not a real "zero asymmetry" reading) passes
// straight through unchanged, still showing the mesh's own normal lit
// shading - no separate "neutral color" placeholder needed the way the
// previous unlit-material version required, and real surface detail
// (creases, folds) stays visible under the tinted half too instead of going
// flat. heatmap is per-vertex signed distance (mm), same order as the
// mesh's own vertices (see craniumpy_core.asymmetry.calculate_asymmetry) -
// assumes a single-mesh GLB (mesh_to_glb always produces one), so no
// per-child index offsetting is needed.
export function applyHeatmap(meshObject, heatmap) {
  const maxAbs = heatmapMaxAbs(heatmap);

  meshObject.traverse((child) => {
    if (!child.isMesh) return;
    const count = child.geometry.attributes.position.count;
    const colors = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const c = divergingColor((heatmap[i] ?? 0) / maxAbs);
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
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xd1453d, linewidth: 2 })));
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
