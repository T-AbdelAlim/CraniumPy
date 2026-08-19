import * as THREE from "three";

// N distinctly-colored sphere markers at given 3D points - the Longitudinal
// workspace's "check correspondence" feature (see CorrespondenceTab.jsx),
// which visually confirms that the same vertex INDEX really does land on
// the same anatomical spot across two same-topology meshes: point i gets
// the same color on both meshes it's shown on, so a mismatch (the same
// color landing in two totally different places) is obvious without
// reading any numbers. points is an array of [x, y, z] triples, colors a
// parallel array of hex ints - same length as points, one marker each.
export function addCorrespondenceMarkers({ sceneBag, points, colors, markerRadius }) {
  const group = new THREE.Group();
  points.forEach((p, i) => {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(markerRadius, 16, 16),
      new THREE.MeshBasicMaterial({ color: colors[i % colors.length] }),
    );
    marker.position.set(p[0], p[1], p[2]);
    group.add(marker);
  });
  sceneBag.scene.add(group);
  return group;
}

export function removeCorrespondenceMarkers(sceneBag, group) {
  if (!group) return;
  sceneBag.scene.remove(group);
  group.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
