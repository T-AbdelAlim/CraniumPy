import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useThreeScene } from "../three/useThreeScene.js";
import { applyOpacityState, applyTextureState, applyWireframeState, disposeMesh, displayMesh as displayMeshImpl, loadGlb, updateObjectGeometry } from "../three/meshDisplay.js";
import { pointerToNdc, raycastMesh, raycastMarkers } from "../three/picking.js";
import { syncLandmarkMarkers, disposeLandmarkMarkers } from "../three/landmarksLayer.js";
import { addTemplateOverlay, removeTemplateOverlay, removeTemplateOverlayExtras } from "../three/templateOverlay.js";
import { addMeasurementsOverlay, removeMeasurementsOverlay, applyHeatmap, removeHeatmap } from "../three/measurementsLayer.js";
import { addMetopicOverlay, removeMetopicOverlay } from "../three/metopicOverlay.js";
import { addFrontalBossingOverlay, removeFrontalBossingOverlay } from "../three/frontalBossingOverlay.js";
import { addNodesOverlay, removeNodesOverlay, resyncNodesGeometry } from "../three/nicpFitVisualization.js";

// deforming-template color during a live NICP fit - matches the --hc red
// token already used elsewhere in this app, so "moving/deforming" reads as
// a consistent color across the UI rather than introducing a new one.
const NICP_DEFORM_COLOR = 0xd1453d;
// same beige plainMaterial() (three/meshDisplay.js) uses - the target/
// patient mesh's node dots use this regardless of whatever material the
// mesh actually has on (plain, textured, vertex-colored) - this is a
// technical visualization aid during a fit, not meant to track the mesh's
// real appearance.
const TARGET_NODE_COLOR = 0xe8d9c0;
// Analysis workspace's starting mesh opacity, whenever a measurements/
// heatmap/metopic overlay first shows - the user's own opacity slider
// (App.jsx's analysisMeshOpacity, via setMeshOpacity) immediately overrides
// this on every subsequent render, but this is what a fresh overlay shows
// before that ever fires.
const ANALYSIS_DEFAULT_MESH_OPACITY = 0.35;

// reusable viewer: knows how to load and show a GLB and nothing else - no
// sessions, no fetch, no upload, no landmark *naming*. wireframe/
// textureEnabled/landmarks are controlled props (state-shaped, react to
// changes like any other prop); displayMesh is exposed imperatively
// (action-shaped - a one-shot load that needs to report back whether the
// mesh actually has a texture, which is only known after parsing it).
// onPick/onDrag are event-shaped callback props - things that *happen* in
// the viewer, reported outward, same as an onClick. later layers (HC-line,
// heatmap, template overlay) follow the same split as they're added.
const Viewer = forwardRef(function Viewer({ wireframe, textureEnabled, landmarks, landmarkColors, onPick, onDrag }, ref) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const sceneBagRef = useThreeScene(canvasRef, containerRef);
  const gltfLoaderRef = useRef(null);
  const raycasterRef = useRef(null);
  const meshStateRef = useRef({ object: null, materials: [], markerRadius: 2 });
  const markersRef = useRef({});
  const templateOverlayRef = useRef(null);
  // bumped on every operation that changes what templateOverlayRef "owns"
  // (a fresh showTemplateOverlay call, hiding it, a mesh swap, or the NICP
  // preview repurposing it) - showTemplateOverlay checks this after its own
  // async GLB load resolves, so a call superseded by a newer one (or a
  // reset) while still loading just discards its result instead of adding
  // a second template object nothing then owns/cleans up. see
  // showTemplateOverlay's own comment for the race this fixes.
  const templateOverlayTokenRef = useRef(0);
  const measurementsOverlayRef = useRef(null);
  const metopicOverlayRef = useRef(null);
  const frontalBossingOverlayRef = useRef(null);
  const nicpPreviewRef = useRef(null);
  const nicpPreviewNodesRef = useRef(null);
  const mainMeshNodesRef = useRef(null);
  const draggingNameRef = useRef(null);
  const onPickRef = useRef(onPick);
  const onDragRef = useRef(onDrag);
  const wireframeRef = useRef(wireframe);

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    onDragRef.current = onDrag;
  }, [onDrag]);

  // read by hideNicpPreview to restore the patient mesh's wireframe state
  // to whatever the checkbox actually says, rather than assuming it was
  // off before the fit forced it on.
  useEffect(() => {
    wireframeRef.current = wireframe;
  }, [wireframe]);

  useEffect(() => {
    gltfLoaderRef.current = new GLTFLoader();
    raycasterRef.current = new THREE.Raycaster();
    return () => {
      disposeMesh(meshStateRef.current.object);
      disposeLandmarkMarkers(markersRef);
      if (sceneBagRef.current) {
        removeTemplateOverlay(sceneBagRef.current, templateOverlayRef.current);
        removeMeasurementsOverlay(sceneBagRef.current, measurementsOverlayRef.current);
        removeMetopicOverlay(sceneBagRef.current, metopicOverlayRef.current);
        removeFrontalBossingOverlay(sceneBagRef.current, frontalBossingOverlayRef.current);
        if (nicpPreviewRef.current) sceneBagRef.current.scene.remove(nicpPreviewRef.current);
      }
      removeNodesOverlay(nicpPreviewNodesRef.current);
      removeNodesOverlay(mainMeshNodesRef.current);
      disposeMesh(nicpPreviewRef.current);
    };
  }, []);

  useEffect(() => {
    applyWireframeState(meshStateRef, wireframe);
  }, [wireframe]);

  useEffect(() => {
    applyTextureState(meshStateRef, textureEnabled);
    applyWireframeState(meshStateRef, wireframe);
  }, [textureEnabled]);

  useEffect(() => {
    const sceneBag = sceneBagRef.current;
    if (!sceneBag) return;
    syncLandmarkMarkers({ sceneBag, markersRef, landmarks, colors: landmarkColors, radius: meshStateRef.current.markerRadius });
  }, [landmarks, landmarkColors]);

  // ctrl/cmd-click to place, alt-drag to reposition. listeners attach once
  // and read the latest callbacks/mesh/markers through refs (kept fresh by
  // the small effects above) instead of re-attaching on every prop change.
  useEffect(() => {
    const canvas = canvasRef.current;

    function handleClick(event) {
      if (!(event.ctrlKey || event.metaKey)) return; // plain click still orbits
      const sceneBag = sceneBagRef.current;
      const meshObject = meshStateRef.current.object;
      if (!sceneBag || !meshObject || !onPickRef.current) return;
      const ndc = pointerToNdc(event, canvas);
      const point = raycastMesh(raycasterRef.current, sceneBag.camera, ndc, meshObject);
      if (point) onPickRef.current({ x: point.x, y: point.y, z: point.z });
    }

    function handleMouseDown(event) {
      if (!event.altKey || event.button !== 0) return;
      const sceneBag = sceneBagRef.current;
      if (!sceneBag || !onDragRef.current) return;
      const ndc = pointerToNdc(event, canvas);
      const name = raycastMarkers(raycasterRef.current, sceneBag.camera, ndc, markersRef.current);
      if (!name) return;
      draggingNameRef.current = name;
      sceneBag.controls.enabled = false;
      event.preventDefault();
    }

    function handleMouseMove(event) {
      const name = draggingNameRef.current;
      if (!name) return;
      const sceneBag = sceneBagRef.current;
      const meshObject = meshStateRef.current.object;
      if (!sceneBag || !meshObject || !onDragRef.current) return;
      const ndc = pointerToNdc(event, canvas);
      const point = raycastMesh(raycasterRef.current, sceneBag.camera, ndc, meshObject);
      if (point) onDragRef.current(name, { x: point.x, y: point.y, z: point.z });
    }

    function handleMouseUp() {
      if (!draggingNameRef.current) return;
      draggingNameRef.current = null;
      if (sceneBagRef.current) sceneBagRef.current.controls.enabled = true;
    }

    canvas.addEventListener("click", handleClick);
    canvas.addEventListener("mousedown", handleMouseDown);
    canvas.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      canvas.removeEventListener("click", handleClick);
      canvas.removeEventListener("mousedown", handleMouseDown);
      canvas.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  useImperativeHandle(ref, () => ({
    async displayMesh(url, { selectionHasTexture }) {
      // whatever the template/measurements overlay was comparing against
      // is about to be disposed - drop them (and the heatmap, which holds
      // a direct reference to the old mesh's material) rather than leave
      // them pointing at a stale/disposed mesh; the caller re-shows
      // whichever were on once the new mesh is in.
      templateOverlayTokenRef.current++;
      if (sceneBagRef.current) {
        removeTemplateOverlay(sceneBagRef.current, templateOverlayRef.current);
        removeMeasurementsOverlay(sceneBagRef.current, measurementsOverlayRef.current);
        removeMetopicOverlay(sceneBagRef.current, metopicOverlayRef.current);
        removeFrontalBossingOverlay(sceneBagRef.current, frontalBossingOverlayRef.current);
        if (nicpPreviewRef.current) sceneBagRef.current.scene.remove(nicpPreviewRef.current);
      }
      templateOverlayRef.current = null;
      measurementsOverlayRef.current = null;
      metopicOverlayRef.current = null;
      frontalBossingOverlayRef.current = null;
      removeNodesOverlay(nicpPreviewNodesRef.current);
      nicpPreviewNodesRef.current = null;
      removeNodesOverlay(mainMeshNodesRef.current);
      mainMeshNodesRef.current = null;
      disposeMesh(nicpPreviewRef.current);
      nicpPreviewRef.current = null;
      return displayMeshImpl({
        sceneBag: sceneBagRef.current,
        gltfLoader: gltfLoaderRef.current,
        meshStateRef,
        url,
        selectionHasTexture,
      });
    },
    // a live NICP fit's deforming template, as its own standalone object -
    // rendered as a red wireframe + vertex-node cloud (see
    // three/nicpFitVisualization.js), so the topology visibly adopts the
    // patient's shape rather than just a solid surface warping. if
    // "compare to template" was already showing a template mesh, THAT
    // exact object is repurposed here rather than spawning a visually
    // duplicate second one - it's the same mesh, just recolored and now
    // being deformed instead of held static; its axes/CoG markers get
    // dropped first since they'd be stale the moment the mesh starts
    // moving. the patient's own mesh gets the same wireframe+nodes
    // treatment (in its own existing color, just dimmed) so both objects
    // read as "topology adopting a shape" the same way. first call sets
    // all of this up; every call after that just swaps the deforming
    // object's geometry in place (no re-add, no flicker) and re-points its
    // node cloud at the new geometry.
    async updateNicpPreview(url) {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      if (!nicpPreviewRef.current) {
        let object;
        if (templateOverlayRef.current) {
          templateOverlayTokenRef.current++;
          object = templateOverlayRef.current.templateObject;
          removeTemplateOverlayExtras(sceneBag, templateOverlayRef.current);
          templateOverlayRef.current = null;
        } else {
          object = await loadGlb(gltfLoaderRef.current, url);
          sceneBag.scene.add(object);
        }
        object.traverse((child) => {
          if (!child.isMesh) return;
          child.geometry.computeVertexNormals();
          child.material?.dispose();
          child.material = new THREE.MeshBasicMaterial({
            color: NICP_DEFORM_COLOR,
            wireframe: true,
            transparent: true,
            opacity: 0.35,
            side: THREE.DoubleSide,
            depthWrite: false,
          });
        });
        nicpPreviewRef.current = object;
        nicpPreviewNodesRef.current = addNodesOverlay(object, NICP_DEFORM_COLOR, meshStateRef.current.markerRadius * 0.4);

        applyWireframeState(meshStateRef, true);
        applyOpacityState(meshStateRef, 0.75);
        if (meshStateRef.current.object && !mainMeshNodesRef.current) {
          mainMeshNodesRef.current = addNodesOverlay(
            meshStateRef.current.object,
            TARGET_NODE_COLOR,
            meshStateRef.current.markerRadius * 0.4,
          );
        }
      } else {
        await updateObjectGeometry({ gltfLoader: gltfLoaderRef.current, targetObject: nicpPreviewRef.current, url });
        resyncNodesGeometry(nicpPreviewNodesRef.current);
      }
    },
    hideNicpPreview() {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag || !nicpPreviewRef.current) return;
      sceneBag.scene.remove(nicpPreviewRef.current);
      disposeMesh(nicpPreviewRef.current);
      nicpPreviewRef.current = null;
      removeNodesOverlay(nicpPreviewNodesRef.current);
      nicpPreviewNodesRef.current = null;
      removeNodesOverlay(mainMeshNodesRef.current);
      mainMeshNodesRef.current = null;
      applyWireframeState(meshStateRef, wireframeRef.current);
      applyOpacityState(meshStateRef, 1.0);
    },
    // loads a template GLB and adds it (+ axes, CoG markers) alongside
    // whatever mesh is currently shown - returns the mesh/template centroid
    // offset (mm) for the panel's readout, or null if there's no mesh to
    // compare against yet.
    // the caller (App.jsx's compare-to-template effect) can fire this again
    // - a different template picked, a fresh pipeline run - before a
    // previous call's GLB load has even resolved, since neither this
    // method nor the effect await/cancel each other. the token makes only
    // the LATEST call actually win: an earlier call whose load resolves
    // after being superseded just disposes what it loaded instead of
    // adding a second template object that templateOverlayRef then has no
    // way to track/remove - that was the "two templates on top of each
    // other, two axes systems" bug.
    async showTemplateOverlay(url) {
      const sceneBag = sceneBagRef.current;
      const meshObject = meshStateRef.current.object;
      if (!sceneBag || !meshObject) return null;
      const token = ++templateOverlayTokenRef.current;
      const templateObject = await loadGlb(gltfLoaderRef.current, url);
      if (token !== templateOverlayTokenRef.current) {
        disposeMesh(templateObject);
        return null;
      }
      removeTemplateOverlay(sceneBag, templateOverlayRef.current);
      const { handle, offset } = addTemplateOverlay({
        sceneBag,
        templateObject,
        meshObject,
        markerRadius: meshStateRef.current.markerRadius,
      });
      templateOverlayRef.current = handle;
      return offset;
    },
    hideTemplateOverlay() {
      const sceneBag = sceneBagRef.current;
      templateOverlayTokenRef.current++;
      if (!sceneBag) return;
      removeTemplateOverlay(sceneBag, templateOverlayRef.current);
      templateOverlayRef.current = null;
    },
    // HC-slice ring + BPD/OFD spans, live on the currently-shown (cranial)
    // result mesh - the Analysis workspace's cranial visualization. dims
    // the mesh so a line running along the far side of the surface doesn't
    // just disappear into it - the user's own opacity slider (App.jsx's
    // analysisMeshOpacity) takes over immediately after via setMeshOpacity.
    showMeasurementsOverlay({ hcPolygon, frontOpt, occOpt, lhOpt, rhOpt }) {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeMeasurementsOverlay(sceneBag, measurementsOverlayRef.current);
      measurementsOverlayRef.current = addMeasurementsOverlay({
        sceneBag,
        hcPolygon,
        frontOpt,
        occOpt,
        lhOpt,
        rhOpt,
        markerRadius: meshStateRef.current.markerRadius * 1.2,
      });
      applyOpacityState(meshStateRef, ANALYSIS_DEFAULT_MESH_OPACITY);
    },
    hideMeasurementsOverlay() {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeMeasurementsOverlay(sceneBag, measurementsOverlayRef.current);
      measurementsOverlayRef.current = null;
      applyOpacityState(meshStateRef, 1.0);
    },
    // per-vertex asymmetry heatmap on the currently-shown (facial) result
    // mesh - the Analysis workspace's facial visualization. applyHeatmap
    // tints whichever material(s) are already assigned in place (see its
    // own docstring) rather than swapping in new ones, so
    // meshStateRef.current.materials already points at the right objects -
    // no rebuild needed the way texture toggling needs one.
    showHeatmap(heatmap) {
      const meshObject = meshStateRef.current.object;
      if (!meshObject) return;
      applyHeatmap(meshObject, heatmap);
      applyOpacityState(meshStateRef, ANALYSIS_DEFAULT_MESH_OPACITY);
    },
    hideHeatmap() {
      removeHeatmap(meshStateRef.current.object);
      applyOpacityState(meshStateRef, 1.0);
    },
    // forehead contour + fitted parabola + regions + frontal-angle
    // construction, live on the currently-shown (facial) result mesh -
    // the Analysis workspace's metopic/frontal-shape visualization,
    // mutually exclusive with the heatmap above (see App.jsx's
    // analysisViewMode). same dim-the-mesh treatment as the other two
    // overlays, so the contour/regions read clearly against the surface.
    showMetopicOverlay(metopic) {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeMetopicOverlay(sceneBag, metopicOverlayRef.current);
      metopicOverlayRef.current = addMetopicOverlay({
        sceneBag,
        metopic,
        markerRadius: meshStateRef.current.markerRadius * 1.2,
      });
      applyOpacityState(meshStateRef, ANALYSIS_DEFAULT_MESH_OPACITY);
    },
    hideMetopicOverlay() {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeMetopicOverlay(sceneBag, metopicOverlayRef.current);
      metopicOverlayRef.current = null;
      applyOpacityState(meshStateRef, 1.0);
    },
    // sellion -> forehead-point angle, live on whichever result mesh is
    // currently shown (cranial or facial) - unlike the heatmap/metopic pair
    // above, this one isn't mutually exclusive with anything: it shows
    // alongside the HC/BPD/OFD overlay on a cranial target, or alongside
    // the heatmap/metopic overlay on a facial one. doesn't touch mesh
    // opacity itself - whichever of those already dimmed the mesh owns that.
    showFrontalBossingOverlay(frontalBossing) {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeFrontalBossingOverlay(sceneBag, frontalBossingOverlayRef.current);
      frontalBossingOverlayRef.current = addFrontalBossingOverlay({
        sceneBag,
        frontalBossing,
        markerRadius: meshStateRef.current.markerRadius * 1.2,
      });
    },
    hideFrontalBossingOverlay() {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;
      removeFrontalBossingOverlay(sceneBag, frontalBossingOverlayRef.current);
      frontalBossingOverlayRef.current = null;
    },
    // the Analysis workspace's opacity slider - only ever touches the
    // mesh's own material(s), never the measurement/heatmap/metopic
    // overlay objects (separate Object3Ds with their own materials, see
    // measurementsLayer.js/metopicOverlay.js) - so dragging it makes the
    // surface more see-through without fading the lines/markers drawn on
    // top of it.
    setMeshOpacity(value) {
      applyOpacityState(meshStateRef, value);
    },
  }));

  return (
    <div ref={containerRef} className="viewer-container">
      <canvas ref={canvasRef} className="viewer-canvas" />
    </div>
  );
});

export default Viewer;
