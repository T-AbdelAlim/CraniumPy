import * as THREE from "three";

// Facial Anthropometrics workspace's own measurement overlay: a connecting
// line - a smoothed surface trace for a geodesic Linear measurement or an
// Area boundary, a plain straight segment for everything else (straight
// Linear, Angular's legs) - a small arc marking which angle is measured
// (Angular), and a translucent patch of the actual enclosed mesh surface
// (Area). see api/routers/facial.py's _render_geometry for where
// render_paths/render_faces come from (server-computed, not approximated
// here) and for which measurement types actually get one - a straight
// rawPoints line is drawn whenever there's no render_path at all, which is
// the CORRECT rendering for straight Linear/Angular (matching what's
// literally being measured), not just a fallback for when the server
// couldn't trace one (a disconnected mesh) or a measurement still being
// defined (no round trip yet) - see FacialWorkspace.jsx.

const AREA_FILL_OPACITY = 0.32;
const ANGLE_ARC_SEGMENTS = 24;
const ANGLE_ARC_RADIUS_FRACTION = 0.22; // of the shorter leg's own length
const ANGLE_ARC_MAX_RADIUS = 14; // mm - keeps the marker legible without dwarfing short legs

function toVector3(p) {
  return new THREE.Vector3(p.x, p.y, p.z);
}

// how many sampled points per input vertex the smoothed curve gets -
// generous enough that the curve reads as genuinely smooth rather than a
// slightly-softened zigzag, without generating a huge geometry for what's
// still just a thin line.
const SMOOTH_SAMPLES_PER_POINT = 6;
const SMOOTH_SAMPLES_MIN = 24;

// smooth=true draws a Catmull-Rom spline THROUGH the given points instead
// of straight segments between them - only meaningful (and only ever
// passed) for a real server-traced geodesic path (see this file's own
// addFacialMeasurementLines), whose raw vertex-to-vertex route can zigzag
// sharply since "shortest path along the mesh's edge graph" has no reason
// to also be the visually smoothest route across the surface - a Dijkstra
// shortest path hops between whichever adjacent vertices are cheapest,
// same as any other shortest-path-over-a-graph result. splining through
// those exact points keeps the curve anchored to the real traced route
// while reading as smooth as the surface itself, matching every other
// straight (non-traced) connector's own clean look. never applied to a
// plain 2-point straight fallback - nothing to smooth there.
function addLine(group, points, color, closed, smooth = false) {
  if (points.length < 2) return;
  let vectors = points.map(toVector3);
  if (smooth && vectors.length >= 3) {
    const curve = new THREE.CatmullRomCurve3(vectors, closed, "catmullrom", 0.5);
    const samples = Math.max(SMOOTH_SAMPLES_MIN, vectors.length * SMOOTH_SAMPLES_PER_POINT);
    vectors = curve.getPoints(samples);
  } else if (closed) {
    vectors.push(vectors[0].clone());
  }
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
      // last vertex coincide - see _closed_geodesic_loop) - the smoothing
      // curve gets its own `closed` flag instead so it wraps smoothly
      // through the seam rather than treating the duplicated start/end
      // vertex as a sharp corner; only the raw fallback polygon needs an
      // extra segment manually pushed to close it.
      const usingServerLoop = renderPath && renderPath.length >= 3;
      addLine(group, usingServerLoop ? renderPath : rawPoints, color, !usingServerLoop, usingServerLoop);
      addAreaFill(group, renderFaces, color);
      continue;
    }
    // renderPath only exists for a geodesic Linear measurement (see
    // api/routers/facial.py's _render_geometry) - straight Linear and
    // Angular (no surface-path toggle at all) always fall back to
    // rawPoints, a plain straight connector, which is exactly what should
    // be drawn for them.
    const usingServerPath = renderPath && renderPath.length >= 2;
    addLine(group, usingServerPath ? renderPath : rawPoints, color, false, usingServerPath);
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
