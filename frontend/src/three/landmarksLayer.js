import * as THREE from "three";

function createMarker(radius, color) {
  return new THREE.Mesh(new THREE.SphereGeometry(radius, 16, 16), new THREE.MeshBasicMaterial({ color }));
}

// reconciles the marker objects in markersRef against the given landmarks
// dict - adds missing ones, moves existing ones, removes ones no longer
// present. radius isn't re-applied to an already-existing marker (picking
// order doesn't change mid-session), only used for newly created ones.
export function syncLandmarkMarkers({ sceneBag, markersRef, landmarks, colors, radius }) {
  const markers = markersRef.current;

  for (const name of Object.keys(markers)) {
    if (!(name in landmarks)) {
      sceneBag.scene.remove(markers[name]);
      markers[name].geometry.dispose();
      markers[name].material.dispose();
      delete markers[name];
    }
  }

  for (const [name, point] of Object.entries(landmarks)) {
    if (!markers[name]) {
      const marker = createMarker(radius, colors[name] ?? 0x4ade80);
      sceneBag.scene.add(marker);
      markers[name] = marker;
    }
    markers[name].position.set(point.x, point.y, point.z);
  }
}

export function disposeLandmarkMarkers(markersRef) {
  const markers = markersRef.current;
  for (const name of Object.keys(markers)) {
    markers[name].geometry.dispose();
    markers[name].material.dispose();
    delete markers[name];
  }
}
