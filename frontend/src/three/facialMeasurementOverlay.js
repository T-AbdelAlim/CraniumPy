import * as THREE from "three";

// straight-segment connecting lines for the Facial Anthropometrics
// workspace's own measurements - a Linear measurement draws one open
// segment, Angular draws the two rays from its vertex point, Area draws
// the closed polygon around its boundary points. deliberately straight
// lines even for a geodesic Linear measurement or Area's true enclosed-
// surface computation: this is a lightweight visual indicator of WHICH
// points a measurement connects, not a trace of the exact path/boundary
// the value was actually computed from (see craniumpy_core.facial_measurements
// for that) - same "simple straight indicator, the real math happens
// server-side" spirit as this app's other 3D overlays (e.g. the frontal-
// bossing construction lines).
//
// segments: [{points: [{x,y,z}, ...], color: number, closed: bool}] - one
// entry per measurement, points already in the order point_ids lists them.
export function addFacialMeasurementLines(sceneBag, segments) {
  const group = new THREE.Group();
  for (const segment of segments) {
    if (segment.points.length < 2) continue;
    const vectors = segment.points.map((p) => new THREE.Vector3(p.x, p.y, p.z));
    if (segment.closed) vectors.push(vectors[0].clone());
    const geometry = new THREE.BufferGeometry().setFromPoints(vectors);
    const material = new THREE.LineBasicMaterial({ color: segment.color, depthTest: false, transparent: true });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 999; // always visible on top of the mesh surface, same reasoning landmark markers already use
    group.add(line);
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
