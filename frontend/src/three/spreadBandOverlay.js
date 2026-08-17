import * as THREE from "three";

// +/-1 SD ribbon around some mean curve on the mean shape's own surface -
// see craniumpy_core.cohort.SpreadBand (hc_ring_band/metopic_band/
// sagittal_band_to_spread_band all produce this same inner/outer point-pair
// shape, one point of inner matching the same position along the curve as
// the same-index point of outer). built as a triangle strip between the two
// point arrays, so a single geometry path covers the closed HC ring and the
// open metopic/sagittal arcs alike - closed just adds one more segment
// wrapping the last pair of points back to the first.

function buildRibbonGeometry(innerPoints, outerPoints, closed) {
  const n = innerPoints.length;
  const positions = new Float32Array(n * 2 * 3);
  for (let i = 0; i < n; i++) {
    positions.set([innerPoints[i].x, innerPoints[i].y, innerPoints[i].z], i * 6);
    positions.set([outerPoints[i].x, outerPoints[i].y, outerPoints[i].z], i * 6 + 3);
  }
  const segments = closed ? n : n - 1;
  const total = n * 2;
  const indices = [];
  for (let i = 0; i < segments; i++) {
    const a = (i * 2) % total;
    const b = (i * 2 + 1) % total;
    const c = (i * 2 + 2) % total;
    const d = (i * 2 + 3) % total;
    indices.push(a, b, c, b, d, c);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

export function addSpreadBandRibbon(sceneBag, innerPoints, outerPoints, closed, color) {
  const geometry = buildRibbonGeometry(innerPoints, outerPoints, closed);
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.35,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  sceneBag.scene.add(mesh);
  return mesh;
}

export function removeSpreadBandRibbon(sceneBag, mesh) {
  if (!mesh) return;
  sceneBag.scene.remove(mesh);
  mesh.geometry?.dispose();
  mesh.material?.dispose();
}
