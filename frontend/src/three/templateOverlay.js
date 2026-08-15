import * as THREE from "three";

// plain vertex-average centroid across all mesh children - not the
// slice-based center-of-mass the backend uses for craniometrics, just a
// straightforward "middle of all the points" for visually comparing two
// whole meshes. ported from frontend_legacy/app.js's computeCentroid.
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

// billboarded text label for an axis tip - a canvas texture on a sprite,
// same approach as the legacy overlay (no font/TextGeometry loading
// anywhere else in this app).
function makeAxisLabelSprite(text, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = `#${color.toString(16).padStart(6, "0")}`;
  ctx.font = "bold 48px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 32, 34);
  const texture = new THREE.CanvasTexture(canvas);
  return new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false, depthWrite: false }));
}

function addCogMarker(sceneBag, point, color, radius) {
  const marker = new THREE.Mesh(new THREE.SphereGeometry(radius, 16, 16), new THREE.MeshBasicMaterial({ color }));
  marker.position.copy(point);
  sceneBag.scene.add(marker);
  return marker;
}

// adds the template mesh (semi-transparent) plus X/Y/Z axes and both
// centers-of-gravity (+ a dashed line between them) to the scene - same
// visual as legacy's enableTemplateOverlay (app.js:1348-1420), reshaped
// into this codebase's layer-module pattern (a plain function owning its
// own Object3Ds, paired with removeTemplateOverlay below). returns a
// handle to pass to removeTemplateOverlay, plus the mesh/template
// centroid offset (mm) for the panel's readout.
export function addTemplateOverlay({ sceneBag, templateObject, meshObject, markerRadius }) {
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
  sceneBag.scene.add(templateObject);

  const meshCentroid = computeCentroid(meshObject);
  const templateCentroid = computeCentroid(templateObject);

  const box = new THREE.Box3().setFromObject(meshObject);
  box.union(new THREE.Box3().setFromObject(templateObject));
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 1) * 0.7;

  const axesObject = new THREE.Group();
  // Y reaches noticeably less far than X/Z at this same span - the head's
  // vertical extent is usually smaller than its width/depth - stretched
  // 30% just for Y so the upward arrow doesn't look stubby next to the
  // other two.
  const axisDefs = [
    { dir: new THREE.Vector3(1, 0, 0), color: 0xff4d4d, label: "X", span },
    { dir: new THREE.Vector3(0, 1, 0), color: 0x4dff88, label: "Y", span: span * 1.3 },
    { dir: new THREE.Vector3(0, 0, 1), color: 0x4d9fff, label: "Z", span },
  ];
  const labelSize = span * 0.084;
  for (const { dir, color, label, span: axisSpan } of axisDefs) {
    const pts = [dir.clone().multiplyScalar(-axisSpan), dir.clone().multiplyScalar(axisSpan)];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    axesObject.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color })));

    const sprite = makeAxisLabelSprite(label, color);
    sprite.position.copy(dir).multiplyScalar(axisSpan * 1.1);
    sprite.scale.set(labelSize, labelSize, 1);
    axesObject.add(sprite);
  }
  sceneBag.scene.add(axesObject);

  const cogMeshMarker = addCogMarker(sceneBag, meshCentroid, 0xffa500, markerRadius * 1.4);
  const cogTemplateMarker = addCogMarker(sceneBag, templateCentroid, 0x60a5fa, markerRadius * 1.4);

  const lineGeo = new THREE.BufferGeometry().setFromPoints([meshCentroid, templateCentroid]);
  const cogLine = new THREE.Line(lineGeo, new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 3, gapSize: 2 }));
  cogLine.computeLineDistances();
  sceneBag.scene.add(cogLine);

  const offset = new THREE.Vector3().subVectors(meshCentroid, templateCentroid);

  return {
    handle: { templateObject, axesObject, cogMeshMarker, cogTemplateMarker, cogLine },
    offset: { x: offset.x, y: offset.y, z: offset.z, total: offset.length() },
  };
}

// disposes the axes/CoG-marker extras only, leaving handle.templateObject
// in the scene untouched - used when a NICP fit is about to repurpose the
// exact mesh the "compare to template" checkbox was already showing as its
// deforming preview (see Viewer.jsx's updateNicpPreview). the axes/CoG
// markers are a snapshot of the pre-deformation centroid, so they'd be
// actively misleading once the mesh starts moving, but there's no reason
// to reload a fresh copy of the template mesh itself when the one already
// on screen can just be recolored and repurposed.
export function removeTemplateOverlayExtras(sceneBag, handle) {
  if (!handle) return;
  for (const obj of [handle.axesObject, handle.cogMeshMarker, handle.cogTemplateMarker, handle.cogLine]) {
    if (!obj) continue;
    sceneBag.scene.remove(obj);
    obj.traverse((child) => {
      // sprites share a single static geometry across every instance
      // (three.js's Sprite._geometry) - disposing it here would break
      // every other sprite that ever gets created, not just this one.
      if (!child.isSprite) child.geometry?.dispose();
      child.material?.map?.dispose();
      child.material?.dispose();
    });
  }
}

export function removeTemplateOverlay(sceneBag, handle) {
  if (!handle) return;
  removeTemplateOverlayExtras(sceneBag, handle);
  if (handle.templateObject) {
    sceneBag.scene.remove(handle.templateObject);
    handle.templateObject.traverse((child) => {
      if (!child.isMesh) return;
      child.geometry?.dispose();
      child.material?.dispose();
    });
  }
}
