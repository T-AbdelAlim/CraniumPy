import * as THREE from "three";

// forehead-bulge angle, live on the mesh - the Analysis workspace's frontal
// bossing visualization, sibling to measurementsLayer.js/metopicOverlay.js.
// unlike those two (mutually exclusive - HC/BPD/OFD only ever shows for
// cranial, heatmap/metopic only for facial), this one is computed for BOTH
// targets and shows alongside whichever of those is currently on screen -
// see App.jsx's analysis overlay effect and
// craniumpy_core.craniometrics.frontal_bossing.

const PROFILE_COLOR = 0x999999;
const ANGLE_COLOR = 0xea580c;
const REFERENCE_COLOR = 0xb0b0b0;

function toVec3(p) {
  return new THREE.Vector3(p.x, p.y, p.z);
}

export function addFrontalBossingOverlay({ sceneBag, frontalBossing, markerRadius }) {
  const group = new THREE.Group();
  const sellion = toVec3(frontalBossing.sellion);
  const frontalPoint = toVec3(frontalBossing.frontal_point);

  if (frontalBossing.profile && frontalBossing.profile.length > 1) {
    const profilePoints = frontalBossing.profile.map(toVec3);
    const geo = new THREE.BufferGeometry().setFromPoints(profilePoints);
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: PROFILE_COLOR, linewidth: 1 })));
  }

  // the horizontal reference the angle was measured against, drawn from
  // sellion along frontalBossing.horizontal - the sellion-tragus plane's own
  // depth axis, which is NOT this frame's +z whenever a 4th (alt frontal)
  // landmark rotated the displayed frame. taking +z here instead would draw
  // a wedge that visibly disagrees with the reported angle on any 4-landmark
  // run. same length as the sellion -> frontal point vector, so both read at
  // a comparable scale regardless of how bulged/receding the forehead is.
  const horizontalLength = sellion.distanceTo(frontalPoint);
  const horizontalDir = frontalBossing.horizontal
    ? toVec3(frontalBossing.horizontal).normalize()
    : new THREE.Vector3(0, 0, 1);
  const horizontalEnd = sellion.clone().add(horizontalDir.multiplyScalar(horizontalLength));
  const refGeo = new THREE.BufferGeometry().setFromPoints([sellion, horizontalEnd]);
  const refLine = new THREE.Line(
    refGeo,
    new THREE.LineDashedMaterial({ color: REFERENCE_COLOR, dashSize: 3, gapSize: 2, linewidth: 1 })
  );
  refLine.computeLineDistances();
  group.add(refLine);

  const angleGeo = new THREE.BufferGeometry().setFromPoints([sellion, frontalPoint]);
  group.add(new THREE.Line(angleGeo, new THREE.LineBasicMaterial({ color: ANGLE_COLOR, linewidth: 2 })));

  for (const p of [sellion, frontalPoint]) {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(markerRadius, 12, 12),
      new THREE.MeshBasicMaterial({ color: ANGLE_COLOR })
    );
    marker.position.copy(p);
    group.add(marker);
  }

  sceneBag.scene.add(group);
  return group;
}

export function removeFrontalBossingOverlay(sceneBag, group) {
  if (!group) return;
  sceneBag.scene.remove(group);
  group.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
