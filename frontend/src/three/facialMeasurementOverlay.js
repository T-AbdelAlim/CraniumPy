import * as THREE from "three";

// Facial Anthropometrics workspace's own measurement overlay: a connecting
// line that hugs the mesh surface (Linear/Angular), a small arc marking
// which angle is measured (Angular), and a translucent patch of the actual
// enclosed mesh surface (Area) - see api/routers/facial.py's
// _render_geometry for where render_paths/render_faces come from (a real
// geodesic trace/enclosed-face set, computed server-side, not approximated
// here). a straight rawPoints fallback only ever applies when the server
// couldn't trace a path (a disconnected mesh) or for a measurement still
// being defined (no round trip yet) - see FacialWorkspace.jsx.

const AREA_FILL_OPACITY = 0.32;
const ANGLE_ARC_SEGMENTS = 24;
const ANGLE_ARC_RADIUS_FRACTION = 0.22; // of the shorter leg's own length
const ANGLE_ARC_MAX_RADIUS = 14; // mm - keeps the marker legible without dwarfing short legs

function toVector3(p) {
  return new THREE.Vector3(p.x, p.y, p.z);
}

function addLine(group, points, color, closed) {
  if (points.length < 2) return;
  const vectors = points.map(toVector3);
  if (closed) vectors.push(vectors[0].clone());
  const geometry = new THREE.BufferGeometry().setFromPoints(vectors);
  const material = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
  const line = new THREE.Line(geometry, material);
  line.renderOrder = 999; // always visible on top of the mesh surface, same reasoning landmark markers already use
  group.add(line);
}

// a small arc between an Angular measurement's two straight-line legs, at
// its own vertex - a plain "this is the angle being measured" marker, built
// from the three raw landmark positions (rawPoints = [a, vertex, c], the
// same order compute_measurement itself reads them in) using the identical
// straight-vector math angle_degrees uses server-side
// (craniumpy_core.facial_measurements.angle_degrees) - entirely client-side,
// no round trip needed since it only depends on positions already in hand.
function addAngleArc(group, rawPoints, color) {
  if (rawPoints.length < 3) return;
  const [a, vertexPoint, c] = rawPoints;
  const vertex = toVector3(vertexPoint);
  const toA = toVector3(a).sub(vertex);
  const toC = toVector3(c).sub(vertex);
  const lenA = toA.length();
  const lenC = toC.length();
  if (lenA < 1e-6 || lenC < 1e-6) return;
  const dirA = toA.clone().normalize();
  const dirC = toC.clone().normalize();

  let axis = new THREE.Vector3().crossVectors(dirA, dirC);
  if (axis.lengthSq() < 1e-10) {
    // legs are (near-)parallel or anti-parallel - no well-defined rotation
    // plane from the two directions alone; pick any axis orthogonal to dirA.
    const helper = Math.abs(dirA.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
    axis = new THREE.Vector3().crossVectors(dirA, helper);
    if (axis.lengthSq() < 1e-10) return;
  }
  axis.normalize();

  const angle = dirA.angleTo(dirC);
  const radius = Math.min(ANGLE_ARC_MAX_RADIUS, Math.min(lenA, lenC) * ANGLE_ARC_RADIUS_FRACTION);
  const points = [];
  for (let i = 0; i <= ANGLE_ARC_SEGMENTS; i++) {
    const t = (angle * i) / ANGLE_ARC_SEGMENTS;
    const dir = dirA.clone().applyAxisAngle(axis, t);
    points.push(vertex.clone().addScaledVector(dir, radius));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.85 });
  const arc = new THREE.Line(geometry, material);
  arc.renderOrder = 999;
  group.add(arc);
}

// the subtle colored patch of actual mesh surface a Surface Area
// measurement encloses - renderFaces is a flat [{x,y,z}, ...] triangle
// soup, every 3 consecutive points one triangle (see api/routers/facial.py's
// _render_geometry / craniumpy_core.facial_measurements.BoundaryTopology.
// face_indices). polygon-offset so it sits just in front of the otherwise-
// coincident mesh surface without z-fighting; depth-tested (unlike the
// connecting lines above) so it reads as embedded IN the surface, properly
// occluded on the far side of the head the way the mesh itself would be.
function addAreaFill(group, renderFaces, color) {
  if (!renderFaces || renderFaces.length < 3) return;
  const positions = new Float32Array(renderFaces.length * 3);
  renderFaces.forEach((p, i) => {
    positions[i * 3] = p.x;
    positions[i * 3 + 1] = p.y;
    positions[i * 3 + 2] = p.z;
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: AREA_FILL_OPACITY,
    side: THREE.DoubleSide,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 500;
  group.add(mesh);
}

// segments: [{type: "linear"|"angular"|"area", color, rawPoints: [{x,y,z}],
// renderPath?: [{x,y,z}], renderFaces?: [{x,y,z}]}] - one entry per
// measurement (plus, while composing one, a synthetic entry for the
// in-progress pick order). renderPath/renderFaces are the server-computed
// surface trace/enclosed-region triangles; a connecting line prefers them
// over rawPoints whenever present, so it visibly hugs the mesh surface even
// for a Linear measurement whose own computed VALUE is a straight 3D
// distance - only a still-composing measurement (no round trip yet) or one
// whose path genuinely couldn't be traced falls back to a plain straight
// segment between the raw points.
export function addFacialMeasurementLines(sceneBag, segments) {
  const group = new THREE.Group();
  for (const segment of segments) {
    const { type, color, rawPoints, renderPath, renderFaces } = segment;
    if (type === "area") {
      // a server-traced boundary loop is already closed (its first and
      // last vertex coincide - see _closed_geodesic_loop) - only the raw
      // fallback polygon needs an extra segment back to its own start.
      const usingServerLoop = renderPath && renderPath.length >= 3;
      addLine(group, usingServerLoop ? renderPath : rawPoints, color, !usingServerLoop);
      addAreaFill(group, renderFaces, color);
      continue;
    }
    const path = renderPath && renderPath.length >= 2 ? renderPath : rawPoints;
    addLine(group, path, color, false);
    if (type === "angular") addAngleArc(group, rawPoints, color);
  }
  sceneBag.scene.add(group);
  return group;
}

export function removeFacialMeasurementLines(sceneBag, group) {
  if (!group) return;
  sceneBag.scene.remove(group);
  group.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
