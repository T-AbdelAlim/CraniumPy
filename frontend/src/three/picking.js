// pure raycasting helpers - no React, no landmark-naming logic. Viewer
// wires these to DOM events; App decides what a hit point actually means.

export function pointerToNdc(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * 2 - 1,
    y: -((event.clientY - rect.top) / rect.height) * 2 + 1,
  };
}

// first point where the ray hits the given object (recursive), or null.
export function raycastMesh(raycaster, camera, ndc, object) {
  if (!object) return null;
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObject(object, true);
  return hits.length > 0 ? hits[0].point : null;
}

// which named marker (if any) the ray hits first - used by alt-drag's
// mousedown to figure out which landmark just got grabbed.
export function raycastMarkers(raycaster, camera, ndc, markersByName) {
  const names = Object.keys(markersByName);
  if (names.length === 0) return null;
  const objects = names.map((n) => markersByName[n]);
  // a marker's matrixWorld only refreshes on the next render() tick, which
  // hasn't necessarily happened yet if it was just placed/moved - raycasting
  // against a stale (identity) matrixWorld makes every hit test miss.
  objects.forEach((m) => m.updateMatrixWorld(true));
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects(objects, false);
  if (hits.length === 0) return null;
  return names.find((n) => markersByName[n] === hits[0].object) ?? null;
}
