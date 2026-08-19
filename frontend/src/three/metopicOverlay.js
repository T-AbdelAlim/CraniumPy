import * as THREE from "three";

// forehead contour + fitted parabola + regions + frontal-angle construction,
// live on the mesh - the Analysis workspace's metopic/frontal-shape
// visualization, sibling to measurementsLayer.js's HC-ring/heatmap overlays.
// everything here lives on the y = slice_height plane (metopic's own 2D
// (x, z) plane lifted into 3D) - see api/schemas.py's MetopicResponse and
// craniumpy_core.metopic's module docstring for the axis convention.

// default palette - overridable per call (see addMetopicOverlay's colors
// param) so the Longitudinal workspace can draw two timepoints' contours in
// two distinct, legend-matched palettes in the same viewer.
const DEFAULT_METOPIC_COLORS = {
  contour: 0x3a3a3a,
  parabola: 0x2563eb,
  central: 0xd1453d,
  temporal: 0x0891b2,
  frontalAngle: 0x16a34a,
  midline: 0x999999,
};

function toVec3(point2d, y) {
  return new THREE.Vector3(point2d.x, y, point2d.z);
}

function lineFromPoints(points, color, dashed = false) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 3, gapSize: 2, linewidth: 2 })
    : new THREE.LineBasicMaterial({ color, linewidth: 2 });
  const line = new THREE.Line(geometry, material);
  if (dashed) line.computeLineDistances();
  return line;
}

function contourSegmentInWindow(contour, normalizedArcLength, [start, end], y) {
  const points = [];
  for (let i = 0; i < contour.length; i++) {
    const u = normalizedArcLength[i];
    if (u >= start && u <= end) points.push(toVec3(contour[i], y));
  }
  return points;
}

export function addMetopicOverlay({ sceneBag, metopic, markerRadius, colors }) {
  const c = { ...DEFAULT_METOPIC_COLORS, ...colors };
  const group = new THREE.Group();
  const y = metopic.slice_height;
  const contour = metopic.contour;

  const contourPoints = contour.map((p) => toVec3(p, y));
  group.add(lineFromPoints(contourPoints, c.contour));

  const xs = contour.map((p) => p.x);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const parabolaPoints = [];
  const steps = 60;
  for (let i = 0; i <= steps; i++) {
    const x = xMin + ((xMax - xMin) * i) / steps;
    const z = metopic.parabola_a * x * x + metopic.parabola_c;
    parabolaPoints.push(new THREE.Vector3(x, y, z));
  }
  group.add(lineFromPoints(parabolaPoints, c.parabola, true));

  const zs = contour.map((p) => p.z);
  group.add(
    lineFromPoints(
      [new THREE.Vector3(0, y, Math.min(...zs)), new THREE.Vector3(0, y, Math.max(...zs))],
      c.midline,
      true
    )
  );

  const centralPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.central_window, y);
  if (centralPts.length > 1) group.add(lineFromPoints(centralPts, c.central));
  const leftPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.left_temporal_window, y);
  if (leftPts.length > 1) group.add(lineFromPoints(leftPts, c.temporal));
  const rightPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.right_temporal_window, y);
  if (rightPts.length > 1) group.add(lineFromPoints(rightPts, c.temporal));

  const [M, L, R] = metopic.frontal_angle_points;
  group.add(lineFromPoints([toVec3(L, y), toVec3(M, y), toVec3(R, y)], c.frontalAngle));
  for (const p of [L, R]) {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(markerRadius, 12, 12),
      new THREE.MeshBasicMaterial({ color: c.frontalAngle })
    );
    marker.position.copy(toVec3(p, y));
    group.add(marker);
  }
  const ridgeMarker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius, 12, 12),
    new THREE.MeshBasicMaterial({ color: c.central })
  );
  ridgeMarker.position.copy(toVec3(M, y));
  group.add(ridgeMarker);

  sceneBag.scene.add(group);
  return group;
}

export function removeMetopicOverlay(sceneBag, group) {
  if (!group) return;
  sceneBag.scene.remove(group);
  group.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
