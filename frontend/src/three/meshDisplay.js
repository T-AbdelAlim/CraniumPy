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

export function applyWireframeState(meshStateRef, on) {
  for (const m of meshStateRef.current.materials) m.wireframe = on;
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
