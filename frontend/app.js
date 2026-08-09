// craniumpy frontend. plain JS, no build step - see DEPENDENCIES.md for why.

import * as THREE from "three";
import { OrbitControls } from "./vendor/three/controls/OrbitControls.js";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

// --- menu bar ---
// just the shell for now - view (split screen, pre/post-op overlay) and
// settings (default template/config) are placeholders, nothing behind them
// yet. wiring here is only open/close, nothing else to hook up until there's
// an actual feature behind one of these.

document.querySelectorAll(".menu-trigger").forEach((trigger) => {
  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = trigger.closest(".menu");
    const wasOpen = menu.classList.contains("open");
    document.querySelectorAll(".menu.open").forEach((m) => {
      m.classList.remove("open");
      m.querySelector(".menu-dropdown").classList.add("hidden");
    });
    if (!wasOpen) {
      menu.classList.add("open");
      menu.querySelector(".menu-dropdown").classList.remove("hidden");
    }
  });
});

window.addEventListener("click", () => {
  document.querySelectorAll(".menu.open").forEach((m) => {
    m.classList.remove("open");
    m.querySelector(".menu-dropdown").classList.add("hidden");
  });
});

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
  currentMeshMaterials = [];
  currentMeshHasTexture = false;

  const object = await loadGlb(url);
  object.traverse((child) => {
    if (!child.isMesh) return;

    // recompute normals ourselves regardless of what the GLB has - a
    // missing/empty NORMAL attribute is what makes a PBR material render
    // solid black, learned that one the hard way
    child.geometry.computeVertexNormals();

    const hasTexture = !!(child.material && child.material.map);
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
  markerRadius = fitCameraToObject(object) * 0.012;
  applyClipPreview();

  document.getElementById("mesh-view-toggles").classList.remove("hidden");
  document.getElementById("wireframe-toggle").checked = false;
  const textureToggle = document.getElementById("texture-toggle");
  textureToggle.closest("label").classList.toggle("hidden", !currentMeshHasTexture);
  textureToggle.checked = true;
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
  applyClipPreview();
});

// --- landmark / result markers ---
// landmark markers (green, draggable via alt+drag) are tracked by name so a
// drag can look up and move the right one. result markers (blue, just a
// display of what the backend actually used) are a flat list.

let landmarkMarkerObjects = {};
let resultMarkers = [];

function clearLandmarkMarkers() {
  for (const name of Object.keys(landmarkMarkerObjects)) {
    scene.remove(landmarkMarkerObjects[name]);
  }
  landmarkMarkerObjects = {};
}

function clearResultMarkers() {
  for (const m of resultMarkers) scene.remove(m);
  resultMarkers = [];
}

function clearMarkers() {
  clearLandmarkMarkers();
  clearResultMarkers();
}

function addLandmarkMarker(name, point) {
  if (landmarkMarkerObjects[name]) scene.remove(landmarkMarkerObjects[name]);
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius, 16, 16),
    new THREE.MeshBasicMaterial({ color: 0x4ade80 })
  );
  marker.position.set(point.x, point.y, point.z);
  scene.add(marker);
  landmarkMarkerObjects[name] = marker;
  return marker;
}

function addResultMarker(point, color) {
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(markerRadius, 16, 16),
    new THREE.MeshBasicMaterial({ color })
  );
  marker.position.set(point.x, point.y, point.z);
  scene.add(marker);
  resultMarkers.push(marker);
  return marker;
}

let hcLineObject = null;

function drawHcLine(polygonPoints) {
  if (hcLineObject) {
    scene.remove(hcLineObject);
    hcLineObject = null;
  }
  if (!polygonPoints || polygonPoints.length < 3) return;
  const pts = polygonPoints.map((p) => new THREE.Vector3(p.x, p.y, p.z));
  pts.push(pts[0]); // close the loop
  const geometry = new THREE.BufferGeometry().setFromPoints(pts);
  hcLineObject = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0xd1453d, linewidth: 2 }));
  scene.add(hcLineObject);
}

// --- landmark picking (ctrl/cmd + click) ---

const LANDMARK_NAMES = ["nasion", "left_tragus", "right_tragus"];
const pickedLandmarks = {};
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

function nextUnpickedLandmark() {
  return LANDMARK_NAMES.find((n) => !(n in pickedLandmarks));
}

function resetManualPicks() {
  for (const n of LANDMARK_NAMES) delete pickedLandmarks[n];
  clearMarkers();
  drawHcLine(null);
  updateLandmarkList();
}

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

  if (isManualClipMode()) {
    // ctrl-click moves the clip plane's origin to this point, along the current axis
    setClipOffsetFromPoint(point);
    return;
  }

  const name = nextUnpickedLandmark();
  if (!name) return;
  pickedLandmarks[name] = { x: point.x, y: point.y, z: point.z };
  addLandmarkMarker(name, point);
  updateLandmarkList();
});

document.getElementById("reset-landmarks").addEventListener("click", resetManualPicks);

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

  pickedLandmarks[draggingLandmarkName] = { x: point.x, y: point.y, z: point.z };
  landmarkMarkerObjects[draggingLandmarkName].position.copy(point);
  updateLandmarkList();
});

window.addEventListener("mouseup", () => {
  if (!draggingLandmarkName) return;
  draggingLandmarkName = null;
  controls.enabled = true;
});

// --- upload ---

let sessionId = null;

async function _afterSessionOpened(response) {
  const infoEl = document.getElementById("mesh-info");
  if (!response.ok) {
    infoEl.textContent = `couldn't open mesh: ${await response.text()}`;
    return;
  }

  const data = await response.json();
  sessionId = data.session_id;
  infoEl.textContent = `${data.vertex_count} vertices, ${data.face_count} faces`;
  document.getElementById("viewer-hint").classList.add("hidden");
  document.getElementById("results").classList.add("hidden");
  document.getElementById("save-status").textContent = "";

  resetManualPicks();
  await displayMesh(`/api/sessions/${sessionId}/mesh/original`);
  updateAnalyzeButtonState();
}

async function uploadFiles(files) {
  document.getElementById("mesh-info").textContent = "uploading...";
  const formData = new FormData();
  for (const f of files) formData.append("files", f);
  try {
    await _afterSessionOpened(await fetch("/api/sessions", { method: "POST", body: formData }));
  } catch (err) {
    document.getElementById("mesh-info").textContent = `upload failed: ${err}`;
  }
}

// desktop-only: paths from the native file dialog (see pick_file in
// desktop/app.py) - read straight off disk server-side, no upload needed,
// and the source folder gets remembered so results can be saved back into
// it later without asking (see the save-results button below).
async function openFilesFromPaths(paths) {
  document.getElementById("mesh-info").textContent = "opening...";
  try {
    await _afterSessionOpened(
      await fetch("/api/sessions/from-paths", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths }),
      })
    );
  } catch (err) {
    document.getElementById("mesh-info").textContent = `couldn't open mesh: ${err}`;
  }
}

const MESH_EXTENSIONS = ["ply", "obj", "stl"];

function hasMeshFile(names) {
  const extOf = (name) => (name.split(".").pop() || "").toLowerCase();
  return names.some((n) => MESH_EXTENSIONS.includes(extOf(n)));
}

document.getElementById("choose-mesh-button").addEventListener("click", async () => {
  if (isDesktopApp()) {
    const paths = await pickFileNative(true, (msg) => {
      document.getElementById("mesh-info").textContent = `couldn't open the file picker: ${msg}`;
    });
    if (!paths || paths.length === 0) return;
    if (!hasMeshFile(paths.map((p) => p.split(/[\\/]/).pop()))) {
      document.getElementById("mesh-info").textContent = "no .ply/.obj/.stl found in what you picked";
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
    document.getElementById("mesh-info").textContent = "no .ply/.obj/.stl found in the files you picked";
    return;
  }
  uploadFiles(allFiles);
});

function updateAnalyzeButtonState() {
  const button = document.getElementById("analyze-button");
  const landmarksOk = LANDMARK_NAMES.every((n) => n in pickedLandmarks);
  button.disabled = !sessionId || !landmarksOk;
}

// --- clipping: default vs manual plane widget ---

let clipAxis = new THREE.Vector3(0, 1, 0);
let clipOffset = 0;
let clipPlaneMesh = null;
let clipArrow = null;

function isManualClipMode() {
  const checked = document.querySelector('input[name="clip-mode"]:checked');
  return checked && checked.value === "manual";
}

function currentClipPlane() {
  // plane through (axis * offset), normal = axis. matches clip_plane()'s
  // "+normal side is kept" convention on the backend.
  const origin = clipAxis.clone().multiplyScalar(clipOffset);
  const plane = new THREE.Plane();
  plane.setFromNormalAndCoplanarPoint(clipAxis, origin);
  return plane;
}

function updateClipWidget() {
  const origin = clipAxis.clone().multiplyScalar(clipOffset);

  if (!clipPlaneMesh) {
    const geo = new THREE.PlaneGeometry(300, 300);
    const mat = new THREE.MeshBasicMaterial({ color: 0xf5c518, transparent: true, opacity: 0.25, side: THREE.DoubleSide });
    clipPlaneMesh = new THREE.Mesh(geo, mat);
    scene.add(clipPlaneMesh);
  }
  clipPlaneMesh.position.copy(origin);
  clipPlaneMesh.lookAt(origin.clone().add(clipAxis));

  if (!clipArrow) {
    clipArrow = new THREE.ArrowHelper(clipAxis, origin, 60, 0xf5c518, 15, 8);
    scene.add(clipArrow);
  }
  clipArrow.position.copy(origin);
  clipArrow.setDirection(clipAxis);

  applyClipPreview();
}

function applyClipPreview() {
  const active = isManualClipMode();
  clipPlaneMesh && (clipPlaneMesh.visible = active);
  clipArrow && (clipArrow.visible = active);
  const planes = active ? [currentClipPlane()] : [];
  for (const mat of currentMeshMaterials) mat.clippingPlanes = planes;
}

document.querySelectorAll('input[name="clip-mode"]').forEach((el) => {
  el.addEventListener("change", () => {
    document.getElementById("manual-clip-controls").classList.toggle("hidden", el.value !== "manual" || !el.checked);
    applyClipPreview();
  });
});

document.querySelectorAll(".axis-buttons button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const [x, y, z] = btn.dataset.axis.split(",").map(Number);
    clipAxis.set(x, y, z);
    document.querySelectorAll(".axis-buttons button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    updateClipWidget();
  });
});

document.getElementById("plane-offset").addEventListener("input", (event) => {
  clipOffset = Number(event.target.value);
  updateClipWidget();
});

function setClipOffsetFromPoint(point) {
  clipOffset = point.dot(clipAxis);
  document.getElementById("plane-offset").value = String(Math.round(clipOffset));
  updateClipWidget();
}

updateClipWidget();

// --- mesh cleanup ---

function updateResampleWidget() {
  const enabled = document.getElementById("resample-mesh").checked;
  document.getElementById("vertex-count").disabled = !enabled;
}

document.getElementById("resample-mesh").addEventListener("change", updateResampleWidget);
updateResampleWidget();

// --- analysis ---

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

document.getElementById("analyze-button").addEventListener("click", async () => {
  if (!sessionId) return;

  const target = document.querySelector('input[name="target"]:checked').value;
  const comTranslation = document.getElementById("com-translation").checked;
  const repairMesh = document.getElementById("repair-mesh").checked;
  const resampleMesh = document.getElementById("resample-mesh").checked;
  const vertexCount = Number(document.getElementById("vertex-count").value) || 10000;

  const body = {
    target,
    landmarks: LANDMARK_NAMES.map((n) => pickedLandmarks[n]),
    com_translation: comTranslation,
    clipping: {},
    harmonize: { n_vertices: resampleMesh ? vertexCount : null, repair: repairMesh },
  };

  if (isManualClipMode()) {
    body.clipping = {
      mode: "manual",
      manual_plane_normal: [clipAxis.x, clipAxis.y, clipAxis.z],
      manual_plane_origin: [clipAxis.x * clipOffset, clipAxis.y * clipOffset, clipAxis.z * clipOffset],
    };
  }

  const statusEl = document.getElementById("job-status");
  statusEl.textContent = "starting...";
  document.getElementById("analyze-button").disabled = true;

  const startResponse = await fetch(`/api/sessions/${sessionId}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!startResponse.ok) {
    statusEl.textContent = `failed to start: ${await startResponse.text()}`;
    updateAnalyzeButtonState();
    return;
  }

  while (true) {
    const response = await fetch(`/api/sessions/${sessionId}/status`);
    const data = await response.json();
    if (data.status === "done") {
      statusEl.textContent = "done.";
      await showResults();
      break;
    }
    if (data.status === "error") {
      statusEl.textContent = `error: ${data.error}`;
      break;
    }
    // live progress - this is the actual current pipeline stage, not a
    // static "please wait" message
    if (data.progress) {
      statusEl.textContent = `${data.progress.stage}${data.progress.detail ? " - " + data.progress.detail : ""}...`;
    }
    await sleep(500);
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
    rows.push(["mean asymmetry index", data.asymmetry.mean_asymmetry_index]);
  }

  const table = document.getElementById("results-table");
  table.innerHTML = "";
  for (const [label, value] of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
    table.appendChild(tr);
  }

  document.getElementById("template-overlay-toggle").checked = false;
  if (shippedTemplates.length === 0) await fetchShippedTemplates();
  populateTemplateSelect();
  await displayResultMesh();
}

// shows the final (post clip/repair/resample) mesh with the landmarks the
// backend actually used and the HC line, if there is one. pulled out of
// showResults() so the template-overlay toggle can get back to this same
// view without re-running the whole analysis.
async function displayResultMesh() {
  await displayMesh(`/api/sessions/${sessionId}/mesh/result`);
  if (!lastResultsData) return;
  for (const p of lastResultsData.landmarks) addResultMarker(p, 0x60a5fa);
  if (lastResultsData.craniometrics) drawHcLine(lastResultsData.craniometrics.hc_slice_polygon);
}

// --- template overlay: compare the final mesh (the one you'd download,
// post clip/repair/resample - "what's in view") against a reference
// template, with X/Y/Z axes and both centers of gravity.

const DEFAULT_TEMPLATE_BY_TARGET = { cranium: "template_xy_com", face: "template_face" };

// whatever template you pick (shipped or custom) gets clipped live, the
// same way the real pipeline clips the patient's mesh - see
// _apply_overlay_clip in api/routers/mesh.py. deliberately NOT using the
// separately-shipped clipped_template_xy(_com).ply files for this: checked
// their actual bounds once and they were clipped ~1.2mm off from where a
// freshly-registered mesh's own landmark plane sits, a leftover from
// however they got baked, and that mismatch only became visible once the
// overlay started comparing clipped-vs-clipped. clipping live means there's
// nothing pre-baked left to drift out of sync.
const CLIP_BY_TARGET = { cranium: "cranial", face: "facial" };

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
// button just silently doing nothing - that's exactly how a real bug here
// slipped through before: create_file_dialog raised (invalid file filter),
// nothing caught the rejection, "choose file(s)" just did nothing at all.
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
    option.textContent = `${t.name} - ${t.description}`;
    select.appendChild(option);
  }
  const customOption = document.createElement("option");
  customOption.value = "custom";
  customOption.textContent = "custom...";
  select.appendChild(customOption);

  const remembered = localStorage.getItem(templateChoiceStorageKey(target));
  select.value = remembered && [...select.options].some((o) => o.value === remembered)
    ? remembered
    : (DEFAULT_TEMPLATE_BY_TARGET[target] || shippedTemplates[0]?.name || "custom");
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

document.getElementById("template-select").addEventListener("change", () => {
  const target = document.querySelector('input[name="target"]:checked').value;
  localStorage.setItem(templateChoiceStorageKey(target), document.getElementById("template-select").value);
  updateTemplateCustomRow();
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
      document.getElementById("template-custom-name").textContent = `couldn't open the file picker: ${msg}`;
    });
    if (!paths || paths.length === 0) return;
    localStorage.setItem(customTemplatePathStorageKey(target), paths[0]);
    updateTemplateCustomRow();
  } else {
    document.getElementById("template-custom-file-input").click();
  }
});

document.getElementById("template-custom-file-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const target = document.querySelector('input[name="target"]:checked').value;
  const formData = new FormData();
  formData.append("files", file);
  const response = await fetch(`/api/templates/custom/upload?clip=${CLIP_BY_TARGET[target]}`, { method: "POST", body: formData });
  if (!response.ok) {
    document.getElementById("template-custom-name").textContent = `upload failed: ${await response.text()}`;
    return;
  }
  if (customTemplateBlobUrl) URL.revokeObjectURL(customTemplateBlobUrl);
  customTemplateBlobUrl = URL.createObjectURL(await response.blob());
  customTemplateBlobName = file.name;
  updateTemplateCustomRow();
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
  const clip = CLIP_BY_TARGET[target];

  if (choice !== "custom") {
    return { object: await loadGlb(`/api/templates/${choice}/mesh?clip=${clip}`), displayName: choice };
  }

  if (isDesktopApp()) {
    const path = localStorage.getItem(customTemplatePathStorageKey(target));
    if (!path) return null;
    return {
      object: await loadGlb(`/api/templates/custom/mesh?path=${encodeURIComponent(path)}&clip=${clip}`),
      displayName: path.split(/[\\/]/).pop(),
    };
  }

  // uploaded via template-custom-file-input above, already clipped for
  // whatever target was active at upload time
  if (!customTemplateBlobUrl) return null;
  return { object: await loadGlb(customTemplateBlobUrl), displayName: customTemplateBlobName };
}

async function enableTemplateOverlay() {
  const resolved = await resolveTemplateForOverlay();
  if (!resolved) {
    document.getElementById("template-offset-info").textContent = "pick a custom template file first.";
    document.getElementById("template-overlay-toggle").checked = false;
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
}

document.getElementById("template-overlay-toggle").addEventListener("change", async (event) => {
  if (!sessionId || !lastResultsData) {
    event.target.checked = false;
    return;
  }
  clearTemplateOverlay();
  if (event.target.checked) {
    await enableTemplateOverlay();
  } else {
    await displayResultMesh();
  }
});

document.getElementById("download-bundle-button").addEventListener("click", async () => {
  if (!sessionId) return;
  const statusEl = document.getElementById("save-status");

  if (isDesktopApp()) {
    statusEl.textContent = "saving...";
    const response = await fetch(`/api/sessions/${sessionId}/save`, { method: "POST" });
    if (response.ok) {
      const data = await response.json();
      statusEl.textContent = `saved to ${data.saved_to}`;
      return;
    }
    // only real reason this 400s is a session that wasn't opened from a real
    // path (shouldn't normally happen in the desktop app, but fall back
    // cleanly rather than leaving the user stuck) - anything else is worth
    // surfacing instead of silently falling back.
    if (response.status !== 400) {
      statusEl.textContent = `save failed: ${await response.text()}`;
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
