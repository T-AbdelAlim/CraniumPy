import * as THREE from "three";

// forehead contour + fitted parabola + regions + frontal-angle construction,
// live on the mesh - the Analysis workspace's metopic/frontal-shape
// visualization, sibling to measurementsLayer.js's HC-ring/heatmap overlays.
// everything here lives on the y = slice_height plane (metopic's own 2D
// (x, z) plane lifted into 3D) - see api/schemas.py's MetopicResponse and
// craniumpy_core.metopic's module docstring for the axis convention.

const CONTOUR_COLOR = 0x3a3a3a;
const PARABOLA_COLOR = 0x2563eb;
const CENTRAL_COLOR = 0xd1453d;
const TEMPORAL_COLOR = 0x0891b2;
const FRONTAL_ANGLE_COLOR = 0x16a34a;
const MIDLINE_COLOR = 0x999999;

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

export function addMetopicOverlay({ sceneBag, metopic, markerRadius }) {
  const group = new THREE.Group();
  const y = metopic.slice_height;
  const contour = metopic.contour;

  const contourPoints = contour.map((p) => toVec3(p, y));
  group.add(lineFromPoints(contourPoints, CONTOUR_COLOR));

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
  group.add(lineFromPoints(parabolaPoints, PARABOLA_COLOR, true));

  const zs = contour.map((p) => p.z);
  group.add(
    lineFromPoints(
      [new THREE.Vector3(0, y, Math.min(...zs)), new THREE.Vector3(0, y, Math.max(...zs))],
      MIDLINE_COLOR,
      true
    )
  );

  const centralPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.central_window, y);
  if (centralPts.length > 1) group.add(lineFromPoints(centralPts, CENTRAL_COLOR));
  const leftPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.left_temporal_window, y);
  if (leftPts.length > 1) group.add(lineFromPoints(leftPts, TEMPORAL_COLOR));
  const rightPts = contourSegmentInWindow(contour, metopic.normalized_arc_length, metopic.right_temporal_window, y);
  if (rightPts.length > 1) group.add(lineFromPoints(rightPts, TEMPORAL_COLOR));

  const [M, L, R] = metopic.frontal_angle_points;
  group.add(lineFromPoints([toVec3(L, y), toVec3(M, y), toVec3(R, y)], FRONTAL_ANGLE_COLOR));
  for (const p of [L, R]) {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(markerRadius, 12, 12),
      new THREE.MeshBasicMaterial({ color: FRONTAL_ANGLE_COLOR })
    );
    marker.position.copy(toVec3(p, y));
    group.add(marker);
  }
  const ridgeMarker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius, 12, 12),
    new THREE.MeshBasicMaterial({ color: CENTRAL_COLOR })
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
