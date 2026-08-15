import * as THREE from "three";

export function loadGlb(gltfLoader, url) {
  return new Promise((resolve, reject) => {
    gltfLoader.load(url, (gltf) => resolve(gltf.scene), undefined, reject);
  });
}

export function plainMaterial() {
  return new THREE.MeshStandardMaterial({ color: 0xe8d9c0, side: THREE.DoubleSide, roughness: 0.85, metalness: 0.0 });
}

// disposes an object's geometries/materials/textures - used both when
// swapping in a new mesh and when the Viewer unmounts. materials stashed on
// userData (texturedMaterial/plainMaterial, see displayMesh below) aren't
// necessarily the ones currently assigned to child.material, so they're
// disposed explicitly too rather than relying on traversal alone.
export function disposeMesh(object3D) {
  if (!object3D) return;
  object3D.traverse((child) => {
    if (!child.isMesh) return;
    child.geometry?.dispose();
    for (const mat of [child.material, child.userData.texturedMaterial, child.userData.plainMaterial]) {
      if (!mat) continue;
      mat.map?.dispose();
      mat.dispose();
    }
  });
}

// the central mesh-swap: loads a GLB, decides per-child material (unlit for
// a real texture or per-vertex color - both already have real-world
// lighting baked in, so running them through the scene's directional
// lights on top just adds a second, wrong light source; lit MeshStandard
// otherwise), stashes both texture/plain variants on userData so the
// texture toggle can swap between them without reloading, and reframes the
// camera. returns whether the loaded mesh actually has a usable texture.
export async function displayMesh({ sceneBag, gltfLoader, meshStateRef, url, selectionHasTexture }) {
  if (meshStateRef.current.object) {
    sceneBag.scene.remove(meshStateRef.current.object);
    disposeMesh(meshStateRef.current.object);
  }

  const object = await loadGlb(gltfLoader, url);
  const materials = [];
  let hasTexture = false;

  object.traverse((child) => {
    if (!child.isMesh) return;

    // recompute normals ourselves regardless of what the GLB has - a
    // missing/empty NORMAL attribute is what makes a PBR material render
    // solid black
    child.geometry.computeVertexNormals();

    // gated on selectionHasTexture too, not just material.map - a lone
    // .obj that internally references an .mtl/texture by filename still
    // gets one of those from trimesh even when that file was never
    // selected (trimesh quietly falls back to a blank placeholder image
    // instead of erroring) - so without this the texture toggle would
    // unlock itself over a meaningless placeholder.
    const childHasTexture = selectionHasTexture && !!(child.material && child.material.map);
    const hasVertexColors = !!child.geometry.attributes.color;

    if (childHasTexture || hasVertexColors) {
      hasTexture = true;
      child.userData.texturedMaterial = childHasTexture
        ? new THREE.MeshBasicMaterial({ map: child.material.map, side: THREE.DoubleSide })
        : new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide });
      child.userData.plainMaterial = plainMaterial();
      child.material = child.userData.texturedMaterial;
    } else {
      child.material = plainMaterial();
    }
    materials.push(child.material);
  });

  sceneBag.scene.add(object);
  const maxDim = sceneBag.fitCameraToObject(object);
  // landmark/measurement marker size scales with the mesh instead of being
  // a fixed radius, so it stays sensibly proportioned whether the mesh is
  // a small scan or a much larger one.
  meshStateRef.current = { object, materials, markerRadius: maxDim * 0.0038 };

  return { hasTexture };
}

// swaps in a new geometry on targetObject's mesh children, in place -
// leaves targetObject's own materials/transform untouched, unlike
// displayMesh which always resets both. used for anything that needs to
// show a mesh's shape changing over time without the jump-cut a fresh
// displayMesh call would cause (camera reframe, material flicker) on every
// update - assumes newObject's mesh children line up 1:1, in order, with
// targetObject's (true for every caller today: a live NICP preview always
// has the same topology as whatever it's updating).
function swapGeometryInPlace(targetObject, newObject) {
  const newGeometries = [];
  newObject.traverse((child) => {
    if (child.isMesh) newGeometries.push(child.geometry);
  });

  let i = 0;
  targetObject.traverse((child) => {
    if (!child.isMesh) return;
    const newGeometry = newGeometries[i++];
    if (!newGeometry) return;
    newGeometry.computeVertexNormals();
    child.geometry.dispose();
    child.geometry = newGeometry;
  });

  // the freshly-loaded object's own materials are never used (this call
  // only ever swaps geometry) - dispose them; the geometries they came
  // with were just adopted by targetObject's children above, so those are
  // left alone.
  newObject.traverse((child) => {
    if (!child.isMesh) return;
    child.material?.dispose();
  });
}

// in-place swap against an arbitrary standalone object - used for the NICP
// live-preview overlay (see Viewer.jsx's updateNicpPreview), which needs to
// update its own geometry every poll tick while the main displayed mesh
// (the patient, fixed) stays completely untouched underneath it.
export async function updateObjectGeometry({ gltfLoader, targetObject, url }) {
  const newObject = await loadGlb(gltfLoader, url);
  swapGeometryInPlace(targetObject, newObject);
}

export function applyWireframeState(meshStateRef, on) {
  for (const m of meshStateRef.current.materials) m.wireframe = on;
}

// dims the mesh a bit so a measurement line/HC ring running along the far
// side of the surface (from the current camera angle) doesn't just vanish
// into it - same fixed 0.75 the old app used while a measurements overlay
// was showing, reset to 1.0 (fully opaque, the normal state) otherwise. no
// user-facing slider, same as before - just tied to whether an overlay is
// currently on (see Viewer.jsx's showMeasurementsOverlay/showHeatmap).
export function applyOpacityState(meshStateRef, opacity) {
  for (const m of meshStateRef.current.materials) {
    m.transparent = opacity < 1;
    m.opacity = opacity;
    m.needsUpdate = true;
  }
}

// swaps in the textured or plain material per showTexture - shared shape
// with applyWireframeState/displayMesh: mutate the ref's materials list to
// match what's actually assigned, since texture toggling changes which
// material each mesh child points at.
export function applyTextureState(meshStateRef, showTexture) {
  const { object } = meshStateRef.current;
  if (!object) return;
  const materials = [];
  object.traverse((child) => {
    if (!child.isMesh || !child.userData.texturedMaterial) return;
    child.material = showTexture ? child.userData.texturedMaterial : child.userData.plainMaterial;
  });
  object.traverse((child) => {
    if (child.isMesh) materials.push(child.material);
  });
  meshStateRef.current.materials = materials;
}
