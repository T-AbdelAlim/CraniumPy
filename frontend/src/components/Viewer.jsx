import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useThreeScene } from "../three/useThreeScene.js";
import { applyTextureState, applyWireframeState, disposeMesh, displayMesh as displayMeshImpl } from "../three/meshDisplay.js";
import { pointerToNdc, raycastMesh, raycastMarkers } from "../three/picking.js";
import { syncLandmarkMarkers, disposeLandmarkMarkers } from "../three/landmarksLayer.js";

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
  const draggingNameRef = useRef(null);
  const onPickRef = useRef(onPick);
  const onDragRef = useRef(onDrag);

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    onDragRef.current = onDrag;
  }, [onDrag]);

  useEffect(() => {
    gltfLoaderRef.current = new GLTFLoader();
    raycasterRef.current = new THREE.Raycaster();
    return () => {
      disposeMesh(meshStateRef.current.object);
      disposeLandmarkMarkers(markersRef);
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
      return displayMeshImpl({
        sceneBag: sceneBagRef.current,
        gltfLoader: gltfLoaderRef.current,
        meshStateRef,
        url,
        selectionHasTexture,
      });
    },
  }));

  return (
    <div ref={containerRef} className="viewer-container">
      <canvas ref={canvasRef} className="viewer-canvas" />
    </div>
  );
});

export default Viewer;
