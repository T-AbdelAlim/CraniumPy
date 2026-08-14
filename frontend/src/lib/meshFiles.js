export const MESH_EXTENSIONS = ["ply", "obj", "stl"];
export const TEXTURE_EXTENSIONS = ["jpg", "jpeg", "png"];

export function extOf(name) {
  return (name.split(".").pop() || "").toLowerCase();
}

export function hasMeshFile(names) {
  return names.some((n) => MESH_EXTENSIONS.includes(extOf(n)));
}

export function primaryMeshFile(names) {
  return names.find((n) => MESH_EXTENSIONS.includes(extOf(n)));
}

export function hasTextureFile(names) {
  return names.some((n) => TEXTURE_EXTENSIONS.includes(extOf(n)));
}
