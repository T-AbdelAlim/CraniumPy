import * as THREE from "three";

// per-vertex "nodes" overlay - a THREE.Points sibling per mesh child,
// sharing that child's own geometry (so the dots always sit exactly on
// the mesh's actual vertices) - added as a child of the mesh itself so it
// inherits position/rotation/scale for free. lets a live NICP fit show the
// mesh's actual topology (vertex density, connectivity) converging, not
// just a shaded surface moving - used alongside wireframe (see Viewer.jsx's
// updateNicpPreview).
export function addNodesOverlay(meshObject, color, size) {
  const pointsObjects = [];
  meshObject.traverse((child) => {
    if (!child.isMesh) return;
    const points = new THREE.Points(child.geometry, new THREE.PointsMaterial({ color, size, sizeAttenuation: true }));
    child.add(points);
    pointsObjects.push(points);
  });
  return pointsObjects;
}

export function removeNodesOverlay(pointsObjects) {
  for (const points of pointsObjects ?? []) {
    points.parent?.remove(points);
    // geometry is shared with the mesh child it was added to - not this
    // overlay's to dispose, just its own material.
    points.material.dispose();
  }
}

// re-points each Points object at its mesh sibling's current geometry -
// call after swapping the mesh's own geometry in place (see
// meshDisplay.js's swapGeometryInPlace), since a Points object created
// against the old geometry reference won't follow it being disposed and
// replaced on its own.
export function resyncNodesGeometry(pointsObjects) {
  for (const points of pointsObjects ?? []) {
    if (points.parent) points.geometry = points.parent.geometry;
  }
}
