// craniumpy frontend. plain JS, no build step - see DEPENDENCIES.md for why.

import * as THREE from "three";
import { OrbitControls } from "./vendor/three/controls/OrbitControls.js";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

// --- scene setup ---

const canvas = document.getElementById("viewer");
const container = document.getElementById("viewer-container");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14161a);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.localClippingEnabled = true; // needed for the manual clip-plane live preview
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

// three lights from different angles, each fairly dim, instead of one strong
// one - a single directional light was crushing whichever side faced away
// from it into near-black, which made it hard to see the mesh well enough
// to place landmarks accurately on that side.
scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2e37, 1.3));
const keyLight = new THREE.DirectionalLight(0xffffff, 0.55);
keyLight.position.set(1, 1, 1);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
fillLight.position.set(-1, 0.5, -1);
scene.add(fillLight);
const rimLight = new THREE.DirectionalLight(0xffffff, 0.3);
rimLight.position.set(0, -1, 1);
scene.add(rimLight);

function resize() {
  const w = container.clientWidth;
  const h = container.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

(function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
})();

function fitCameraToObject(object) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 1);
  const distance = maxDim * 1.8;
  camera.position.set(center.x, center.y, center.z + distance);
  camera.near = distance / 100;
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
  return maxDim;
}

// --- mesh loading ---

const gltfLoader = new GLTFLoader();
let currentMeshObject = null;
let currentMeshMaterials = [];
let currentMeshHasTexture = false;
let markerRadius = 2;
let lineRadius = 1;

// whether the current session's file selection actually included a texture
// image, set once at upload/open time (see uploadFiles/openFilesFromPaths
// below) - deliberately separate from currentMeshHasTexture, which just
// reflects whether the loaded GLB happens to carry a material.map. a lone
// .obj that internally references an .mtl/texture by filename still gets
// one of those from trimesh even when you never picked that file: trimesh
// quietly falls back to a blank placeholder image instead of erroring (see
// api/routers/mesh.py's upload_mesh docstring) - so without this, the
// texture toggle would unlock itself and the mesh would render with that
// meaningless placeholder, even though nothing you picked had a texture in
// it.
let selectionHasTexture = false;

function loadGlb(url) {
  return new Promise((resolve, reject) => {
    gltfLoader.load(url, (gltf) => resolve(gltf.scene), undefined, reject);
  });
}

function plainMaterial() {
  return new THREE.MeshStandardMaterial({ color: 0xe8d9c0, side: THREE.DoubleSide, roughness: 0.85, metalness: 0.0 });
}

async function displayMesh(url) {
  if (currentMeshObject) {
    scene.remove(currentMeshObject);
    currentMeshObject = null;
  }
  clearMarkers();
  clearTemplateOverlay();
  drawHcLine(null);
  clearBpdOfdLines();
  hideMeasurementsPanel();
  hideScalarBar(); // same reasoning as drawHcLine(null) below - reset stale
  // state from a previous *facial* result before a fresh mesh (or a
  // cranial result, which never calls applyAsymmetryHeatmap) shows up
  currentMeshMaterials = [];
  currentMeshHasTexture = false;

  const object = await loadGlb(url);
  object.traverse((child) => {
    if (!child.isMesh) return;

    // recompute normals ourselves regardless of what the GLB has - a
    // missing/empty NORMAL attribute is what makes a PBR material render
    // solid black
    child.geometry.computeVertexNormals();

    // gated on selectionHasTexture too, not just material.map - see that
    // variable's comment for why a mesh can have a map that isn't real
    const hasTexture = selectionHasTexture && !!(child.material && child.material.map);
    const hasVertexColors = !!child.geometry.attributes.color;

    if (hasTexture) {
      // unlit on purpose - a photo texture already has real-world lighting
      // baked into its pixels, so running it through the scene's directional
      // light on top just adds a second, wrong light source, crushing one
      // side of the face into shadow and making it hard to see where you're
      // actually clicking for landmarks.
      currentMeshHasTexture = true;
      child.userData.texturedMaterial = new THREE.MeshBasicMaterial({ map: child.material.map, side: THREE.DoubleSide });
      child.userData.plainMaterial = plainMaterial();
      child.material = child.userData.texturedMaterial;
    } else if (hasVertexColors) {
      child.material = new THREE.MeshStandardMaterial({
        vertexColors: true, side: THREE.DoubleSide, roughness: 0.85, metalness: 0.0,
      });
    } else {
      child.material = plainMaterial();
    }
    currentMeshMaterials.push(child.material);
  });
  scene.add(object);
  currentMeshObject = object;
  markerRadius = fitCameraToObject(object) * 0.00765; // 10% smaller again - was 0.0085
  lineRadius = markerRadius * 0.35 * 1.3; // 30% thicker than the plain-tube baseline

  document.getElementById("mesh-view-toggles").classList.remove("hidden");
  document.getElementById("wireframe-toggle").checked = false;
  const textureToggle = document.getElementById("texture-toggle");
  textureToggle.disabled = !currentMeshHasTexture;
  textureToggle.checked = currentMeshHasTexture;
  applyWireframeState();

  return object;
}

function applyWireframeState() {
  const on = document.getElementById("wireframe-toggle").checked;
  for (const m of currentMeshMaterials) m.wireframe = on;
}

document.getElementById("wireframe-toggle").addEventListener("change", applyWireframeState);

document.getElementById("texture-toggle").addEventListener("change", (event) => {
  if (!currentMeshObject) return;
  const showTexture = event.target.checked;
  currentMeshMaterials = [];
  currentMeshObject.traverse((child) => {
    if (!child.isMesh || !child.userData.texturedMaterial) return;
    child.material = showTexture ? child.userData.texturedMaterial : child.userData.plainMaterial;
  });
  currentMeshObject.traverse((child) => {
    if (child.isMesh) currentMeshMaterials.push(child.material);
  });
  applyWireframeState();
});

// --- landmark markers ---
// green, draggable via alt+drag, tracked by name so a drag can look up and
// move the right one. cleared once the result mesh is shown - see
// displayResultMesh.

let landmarkMarkerObjects = {};

function clearLandmarkMarkers() {
  for (const name of Object.keys(landmarkMarkerObjects)) {
    scene.remove(landmarkMarkerObjects[name]);
  }
  landmarkMarkerObjects = {};
}

function clearMarkers() {
  clearLandmarkMarkers();
}

function addLandmarkMarker(name, point) {
  if (landmarkMarkerObjects[name]) scene.remove(landmarkMarkerObjects[name]);
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius, 16, 16),
    new THREE.MeshBasicMaterial({ color: LANDMARK_COLORS[name] ?? 0x4ade80 })
  );
  marker.position.set(point.x, point.y, point.z);
  scene.add(marker);
  landmarkMarkerObjects[name] = marker;
  return marker;
}

// measurement lines (HC ring + BPD/OFD spans) as actual tube geometry, not
// THREE.Line - LineBasicMaterial's linewidth is a screen-space pixel count
// that most WebGL backends just ignore and always render at 1px, so it's
// not a real way to make a line look thicker. a tube has genuine 3D
// thickness that scales with the mesh like everything else in the scene.
function makeTube(points, radius, color, closed) {
  const curve = new THREE.CatmullRomCurve3(points, closed, "catmullrom", 0.0);
  const tubularSegments = Math.max(8, points.length * 4);
  const geometry = new THREE.TubeGeometry(curve, tubularSegments, radius, 8, closed);
  return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color }));
}

let hcLineObject = null;

function drawHcLine(polygonPoints) {
  if (hcLineObject) {
    scene.remove(hcLineObject);
    hcLineObject = null;
  }
  if (!polygonPoints || polygonPoints.length < 3) return;
  const pts = polygonPoints.map((p) => new THREE.Vector3(p.x, p.y, p.z));
  hcLineObject = makeTube(pts, lineRadius, 0xd1453d, true);
  scene.add(hcLineObject);
}

let bpdOfdLineObjects = [];

function clearBpdOfdLines() {
  for (const obj of bpdOfdLineObjects) scene.remove(obj);
  bpdOfdLineObjects = [];
}

// BPD (breadth, left<->right optima) in blue, OFD (depth, front<->occiput
// optima) in green - same colors as the saved 2D figure (see
// api/results_bundle.py's _measurement_figure) so the live view and the
// downloaded one read the same way.
function drawBpdOfdLines(frontOpt, occOpt, lhOpt, rhOpt) {
  clearBpdOfdLines();
  if (!frontOpt || !occOpt || !lhOpt || !rhOpt) return;
  const bpd = makeTube(
    [new THREE.Vector3(lhOpt.x, lhOpt.y, lhOpt.z), new THREE.Vector3(rhOpt.x, rhOpt.y, rhOpt.z)],
    lineRadius, 0x2563eb, false
  );
  const ofd = makeTube(
    [new THREE.Vector3(frontOpt.x, frontOpt.y, frontOpt.z), new THREE.Vector3(occOpt.x, occOpt.y, occOpt.z)],
    lineRadius, 0x16a34a, false
  );
  bpdOfdLineObjects = [bpd, ofd];
  scene.add(bpd, ofd);
}

function hideMeasurementsPanel() {
  document.getElementById("measurements-panel").classList.add("hidden");
}

function showMeasurementsPanel(c) {
  document.getElementById("mp-hc").textContent = `${c.circumference_cm} cm`;
  document.getElementById("mp-bpd").textContent = `${c.breadth_mm} mm`;
  document.getElementById("mp-ofd").textContent = `${c.depth_mm} mm`;
  document.getElementById("mp-ci").textContent = c.cephalic_index;
  document.getElementById("mp-volume").textContent = `${c.mesh_volume_cc} cc`;
  document.getElementById("measurements-panel").classList.remove("hidden");
}

// dims the mesh a bit while measurement lines are showing, so a line
// running along the far side (behind the surface, from this angle) doesn't
// just disappear into it - full opacity (1.0) is the normal/default state.
function setMeshOpacity(opacity) {
  for (const mat of currentMeshMaterials) {
    mat.transparent = opacity < 1;
    mat.opacity = opacity;
    mat.needsUpdate = true;
  }
}

function enableMeasurementsVisualization() {
  if (!lastResultsData || !lastResultsData.craniometrics) return;
  const c = lastResultsData.craniometrics;
  drawHcLine(c.hc_slice_polygon);
  drawBpdOfdLines(c.front_opt, c.occ_opt, c.lh_opt, c.rh_opt);
  setMeshOpacity(0.75);
  showMeasurementsPanel(c);
}

function disableMeasurementsVisualization() {
  drawHcLine(null);
  clearBpdOfdLines();
  setMeshOpacity(1.0);
  hideMeasurementsPanel();
}

function enableAsymmetryVisualization() {
  if (!lastResultsData || !lastResultsData.asymmetry) return;
  applyAsymmetryHeatmap(lastResultsData.asymmetry.heatmap);
}

// undoes applyAsymmetryHeatmap's material tint - vertexColors=false leaves
// the color attribute sitting on the geometry unused, cheaper than
// reloading the mesh fresh just to drop it.
function disableAsymmetryVisualization() {
  hideScalarBar();
  if (!currentMeshObject) return;
  currentMeshObject.traverse((child) => {
    if (!child.isMesh) return;
    for (const mat of [child.material, child.userData.texturedMaterial, child.userData.plainMaterial]) {
      if (!mat) continue;
      mat.vertexColors = false;
      mat.needsUpdate = true;
    }
  });
}

// facial asymmetry heatmap: one signed distance (mm) per vertex of the
// result mesh, zeroed out on one half by design (see
// craniumpy_core.asymmetry's module docstring) - negative means that point
// sits closer to center than its mirrored counterpart (a dent), positive
// means it sticks out further (protruded). blue/white/red diverging so 0 is
// neutral, scaled to whatever the biggest deviation in this mesh actually
// is rather than a fixed mm range, since a mild case and a severe one
// shouldn't both max out or both wash out the same way.
function heatmapColor(value, maxAbs) {
  let t = maxAbs > 0 ? Math.max(-1, Math.min(1, value / maxAbs)) : 0;
  // pure blue/red at the extremes are already fully saturated - it's the
  // middle of the range that reads as washed-out near-white. a gamma <1
  // pushes moderate deviations toward full color sooner, so more of the
  // heatmap actually looks colored instead of pale.
  t = Math.sign(t) * Math.abs(t) ** 0.6;
  if (t < 0) {
    const k = 1 + t;
    return new THREE.Color(k, k, 1);
  }
  const k = 1 - t;
  return new THREE.Color(1, k, k);
}

function updateScalarBar(maxAbs) {
  document.getElementById("scalar-bar-max").textContent = `+${maxAbs.toFixed(1)} mm`;
  document.getElementById("scalar-bar-min").textContent = `-${maxAbs.toFixed(1)} mm`;
  document.getElementById("heatmap-scalar-bar").classList.remove("hidden");
}

function hideScalarBar() {
  document.getElementById("heatmap-scalar-bar").classList.add("hidden");
}

function applyAsymmetryHeatmap(heatmapValues) {
  if (!currentMeshObject || !heatmapValues || heatmapValues.length === 0) return;
  const maxAbs = heatmapValues.reduce((m, v) => Math.max(m, Math.abs(v)), 1e-6);
  updateScalarBar(maxAbs);

  currentMeshObject.traverse((child) => {
    if (!child.isMesh) return;
    const count = child.geometry.attributes.position.count;
    const colors = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const c = heatmapColor(heatmapValues[i] ?? 0, maxAbs);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    child.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    // tint multiplicatively on top of whatever material this mesh is
    // already showing (texture, its own vertex colors, or the plain skin
    // tone) instead of replacing the material outright - heatmapColor()
    // returns white at 0, so vertices with no asymmetry data (the
    // mirrored-out half, zeroed by design) pass straight through
    // unchanged, and only the half with real data gets tinted red/blue.
    // swapping in a flat unlit vertex-colored material for the whole mesh
    // instead would show the data fine but flatten the zeroed half into a
    // featureless white blob with no surface detail.
    for (const mat of [child.material, child.userData.texturedMaterial, child.userData.plainMaterial]) {
      if (!mat) continue;
      mat.vertexColors = true;
      mat.needsUpdate = true;
    }
  });
  applyWireframeState();
}

// --- landmark picking (ctrl/cmd + click) ---

const LANDMARK_NAMES = ["sellion", "left_tragus", "right_tragus"];
// optional 4th point (cranium target only, see the "use a secondary frontal
// landmark" checkbox) - an alternate anchor (e.g. subnasale) that takes over
// the registration/clip/display frame while sellion above stays mandatory and
// keeps driving the actual measurements. see pipeline.analyze_cranial for
// why these are two different knobs, not one.
const ALT_FRONTAL_NAME = "alt_frontal";
// distinct colors so the marker in the 3D view and its row in the sidebar
// list (see the matching CSS in style.css) are unambiguously the same point -
// picking order alone wasn't enough once the labels went generic (frontal/
// left/right landmark instead of sellion/tragus).
const LANDMARK_COLORS = { sellion: 0x1a4922, left_tragus: 0xa65c3c, right_tragus: 0xd4af37, alt_frontal: 0x2a4d80 };
const pickedLandmarks = {};
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

let useAltFrontal = false;

function activeLandmarkNames() {
  return useAltFrontal ? [...LANDMARK_NAMES, ALT_FRONTAL_NAME] : LANDMARK_NAMES;
}

function nextUnpickedLandmark() {
  return activeLandmarkNames().find((n) => !(n in pickedLandmarks));
}

function resetManualPicks() {
  for (const n of [...LANDMARK_NAMES, ALT_FRONTAL_NAME]) delete pickedLandmarks[n];
  clearMarkers();
  drawHcLine(null);
  updateLandmarkList();
  resetAlignState();
}

// deliberately does NOT invalidate alignment itself - this runs on every
// mousemove tick while dragging a landmark, and while "adjust picks" is
// active that drag depends on registeredTransform staying put. a full
// reset (reset-button, new upload) calls resetAlignState() itself; an
// actual landmark position change calls markLandmarksChanged() itself
// (see both below) - this only refreshes the button-enabled state (e.g.
// "align" unlocking once the last landmark is picked), which always
// needs to happen here regardless of which of those applies.
function updateLandmarkList() {
  document.querySelectorAll("#landmark-list li").forEach((li) => {
    const name = li.dataset.name;
    const valueEl = li.querySelector(".landmark-value");
    const p = pickedLandmarks[name];
    if (p) {
      valueEl.textContent = `${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}`;
      li.classList.add("picked");
    } else {
      valueEl.textContent = "not picked";
      li.classList.remove("picked");
    }
  });
  updateAnalyzeButtonState();
}

// secondary frontal landmark is cranium-only (see AnalyzeRequest) - facial
// registration/clipping never had a "which frontal point" ambiguity to
// begin with, so there's nothing for it to do there.
function updateAltFrontalVisibility() {
  const target = document.querySelector('input[name="target"]:checked').value;
  const row = document.getElementById("use-alt-frontal-row");
  row.classList.toggle("hidden", target !== "cranium");
  if (target !== "cranium" && document.getElementById("use-alt-frontal").checked) {
    document.getElementById("use-alt-frontal").checked = false;
    setUseAltFrontal(false);
  }
}

function setUseAltFrontal(enabled) {
  useAltFrontal = enabled;
  document.getElementById("alt-frontal-item").classList.toggle("hidden", !enabled);
  if (!enabled) {
    delete pickedLandmarks[ALT_FRONTAL_NAME];
    if (landmarkMarkerObjects[ALT_FRONTAL_NAME]) {
      scene.remove(landmarkMarkerObjects[ALT_FRONTAL_NAME]);
      delete landmarkMarkerObjects[ALT_FRONTAL_NAME];
    }
  }
  // deliberately does NOT invalidate an existing alignment - /clip always
  // re-registers from the current landmarks/target/alt-frontal state fresh
  // (see start_clip in api/routers/mesh.py), so "align" was never actually
  // a dependency of "run pipeline"'s correctness, just a preview/sanity
  // gate on the landmark POSITIONS. enabling alt-frontal naturally
  // requires a new pick anyway (landmarksOk below goes false until it's
  // placed, which does mark the alignment stale - see markLandmarksChanged).
  updateLandmarkList();
}

document.getElementById("use-alt-frontal").addEventListener("change", (event) => {
  setUseAltFrontal(event.target.checked);
});

document.querySelectorAll('input[name="target"]').forEach((el) => {
  // deliberately does NOT invalidate an existing alignment either, same
  // reasoning as setUseAltFrontal above - switching cranial/facial doesn't
  // change any landmark's position, and /clip picks up the new target
  // fresh on its own.
  el.addEventListener("change", updateAltFrontalVisibility);
});
updateAltFrontalVisibility();

function pointerToNdc(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * 2 - 1,
    y: -((event.clientY - rect.top) / rect.height) * 2 + 1,
  };
}

canvas.addEventListener("click", (event) => {
  if (!currentMeshObject) return;
  if (!(event.ctrlKey || event.metaKey)) return; // ctrl/cmd-click required, so a plain click can still orbit

  const ndc = pointerToNdc(event);
  pointer.x = ndc.x;
  pointer.y = ndc.y;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObject(currentMeshObject, true);
  if (hits.length === 0) return;
  const point = hits[0].point;

  const name = nextUnpickedLandmark();
  if (!name) return;
  pickedLandmarks[name] = { x: point.x, y: point.y, z: point.z };
  addLandmarkMarker(name, point);
  updateLandmarkList();
  markLandmarksChanged();
});

// --- landmark repositioning (alt + left-button drag) ---
// separate from ctrl-click placement above: grab an already-placed marker
// with alt+mousedown, drag it across the mesh surface, drop with mouseup.
// orbit controls get disabled for the duration so dragging the camera and
// dragging a landmark can't fight each other.

let draggingLandmarkName = null;

canvas.addEventListener("mousedown", (event) => {
  if (!event.altKey || event.button !== 0) return;
  if (!currentMeshObject) return;
  const names = Object.keys(landmarkMarkerObjects);
  if (names.length === 0) return;

  const ndc = pointerToNdc(event);
  pointer.x = ndc.x;
  pointer.y = ndc.y;
  raycaster.setFromCamera(pointer, camera);
  const markerObjects = names.map((n) => landmarkMarkerObjects[n]);
  // a marker's matrixWorld only refreshes on the next render() tick, which
  // hasn't necessarily happened yet if it was just placed/moved - raycasting
  // against a stale (identity) matrixWorld makes every hit test miss.
  markerObjects.forEach((m) => m.updateMatrixWorld(true));
  const hits = raycaster.intersectObjects(markerObjects, false);
  if (hits.length === 0) return;

  draggingLandmarkName = names.find((n) => landmarkMarkerObjects[n] === hits[0].object);
  controls.enabled = false;
  event.preventDefault();
});

canvas.addEventListener("mousemove", (event) => {
  if (!draggingLandmarkName) return;

  const ndc = pointerToNdc(event);
  pointer.x = ndc.x;
  pointer.y = ndc.y;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObject(currentMeshObject, true);
  if (hits.length === 0) return;
  const point = hits[0].point;

  // while "adjust picks" is active, the marker is being dragged on the
  // ALIGNED mesh, but pickedLandmarks has to stay in raw-mesh coordinates
  // (what /align and /clip both expect) - convert back through the
  // inverse of /align's own transform so re-aligning uses the right
  // values. see applyInverseTransform below.
  pickedLandmarks[draggingLandmarkName] =
    adjustingInAlignedFrame && registeredTransform
      ? applyInverseTransform(point, registeredTransform)
      : { x: point.x, y: point.y, z: point.z };
  landmarkMarkerObjects[draggingLandmarkName].position.copy(point);
  updateLandmarkList();
  markLandmarksChanged();
});

window.addEventListener("mouseup", () => {
  if (!draggingLandmarkName) return;
  draggingLandmarkName = null;
  controls.enabled = true;
});

// --- upload ---

let sessionId = null;

async function _afterSessionOpened(response, meshPath) {
  const infoEl = document.getElementById("mesh-info");
  if (!response.ok) {
    infoEl.textContent = `Couldn't open mesh: ${await response.text()}`;
    return;
  }

  const data = await response.json();
  sessionId = data.session_id;
  infoEl.textContent = `${data.vertex_count} vertices, ${data.face_count} faces`;
  document.getElementById("mesh-path").textContent = meshPath ?? "";
  document.getElementById("viewer-hint").classList.add("hidden");
  document.getElementById("results").classList.add("hidden");
  document.getElementById("save-status").textContent = "";

  resetManualPicks();
  await displayMesh(`/api/sessions/${sessionId}/mesh/original`);
  updateAnalyzeButtonState();
}

async function uploadFiles(files) {
  selectionHasTexture = hasTextureFile(files.map((f) => f.name));
  document.getElementById("mesh-info").textContent = "Uploading...";
  const formData = new FormData();
  for (const f of files) formData.append("files", f);
  try {
    await _afterSessionOpened(await fetch("/api/sessions", { method: "POST", body: formData }), primaryMeshFile(files.map((f) => f.name)));
  } catch (err) {
    document.getElementById("mesh-info").textContent = `Upload failed: ${err}`;
  }
}

// desktop-only: paths from the native file dialog (see pick_file in
// desktop/app.py) - read straight off disk server-side, no upload needed,
// and the source folder gets remembered so results can be saved back into
// it later without asking (see the save-results button below).
async function openFilesFromPaths(paths) {
  selectionHasTexture = hasTextureFile(paths.map((p) => p.split(/[\\/]/).pop()));
  document.getElementById("mesh-info").textContent = "Opening...";
  try {
    await _afterSessionOpened(
      await fetch("/api/sessions/from-paths", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths }),
      }),
      // full path, not just the basename - this is the one case where we
      // actually know a real filesystem location, so show it in full
      paths.find((p) => MESH_EXTENSIONS.includes(extOf(p.split(/[\\/]/).pop())))
    );
  } catch (err) {
    document.getElementById("mesh-info").textContent = `Couldn't open mesh: ${err}`;
  }
}

const MESH_EXTENSIONS = ["ply", "obj", "stl"];
const TEXTURE_EXTENSIONS = ["jpg", "jpeg", "png"];

function extOf(name) {
  return (name.split(".").pop() || "").toLowerCase();
}

function hasMeshFile(names) {
  return names.some((n) => MESH_EXTENSIONS.includes(extOf(n)));
}

function primaryMeshFile(names) {
  return names.find((n) => MESH_EXTENSIONS.includes(extOf(n)));
}

function hasTextureFile(names) {
  return names.some((n) => TEXTURE_EXTENSIONS.includes(extOf(n)));
}

document.getElementById("choose-mesh-button").addEventListener("click", async () => {
  if (isDesktopApp()) {
    const paths = await pickFileNative(true, (msg) => {
      document.getElementById("mesh-info").textContent = `Couldn't open the file picker: ${msg}`;
    });
    if (!paths || paths.length === 0) return;
    if (!hasMeshFile(paths.map((p) => p.split(/[\\/]/).pop()))) {
      document.getElementById("mesh-info").textContent = "No .ply/.obj/.stl found in what you picked";
      return;
    }
    openFilesFromPaths(paths);
  } else {
    document.getElementById("file-input").click();
  }
});

document.getElementById("file-input").addEventListener("change", (event) => {
  const allFiles = Array.from(event.target.files);
  if (allFiles.length === 0) return;
  if (!hasMeshFile(allFiles.map((f) => f.name))) {
    document.getElementById("mesh-info").textContent = "No .ply/.obj/.stl found in the files you picked";
    return;
  }
  uploadFiles(allFiles);
});

// true once /align has completed successfully and nothing since has
// invalidated it (see resetAlignState) - gates "adjust picks" and "run",
// same way landmarksOk below gates "align" itself. clipping is always
// automatic (landmark-guided plane, no manual mode) - see
// pipeline.cranial_clip/facial_clip.
let alignSucceeded = false;
// true while "adjust picks" markers are showing on the ALIGNED mesh - the
// alt-drag handler needs to know this so it converts back to raw-mesh
// coordinates before writing into pickedLandmarks (see
// applyInverseTransform below). reset whenever the current alignment is
// invalidated, same as alignSucceeded.
let adjustingInAlignedFrame = false;
// {rotation: 3x3 row-major, translation: [x,y,z]} from the last
// successful /align - see api.schemas.RegisteredTransformResponse.
let registeredTransform = null;
// true once "run pipeline" has completed successfully - locks "align" and
// "adjust picks" (further landmark tweaks wouldn't retroactively update
// results already shown), leaving "reset" or a new file upload as the
// only ways back in. "run pipeline" itself stays unlocked, so resample
// vertex count / center-of-mass correction can still be changed and
// re-run without a fresh align.
let pipelineRan = false;
// true whenever the current landmark positions haven't been through a
// successful /align yet - gates align/run so they stay mutually exclusive:
// align is only pressable while this is true, run only once it's false
// again (i.e. align succeeded and nothing moved since). target/com/resample
// changes don't touch this flag since /clip always re-registers fresh from
// current UI state regardless of what align last computed (see
// register_and_clip_cranial/register in pipeline.py) - only landmark
// position changes actually invalidate a completed alignment.
let landmarksChangedSinceAlign = true;

function resetAlignState() {
  alignSucceeded = false;
  adjustingInAlignedFrame = false;
  registeredTransform = null;
  pipelineRan = false;
  landmarksChangedSinceAlign = true;
  document.getElementById("align-status").innerHTML = "";
  updateAnalyzeButtonState();
}

// call whenever a landmark's position actually changes (new pick, alt-drag,
// or adjust-picks repositioning) - re-enables "align" and locks "run" until
// the new positions are aligned again.
function markLandmarksChanged() {
  landmarksChangedSinceAlign = true;
  updateAnalyzeButtonState();
}

function updateAnalyzeButtonState() {
  const landmarksOk = activeLandmarkNames().every((n) => n in pickedLandmarks);
  document.getElementById("align-button").disabled =
    !sessionId || !landmarksOk || pipelineRan || !landmarksChangedSinceAlign;
  document.getElementById("adjust-picks-button").disabled = !alignSucceeded || pipelineRan;
  document.getElementById("reset-button").disabled = !sessionId;
  document.getElementById("run-button").disabled = !alignSucceeded || landmarksChangedSinceAlign;
}

// forward: aligned = raw @ R.T + t (matches RigidTransform.apply in
// craniumpy_core.registration.rigid). rotation is 3x3 row-major,
// translation is [x, y, z] - see RegisteredTransformResponse.
function applyTransform(point, transform) {
  const { rotation: R, translation: t } = transform;
  const p = [point.x, point.y, point.z];
  const out = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    let sum = t[i];
    for (let j = 0; j < 3; j++) sum += p[j] * R[i][j];
    out[i] = sum;
  }
  return { x: out[0], y: out[1], z: out[2] };
}

// inverse of the above - R is orthogonal (a pure rotation), so R^-1 = R.T
// and raw = (aligned - t) @ R. verified this round-trips to floating-point
// precision against the backend's own transform.
function applyInverseTransform(point, transform) {
  const { rotation: R, translation: t } = transform;
  const d = [point.x - t[0], point.y - t[1], point.z - t[2]];
  const out = [0, 0, 0];
  for (let j = 0; j < 3; j++) {
    let sum = 0;
    for (let i = 0; i < 3; i++) sum += d[i] * R[i][j];
    out[j] = sum;
  }
  return { x: out[0], y: out[1], z: out[2] };
}

// --- mesh cleanup ---

function updateResampleWidget() {
  const enabled = document.getElementById("resample-mesh").checked;
  document.getElementById("vertex-count").disabled = !enabled;
}

document.getElementById("resample-mesh").addEventListener("change", updateResampleWidget);
updateResampleWidget();

// --- align / undo / run ---

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// shared by /clip (the "align" button) and /run - both are async
// background jobs polled the same way. returns the final status ("done"
// or "error"), updating statusEl with live progress along the way.
async function pollJobStatus(statusEl) {
  while (true) {
    const response = await fetch(`/api/sessions/${sessionId}/status`);
    const data = await response.json();
    if (data.status === "done") {
      statusEl.textContent = "Done.";
      return "done";
    }
    if (data.status === "error") {
      statusEl.textContent = `Error: ${data.error}`;
      return "error";
    }
    // live progress - this is the actual current pipeline stage, not a
    // static "please wait" message
    if (data.progress) {
      statusEl.textContent = `${data.progress.stage}${data.progress.detail ? " - " + data.progress.detail : ""}...`;
    }
    await sleep(500);
  }
}

// shared by /align and /clip - both need the landmarks in the same shape.
function _landmarksBody() {
  const body = { landmarks: LANDMARK_NAMES.map((n) => pickedLandmarks[n]) };
  if (useAltFrontal && pickedLandmarks[ALT_FRONTAL_NAME]) {
    body.alt_frontal_landmark = pickedLandmarks[ALT_FRONTAL_NAME];
  }
  return body;
}

document.getElementById("align-button").addEventListener("click", async () => {
  if (!sessionId) return;

  const target = document.querySelector('input[name="target"]:checked').value;
  const body = { target, ..._landmarksBody() };

  const statusEl = document.getElementById("align-status");
  resetAlignState();
  statusEl.textContent = "Starting...";
  document.getElementById("align-button").disabled = true;

  const startResponse = await fetch(`/api/sessions/${sessionId}/align`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!startResponse.ok) {
    statusEl.textContent = `Failed to start: ${await startResponse.text()}`;
    updateAnalyzeButtonState();
    return;
  }

  const outcome = await pollJobStatus(statusEl);
  if (outcome === "done") {
    await displayMesh(`/api/sessions/${sessionId}/mesh/registered`);
    const transformResponse = await fetch(`/api/sessions/${sessionId}/registered-transform`);
    registeredTransform = transformResponse.ok ? await transformResponse.json() : null;
    alignSucceeded = true;
    // landmark positions haven't changed since this align completed, so
    // lock "align" back out and unlock "run" - overwrites pollJobStatus's
    // generic "done." with a persistent completion marker.
    landmarksChangedSinceAlign = false;
    statusEl.textContent = "Rigid alignment: ✓";
  }
  updateAnalyzeButtonState();
});

document.getElementById("reset-button").addEventListener("click", async () => {
  if (!sessionId) return;
  // full clean slate, on purpose - unlike a lighter "undo" that would just
  // step back to the pre-align view, this clears every pick too, so
  // there's no stale state left over from whatever "run pipeline" (if it
  // ran) or "align" already committed. align is cheap and stateless
  // beyond the session fields it directly sets, so no server round-trip
  // is needed here beyond re-fetching the original mesh.
  resetManualPicks();
  await displayMesh(`/api/sessions/${sessionId}/mesh/original`);
  document.getElementById("align-status").textContent = "";
  updateAnalyzeButtonState();
});

document.getElementById("adjust-picks-button").addEventListener("click", () => {
  if (!alignSucceeded || !registeredTransform) return;
  // shows the existing picks on the currently-displayed ALIGNED mesh (not
  // the raw one) so they're easier to judge in a standard, oriented pose.
  // alt-drag already works on whatever markers are showing - the drag
  // handler checks adjustingInAlignedFrame to know it needs to convert
  // back to raw coordinates before storing.
  for (const name of activeLandmarkNames()) {
    const raw = pickedLandmarks[name];
    if (raw) addLandmarkMarker(name, applyTransform(raw, registeredTransform));
  }
  adjustingInAlignedFrame = true;
  // re-registration is only actually needed once a pick is moved, but the
  // user asked for this to unlock "align" as soon as "adjust picks" is
  // pressed, not only once a drag happens.
  markLandmarksChanged();
});

document.getElementById("run-button").addEventListener("click", async () => {
  if (!sessionId || !alignSucceeded) return;

  const target = document.querySelector('input[name="target"]:checked').value;
  const comTranslation = document.getElementById("com-translation").checked;
  const resampleMesh = document.getElementById("resample-mesh").checked;
  const vertexCount = Number(document.getElementById("vertex-count").value) || 10000;

  // "run pipeline" is one committed action from the user's side, but two
  // calls under the hood - /clip (repair + register + clip, cheap after
  // the first press per session) then /run (resample + measure) - same
  // pattern the old two-button clip/run design used, just chained
  // automatically now instead of needing two separate clicks.
  const clipBody = {
    target,
    com_translation: comTranslation,
    // always on - a real scan (photogrammetry especially) can come in with
    // thousands of disconnected patches from the reconstruction process;
    // repair_mesh's merge+pymeshfix pass is what turns that into a single
    // usable surface. cached server-side across repeated presses in this
    // session (see api.sessions.Session.repaired_mesh) - only the first
    // press per session actually pays for it.
    repair: true,
    ..._landmarksBody(),
  };
  const runBody = { n_vertices: resampleMesh ? vertexCount : null };

  const statusEl = document.getElementById("job-status");
  statusEl.textContent = "Starting...";
  document.getElementById("run-button").disabled = true;

  const clipResponse = await fetch(`/api/sessions/${sessionId}/clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(clipBody),
  });
  if (!clipResponse.ok) {
    statusEl.textContent = `Failed to start: ${await clipResponse.text()}`;
    updateAnalyzeButtonState();
    return;
  }
  if ((await pollJobStatus(statusEl)) !== "done") {
    updateAnalyzeButtonState();
    return;
  }

  const runResponse = await fetch(`/api/sessions/${sessionId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(runBody),
  });
  if (!runResponse.ok) {
    statusEl.textContent = `Failed to start: ${await runResponse.text()}`;
    updateAnalyzeButtonState();
    return;
  }

  const outcome = await pollJobStatus(statusEl);
  if (outcome === "done") {
    pipelineRan = true;
    await showResults();
    // overwrites pollJobStatus's generic "Done." - same treatment as
    // align-status's "Rigid alignment: ✓" above.
    statusEl.textContent = "Run complete: ✓";
  }
  updateAnalyzeButtonState();
});

let lastResultsData = null;

async function showResults() {
  const response = await fetch(`/api/sessions/${sessionId}/results`);
  if (!response.ok) return;
  const data = await response.json();
  lastResultsData = data;

  document.getElementById("results").classList.remove("hidden");

  const rows = [];
  if (data.craniometrics) {
    const c = data.craniometrics;
    rows.push(["OFD (depth)", `${c.depth_mm} mm`]);
    rows.push(["BPD (breadth)", `${c.breadth_mm} mm`]);
    rows.push(["cephalic index", c.cephalic_index]);
    rows.push(["circumference", `${c.circumference_cm} cm`]);
    rows.push(["mesh volume", `${c.mesh_volume_cc} cc`]);
  }
  if (data.asymmetry) {
    rows.push([
      'mean facial asymmetry (MFA) - <a href="https://www.sciencedirect.com/science/article/pii/S1010518225001611?via%3Dihub" target="_blank" rel="noopener">details</a>',
      data.asymmetry.mean_asymmetry_index.toFixed(2),
    ]);
  }

  const table = document.getElementById("results-table");
  table.innerHTML = "";
  for (const [label, value] of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
    table.appendChild(tr);
  }
  document.getElementById("alt-frontal-note").classList.toggle("hidden", !data.used_alt_frontal);

  document.getElementById("visualization").classList.remove("hidden");
  // "measurements" mode means different things per target - HC/BPD/OFD for
  // cranial, the asymmetry heatmap for facial - so it's always a valid
  // choice, just relabeled rather than hidden for one target the way it
  // used to be (which left facial results with no non-template default and
  // silently dropped the heatmap the moment applyVisualizationMode ran).
  document.getElementById("measurements-mode-text").textContent = data.craniometrics ? "metrics" : "asymmetry";
  document.querySelector('input[name="visualization-mode"][value="measurements"]').checked = true;
  document.getElementById("visualization-toggle").checked = true;

  if (shippedTemplates.length === 0) await fetchShippedTemplates();
  populateTemplateSelect();
  await displayResultMesh();
  await applyVisualizationMode();
}

// shows the final (post clip/repair/resample) mesh, no landmark markers -
// the mesh itself is the point once registration/clipping is done.
// measurement lines/template overlay are layered on separately by
// applyVisualizationMode - see showResults. pulled out of showResults() so
// visualization mode switches can get back to this same view without
// re-running the whole analysis.
async function displayResultMesh() {
  await displayMesh(`/api/sessions/${sessionId}/mesh/result`);
}

// --- template overlay: compare the final mesh (the one you'd download,
// post clip/repair/resample - "what's in view") against a reference
// template, with X/Y/Z axes and both centers of gravity. templates are
// always shown exactly as stored on disk - no live clipping - so a
// whole-head template stays a whole head even when the patient's own mesh
// is clipped down to just the cranium or face.

// which template makes the most sense to compare against depends on more
// than just the target - a cranial result registered on the secondary
// frontal landmark (4 picks) needs a full-head reference, since
// clipped_template_xy is built in the sellion frame and won't line up; a
// plain 3-landmark cranial result wants the clipped cranium reference
// instead. either way it should match whether center-of-mass correction
// ran, since that's baked into the template's own pose too.
function defaultTemplateForCurrentResult() {
  const target = document.querySelector('input[name="target"]:checked').value;
  if (target === "face") return "template_face";
  const usedAltFrontal = lastResultsData ? lastResultsData.used_alt_frontal : false;
  const comOn = document.getElementById("com-translation").checked;
  if (usedAltFrontal) return comOn ? "template_xy_subanasal_com" : "template_xy_subanasal";
  return comOn ? "clipped_template_xy_com" : "clipped_template_xy";
}

let shippedTemplates = [];

async function fetchShippedTemplates() {
  const response = await fetch("/api/templates");
  if (!response.ok) return;
  shippedTemplates = await response.json();
}

function isDesktopApp() {
  // window.pywebview.api starts out as {} the instant pywebview injects its
  // bridge, before pick_file is actually attached to it - checking the
  // object's truthiness instead of the function's would report "desktop"
  // during that gap and then fail calling something that doesn't exist yet.
  return typeof window.pywebview !== "undefined" && typeof window.pywebview.api?.pick_file === "function";
}

// wraps the native file dialog call so a failure (bad file filter string,
// pywebview not ready yet, whatever) shows up as a message instead of the
// button just silently doing nothing.
async function pickFileNative(allowMultiple, onError) {
  try {
    return await window.pywebview.api.pick_file(allowMultiple);
  } catch (err) {
    onError(err && err.message ? err.message : String(err));
    return null;
  }
}

function templateChoiceStorageKey(target) {
  return `craniumpy.templateChoice.${target}`;
}

function customTemplatePathStorageKey(target) {
  return `craniumpy.customTemplatePath.${target}`;
}

// populates the dropdown for whatever target is currently selected, and
// restores whatever was picked last time for that target (if anything) -
// this is the "remembered" part of the custom-template flow.
function populateTemplateSelect() {
  const target = document.querySelector('input[name="target"]:checked').value;
  const select = document.getElementById("template-select");
  select.innerHTML = "";
  for (const t of shippedTemplates) {
    const option = document.createElement("option");
    option.value = t.name;
    option.textContent = t.description;
    select.appendChild(option);
  }
  const customOption = document.createElement("option");
  customOption.value = "custom";
  customOption.textContent = "custom...";
  select.appendChild(customOption);

  const remembered = localStorage.getItem(templateChoiceStorageKey(target));
  select.value = remembered && [...select.options].some((o) => o.value === remembered)
    ? remembered
    : (defaultTemplateForCurrentResult() || shippedTemplates[0]?.name || "custom");
  updateTemplateCustomRow();
}

function updateTemplateCustomRow() {
  const target = document.querySelector('input[name="target"]:checked').value;
  const isCustom = document.getElementById("template-select").value === "custom";
  document.getElementById("template-custom-row").classList.toggle("hidden", !isCustom);
  document.getElementById("template-custom-hint").classList.toggle("hidden", !isCustom || isDesktopApp());

  const nameEl = document.getElementById("template-custom-name");
  if (!isCustom) {
    nameEl.textContent = "";
    return;
  }
  if (isDesktopApp()) {
    const path = localStorage.getItem(customTemplatePathStorageKey(target));
    nameEl.textContent = path ? path.split(/[\\/]/).pop() : "no file picked yet";
  } else {
    nameEl.textContent = customTemplateBlobName || "no file picked yet (won't be remembered next time)";
  }
}

document.getElementById("template-select").addEventListener("change", async () => {
  const target = document.querySelector('input[name="target"]:checked').value;
  localStorage.setItem(templateChoiceStorageKey(target), document.getElementById("template-select").value);
  updateTemplateCustomRow();
  await refreshTemplateOverlayIfShown();
});

// browser-mode only: holds the last uploaded custom template's GLB blob URL
// and display name for this session - can't remember a real path across
// restarts without pywebview, see get_custom_template_mesh (the path-based
// one) in api/routers/mesh.py.
let customTemplateBlobUrl = null;
let customTemplateBlobName = null;

document.getElementById("template-browse-button").addEventListener("click", async () => {
  const target = document.querySelector('input[name="target"]:checked').value;
  if (isDesktopApp()) {
    const paths = await pickFileNative(false, (msg) => {
      document.getElementById("template-custom-name").textContent = `Couldn't open the file picker: ${msg}`;
    });
    if (!paths || paths.length === 0) return;
    localStorage.setItem(customTemplatePathStorageKey(target), paths[0]);
    updateTemplateCustomRow();
    await refreshTemplateOverlayIfShown();
  } else {
    document.getElementById("template-custom-file-input").click();
  }
});

document.getElementById("template-custom-file-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("files", file);
  const response = await fetch("/api/templates/custom/upload", { method: "POST", body: formData });
  if (!response.ok) {
    document.getElementById("template-custom-name").textContent = `Upload failed: ${await response.text()}`;
    return;
  }
  if (customTemplateBlobUrl) URL.revokeObjectURL(customTemplateBlobUrl);
  customTemplateBlobUrl = URL.createObjectURL(await response.blob());
  customTemplateBlobName = file.name;
  updateTemplateCustomRow();
  await refreshTemplateOverlayIfShown();
});

let templateOverlayObject = null;
let axesObject = null;
let cogMeshMarker = null;
let cogTemplateMarker = null;
let cogLine = null;

function clearTemplateOverlay() {
  if (templateOverlayObject) scene.remove(templateOverlayObject);
  if (axesObject) scene.remove(axesObject);
  if (cogMeshMarker) scene.remove(cogMeshMarker);
  if (cogTemplateMarker) scene.remove(cogTemplateMarker);
  if (cogLine) scene.remove(cogLine);
  templateOverlayObject = axesObject = cogMeshMarker = cogTemplateMarker = cogLine = null;
  document.getElementById("template-offset-info").textContent = "";
  document.getElementById("template-legend").classList.add("hidden");
}

// plain vertex-average centroid - not the slice-based center-of-mass the
// backend uses for craniometrics (that's specific to the pediatric HC
// algorithm), just a straightforward "middle of all the points" for
// visually comparing two whole meshes.
function computeCentroid(object) {
  const sum = new THREE.Vector3();
  let count = 0;
  const v = new THREE.Vector3();
  object.traverse((child) => {
    if (!child.isMesh) return;
    const pos = child.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      child.localToWorld(v);
      sum.add(v);
      count++;
    }
  });
  return count > 0 ? sum.divideScalar(count) : sum;
}

function addCogMarker(point, color) {
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius * 1.4, 16, 16),
    new THREE.MeshBasicMaterial({ color })
  );
  marker.position.copy(point);
  scene.add(marker);
  return marker;
}

// resolves the current dropdown selection to a GLB url/loader and a
// display name for the offset readout. returns null if "custom" is
// selected but nothing's actually been picked yet.
async function resolveTemplateForOverlay() {
  const target = document.querySelector('input[name="target"]:checked').value;
  const choice = document.getElementById("template-select").value;

  if (choice !== "custom") {
    return { object: await loadGlb(`/api/templates/${choice}/mesh`), displayName: choice };
  }

  if (isDesktopApp()) {
    const path = localStorage.getItem(customTemplatePathStorageKey(target));
    if (!path) return null;
    return {
      object: await loadGlb(`/api/templates/custom/mesh?path=${encodeURIComponent(path)}`),
      displayName: path.split(/[\\/]/).pop(),
    };
  }

  // uploaded via template-custom-file-input above
  if (!customTemplateBlobUrl) return null;
  return { object: await loadGlb(customTemplateBlobUrl), displayName: customTemplateBlobName };
}

async function enableTemplateOverlay() {
  const resolved = await resolveTemplateForOverlay();
  if (!resolved) {
    document.getElementById("template-offset-info").textContent = "Pick a custom template file first.";
    document.getElementById("visualization-toggle").checked = false;
    updateVisualizationControlsVisibility();
    return;
  }

  const meshObject = await displayMesh(`/api/sessions/${sessionId}/mesh/result`);

  const templateObject = resolved.object;
  templateObject.traverse((child) => {
    if (!child.isMesh) return;
    child.geometry.computeVertexNormals();
    child.material = new THREE.MeshStandardMaterial({
      color: 0x60a5fa,
      transparent: true,
      opacity: 0.35,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
  });
  scene.add(templateObject);
  templateOverlayObject = templateObject;

  const meshCentroid = computeCentroid(meshObject);
  const templateCentroid = computeCentroid(templateObject);

  const box = new THREE.Box3().setFromObject(meshObject);
  box.union(new THREE.Box3().setFromObject(templateObject));
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 1) * 0.7;

  axesObject = new THREE.Group();
  const axisDefs = [
    { dir: new THREE.Vector3(1, 0, 0), color: 0xff4d4d },
    { dir: new THREE.Vector3(0, 1, 0), color: 0x4dff88 },
    { dir: new THREE.Vector3(0, 0, 1), color: 0x4d9fff },
  ];
  for (const { dir, color } of axisDefs) {
    const pts = [dir.clone().multiplyScalar(-span), dir.clone().multiplyScalar(span)];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    axesObject.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color })));
  }
  scene.add(axesObject);

  cogMeshMarker = addCogMarker(meshCentroid, 0xffa500);
  cogTemplateMarker = addCogMarker(templateCentroid, 0x60a5fa);

  const lineGeo = new THREE.BufferGeometry().setFromPoints([meshCentroid, templateCentroid]);
  cogLine = new THREE.Line(lineGeo, new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 3, gapSize: 2 }));
  cogLine.computeLineDistances();
  scene.add(cogLine);

  const d = new THREE.Vector3().subVectors(meshCentroid, templateCentroid);
  document.getElementById("template-offset-info").textContent =
    `center-of-gravity offset from template (${resolved.displayName}): ${d.length().toFixed(1)}mm total ` +
    `(x ${d.x.toFixed(1)}, y ${d.y.toFixed(1)}, z ${d.z.toFixed(1)})`;
  document.getElementById("template-legend").classList.remove("hidden");
}

function currentVisualizationMode() {
  return document.querySelector('input[name="visualization-mode"]:checked')?.value;
}

// re-runs the overlay against whatever's now selected, but only if the
// overlay is actually on screen - picking a different template (or a new
// custom file) while it's off just changes what enableTemplateOverlay()
// would show next time it's turned on, no need to touch the viewer yet.
async function refreshTemplateOverlayIfShown() {
  if (!sessionId || !lastResultsData) return;
  if (!document.getElementById("visualization-toggle").checked || currentVisualizationMode() !== "template") return;
  clearTemplateOverlay();
  await enableTemplateOverlay();
}

function updateVisualizationControlsVisibility() {
  const enabled = document.getElementById("visualization-toggle").checked;
  const mode = currentVisualizationMode();
  const hasCraniometrics = !!(lastResultsData && lastResultsData.craniometrics);
  document.getElementById("visualization-mode-row").classList.toggle("hidden", !enabled);
  document.getElementById("template-controls").classList.toggle("hidden", !enabled || mode !== "template");
  document.getElementById("measurements-hint").classList.toggle("hidden", !enabled || mode !== "measurements" || !hasCraniometrics);
  document.getElementById("asymmetry-hint").classList.toggle("hidden", !enabled || mode !== "measurements" || hasCraniometrics);
}

// only one of these is ever showing at a time - template overlay and the
// measurement lines/asymmetry heatmap/opacity would just visually fight
// over the same mesh.
async function applyVisualizationMode() {
  updateVisualizationControlsVisibility();
  disableMeasurementsVisualization();
  disableAsymmetryVisualization();
  clearTemplateOverlay();

  if (!sessionId || !lastResultsData || !document.getElementById("visualization-toggle").checked) return;

  if (currentVisualizationMode() === "template") {
    await enableTemplateOverlay();
  } else if (lastResultsData.craniometrics) {
    enableMeasurementsVisualization();
  } else {
    enableAsymmetryVisualization();
  }
}

document.getElementById("visualization-toggle").addEventListener("change", applyVisualizationMode);
for (const el of document.querySelectorAll('input[name="visualization-mode"]')) {
  el.addEventListener("change", applyVisualizationMode);
}

document.getElementById("download-bundle-button").addEventListener("click", async () => {
  if (!sessionId) return;
  const statusEl = document.getElementById("save-status");

  if (isDesktopApp()) {
    statusEl.textContent = "Saving...";
    const response = await fetch(`/api/sessions/${sessionId}/save`, { method: "POST" });
    if (response.ok) {
      const data = await response.json();
      statusEl.textContent = `Saved to ${data.saved_to}`;
      return;
    }
    // only real reason this 400s is a session that wasn't opened from a real
    // path (shouldn't normally happen in the desktop app, but fall back
    // cleanly rather than leaving the user stuck) - anything else is worth
    // surfacing instead of silently falling back.
    if (response.status !== 400) {
      statusEl.textContent = `Save failed: ${await response.text()}`;
      return;
    }
  }

  statusEl.textContent = "";
  window.location.href = `/api/sessions/${sessionId}/bundle`;
});

function updateResultsButtonLabel() {
  document.getElementById("download-bundle-button").textContent = isDesktopApp()
    ? "save results (mesh + report + figure)"
    : "download results (mesh + report + figure)";
}

// window.pywebview.api isn't necessarily ready on first paint - it shows up
// once pywebview finishes injecting its bridge, hence both the immediate
// call (covers plain-browser mode, which is never going to change) and the
// event listener (covers desktop mode's slightly-delayed readiness).
updateResultsButtonLabel();
window.addEventListener("pywebviewready", updateResultsButtonLabel);
