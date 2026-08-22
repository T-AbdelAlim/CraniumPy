import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useThreeScene } from "../../three/useThreeScene.js";
import { loadGlb, disposeMesh, plainMaterial, applyOpacityState } from "../../three/meshDisplay.js";
import { applyHeatmap, heatmapMaxAbs, removeHeatmap } from "../../three/measurementsLayer.js";
import { addMeasurementsOverlay, removeMeasurementsOverlay } from "../../three/measurementsLayer.js";
import { addMetopicOverlay, removeMetopicOverlay } from "../../three/metopicOverlay.js";
import { addFrontalBossingOverlay, removeFrontalBossingOverlay } from "../../three/frontalBossingOverlay.js";
import { lerpStageOverlays } from "./lib/overlayMorph.js";

function firstMesh(object3D) {
  let found = null;
  object3D.traverse((child) => {
    if (!found && child.isMesh) found = child;
  });
  return found;
}

// a fixed marker size (mm), not derived from the mesh's own bounding box -
// same default Viewer.jsx's own meshStateRef starts every instance at
// (markerRadius: 2), * 1.2 for these three overlay types specifically,
// matching that file's own showMeasurementsOverlay/showMetopicOverlay/
// showFrontalBossingOverlay calls.
const OVERLAY_MARKER_RADIUS = 2 * 1.2;

// tried in order - MediaRecorder's own support is entirely up to the
// browser engine, no way to force a codec that isn't there. mp4/avc1 first
// since it's the one format that plays back everywhere with zero fuss
// (every OS's own media player, every video-sharing site) once a browser
// supports it at all (Chromium has since ~2023, which covers both this
// app's own desktop window - pywebview's WebView2 - and any modern browser
// tab); webm/vp9 is the fallback for whichever engine doesn't.
const VIDEO_MIME_CANDIDATES = [
  "video/mp4;codecs=avc1.640028",
  "video/mp4",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
  "video/webm",
];

function pickSupportedVideoMimeType() {
  if (typeof MediaRecorder === "undefined") return null;
  return VIDEO_MIME_CANDIDATES.find((mime) => MediaRecorder.isTypeSupported(mime)) ?? null;
}

// a standalone Three.js viewer, deliberately NOT built on Viewer.jsx - the
// morph animation needs a persistent, directly-mutable geometry (the same
// BufferAttribute lerped in place every frame/scrub) which would fight
// Viewer.jsx's own invariant that displayMesh always fully replaces the
// previous mesh (see that component's meshStateRef). owns its own
// useThreeScene instance instead - proven safe to mount concurrently
// alongside other Viewer/scene instances (see useThreeScene.js's own
// comment on why every instance is fully independent).
//
// loadSequence(urls) loads every GLB in order (2 or more - a plain 2-point
// comparison is just the 1-leg case of the same thing), keeps the FIRST
// mesh's own geometry as the thing actually displayed/animated, and just
// the raw vertex position arrays from all of them (mesh_to_glb always
// produces a single-mesh GLB with a stable vertex order, so a simple flat
// Float32Array per timepoint is enough - no need to keep any Object3D but
// the first one around once positions are copied out). setT(t) maps t in
// [0,1] across however many legs there are (urls.length - 1) and lerps
// between whichever consecutive pair t currently falls between - 0 = fully
// the first timepoint, 1 = fully the last, with every timepoint in between
// actually visited along the way. meaningful only because every timepoint
// shares the same vertex count/order (the same point-correspondence
// guarantee NICP template-fitting provides - every mesh this workspace
// loads is already fit to a shared template before it gets here, see
// TimepointSlot.jsx's own comment).
//
// showMeasurementsOverlaySequence/showMetopicOverlaySequence/
// showFrontalBossingOverlaySequence take one ALREADY-RESAMPLED descriptor
// PER STAGE (see lib/overlayMorph.js's resampleStageOverlays - resampling
// happens once, up front, when the sequence loads, never per frame) and
// lerp between the current leg's own pair every frame, the same way the
// mesh vertices and heatmap already do - see applyCurrentFrame.
const LongitudinalMorphViewer = forwardRef(function LongitudinalMorphViewer(_props, ref) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const sceneBagRef = useThreeScene(canvasRef, containerRef);
  const gltfLoaderRef = useRef(null);
  const stateRef = useRef(null);
  const recorderRef = useRef(null); // {recorder, chunks, previousPixelRatio, mimeType}

  function disposeOverlayGroups(state) {
    const sceneBag = sceneBagRef.current;
    if (!sceneBag || !state) return;
    removeMeasurementsOverlay(sceneBag, state.measurementsGroup);
    removeMetopicOverlay(sceneBag, state.metopicGroup);
    removeFrontalBossingOverlay(sceneBag, state.frontalBossingGroup);
  }

  useEffect(() => {
    gltfLoaderRef.current = new GLTFLoader();
    return () => {
      const sceneBag = sceneBagRef.current;
      if (sceneBag && stateRef.current) {
        sceneBag.scene.remove(stateRef.current.object);
      }
      disposeOverlayGroups(stateRef.current);
      disposeMesh(stateRef.current?.object);
      stateRef.current = null;
      // an export mid-flight when this unmounts (switching tabs) would
      // otherwise leave a MediaRecorder running against a canvas that's
      // about to be disposed.
      if (recorderRef.current) {
        recorderRef.current.recorder.stop();
        recorderRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => {
    // shared by setT/showHeatmapSequence/show*OverlaySequence below so all
    // of them go through the exact same per-leg math - recomputes the
    // current frame's vertex positions, heatmap tint (if any), and overlay
    // geometry (if any) from stateRef.current.lastT.
    function applyCurrentFrame() {
      const state = stateRef.current;
      if (!state) return;
      const { mesh, positions, lastT } = state;
      const legs = positions.length - 1;
      const scaled = lastT * legs;
      let legIndex = Math.floor(scaled);
      if (legIndex >= legs) legIndex = legs - 1;
      if (legIndex < 0) legIndex = 0;
      const localT = scaled - legIndex;
      const posA = positions[legIndex];
      const posB = positions[legIndex + 1];
      const out = mesh.geometry.attributes.position;
      for (let i = 0; i < out.array.length; i++) {
        out.array[i] = posA[i] + localT * (posB[i] - posA[i]);
      }
      out.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
      mesh.geometry.computeBoundingSphere();

      // the heatmap (if one's showing) rescales right along with this leg's
      // own interpolation - a true lerp between the two ADJACENT STAGES' own
      // per-vertex heatmaps (asymmetry, or a "distance" diff against
      // whatever reference the 3D Morphing tab's picked - see
      // lib/distanceHeatmap.js), not a scale-from-zero: neither endpoint's
      // own heatmap is generally zero (asymmetry in particular is a
      // property of that ONE mesh, unrelated to its neighbors), so ramping
      // from white at the start of every leg would misrepresent it. skips
      // tinting entirely for a leg where either endpoint has no heatmap at
      // all (e.g. "longitudinal timing" mode's first stage, which has no
      // predecessor to diff against).
      if (state.stageHeatmaps) {
        const hA = state.stageHeatmaps[legIndex];
        const hB = state.stageHeatmaps[legIndex + 1];
        if (hA && hB) {
          const lerped = hA.map((v, i) => v + (hB[i] - v) * localT);
          applyHeatmap(state.object, lerped, state.heatmapMaxAbs);
        } else {
          removeHeatmap(state.object);
        }
      }

      // measurements/metopic/frontal-bossing overlays lerp the same way -
      // rebuilding a handful of thin line/marker primitives (a few dozen
      // vertices total) every frame is negligible next to the mesh's own
      // vertex lerp above (typically thousands of vertices), so this just
      // reuses the existing add*Overlay functions as-is rather than hand-
      // rolling in-place geometry mutation for them too.
      if (state.overlaySequence) {
        const sceneBag = sceneBagRef.current;
        disposeOverlayGroups(state);
        state.measurementsGroup = null;
        state.metopicGroup = null;
        state.frontalBossingGroup = null;
        const lerped = lerpStageOverlays(state.overlaySequence[legIndex], state.overlaySequence[legIndex + 1], localT);
        if (sceneBag && lerped.craniometrics && lerped.craniometrics.hcPolygon) {
          state.measurementsGroup = addMeasurementsOverlay({
            sceneBag,
            hcPolygon: lerped.craniometrics.hcPolygon,
            frontOpt: lerped.craniometrics.frontOpt,
            occOpt: lerped.craniometrics.occOpt,
            lhOpt: lerped.craniometrics.lhOpt,
            rhOpt: lerped.craniometrics.rhOpt,
            markerRadius: OVERLAY_MARKER_RADIUS,
          });
        }
        if (sceneBag && lerped.metopic) {
          state.metopicGroup = addMetopicOverlay({ sceneBag, metopic: lerped.metopic, markerRadius: OVERLAY_MARKER_RADIUS });
        }
        if (sceneBag && lerped.frontalBossing) {
          state.frontalBossingGroup = addFrontalBossingOverlay({
            sceneBag, frontalBossing: lerped.frontalBossing, markerRadius: OVERLAY_MARKER_RADIUS,
          });
        }
      }
    }

    return {
      async loadSequence(urls) {
        const sceneBag = sceneBagRef.current;
        if (!sceneBag) return;
        if (urls.length < 2) throw new Error("need at least two timepoints to morph between");

        const objects = await Promise.all(urls.map((url) => loadGlb(gltfLoaderRef.current, url)));
        const meshes = objects.map(firstMesh);
        const positionsList = meshes.map((m) => m.geometry.attributes.position.array);
        const vertexCount = positionsList[0].length;
        if (positionsList.some((p) => p.length !== vertexCount)) {
          objects.forEach(disposeMesh);
          throw new Error("vertex count mismatch across timepoints - every timepoint must share the same point correspondence");
        }

        if (stateRef.current) {
          sceneBag.scene.remove(stateRef.current.object);
          disposeOverlayGroups(stateRef.current);
          disposeMesh(stateRef.current.object);
        }
        const [displayObject] = objects;
        const displayMesh = meshes[0];
        displayMesh.geometry.computeVertexNormals();
        displayMesh.material = plainMaterial();
        objects.slice(1).forEach(disposeMesh); // only their position arrays were needed, already copied below

        sceneBag.scene.add(displayObject);
        sceneBag.fitCameraToObject(displayObject);
        stateRef.current = {
          object: displayObject,
          mesh: displayMesh,
          positions: positionsList.map((p) => p.slice()),
          lastT: 0,
          stageHeatmaps: null,
          heatmapMaxAbs: 0,
          overlaySequence: null,
          measurementsGroup: null,
          metopicGroup: null,
          frontalBossingGroup: null,
        };
      },
      setT(t) {
        const state = stateRef.current;
        if (!state) return;
        state.lastT = Math.max(0, Math.min(1, t));
        applyCurrentFrame();
      },
      // heatmaps: one per-vertex heatmap PER STAGE (length === positions.length,
      // one per timepoint, not per leg) - e.g. each stage's own asymmetry
      // heatmap, or its own "distance" diff against whatever reference the
      // 3D Morphing tab picked (see lib/distanceHeatmap.js). null entries
      // are allowed (a stage with nothing meaningful to show - see
      // applyCurrentFrame's own null-either-endpoint handling). fixedMaxAbs
      // is the largest |deviation| seen across every non-null stage, shared
      // by all of them, so the color scale itself stays constant through
      // the whole playback - see applyHeatmap's own comment for why a
      // heatmap that's been scaled down must not renormalize against its
      // own (now smaller) max.
      showHeatmapSequence(heatmaps) {
        const state = stateRef.current;
        if (!state) return;
        state.stageHeatmaps = heatmaps;
        state.heatmapMaxAbs = Math.max(...heatmaps.filter(Boolean).map((h) => heatmapMaxAbs(h)), 1e-6);
        applyCurrentFrame();
      },
      hideHeatmap() {
        const state = stateRef.current;
        if (!state) return;
        state.stageHeatmaps = null;
        removeHeatmap(state.object);
      },
      // overlaySequence: one lib/overlayMorph.js resampleStageOverlays()
      // descriptor PER STAGE (length === positions.length, one per
      // timepoint, not per leg) - applyCurrentFrame lerps between
      // whichever consecutive pair the current leg spans.
      showOverlaySequence(overlaySequence) {
        const state = stateRef.current;
        if (!state) return;
        state.overlaySequence = overlaySequence;
        applyCurrentFrame();
      },
      hideOverlaySequence() {
        const state = stateRef.current;
        if (!state) return;
        state.overlaySequence = null;
        disposeOverlayGroups(state);
        state.measurementsGroup = null;
        state.metopicGroup = null;
        state.frontalBossingGroup = null;
      },
      // the opacity slider (3D Morphing tab) - only ever touches the mesh's
      // own material, never the heatmap tint or the overlay lines/markers,
      // same split Viewer.jsx's own setMeshOpacity already keeps.
      setMeshOpacity(value) {
        const state = stateRef.current;
        if (!state) return;
        applyOpacityState({ current: { object: state.object, materials: [state.mesh.material] } }, value);
      },
      // the Longitudinal workspace's camera-link feature (see
      // workspaces/longitudinal/lib/useLinkedCameras.js) - same shape as
      // Viewer.jsx's own getControls/getCameraState/setCameraState, so the
      // linking hook can treat this and an ordinary Viewer instance
      // identically.
      getControls() {
        return sceneBagRef.current?.controls ?? null;
      },
      getCameraState() {
        const sceneBag = sceneBagRef.current;
        if (!sceneBag) return null;
        return { position: sceneBag.camera.position.toArray(), target: sceneBag.controls.target.toArray() };
      },
      setCameraState({ position, target }) {
        const sceneBag = sceneBagRef.current;
        if (!sceneBag) return;
        sceneBag.camera.position.fromArray(position);
        sceneBag.controls.target.fromArray(target);
        sceneBag.controls.update();
      },
      // fullscreen - the container div (canvas + legend + anything else
      // overlaid on it), not just the bare canvas, so the legend/markers
      // still show while fullscreen. standard Fullscreen API, works in both
      // a real browser tab and the desktop app's own WebView2 window - no
      // library needed.
      requestFullscreen() {
        containerRef.current?.requestFullscreen?.();
      },
      exitFullscreen() {
        if (document.fullscreenElement) document.exitFullscreen?.();
      },
      isFullscreenElement() {
        return document.fullscreenElement === containerRef.current;
      },
      // exports the morph animation as a video clip, captured straight off
      // this canvas via the browser's own MediaRecorder - no export library,
      // no server round-trip, no extra dependency: the render loop
      // (useThreeScene.js's own requestAnimationFrame call) is already
      // continuously redrawing this canvas every frame regardless,
      // captureStream(fps) just taps that as a live video source. pairs with
      // stopRecording() below - the caller (MorphControl.jsx) starts this,
      // drives its own t sweep exactly as if it were animating normally
      // (setT already applies to whatever's being recorded, live), then
      // stops it once the sweep finishes.
      //
      // pixelRatio temporarily renders at a higher resolution than the
      // canvas's own on-screen CSS size (a plain WebGLRenderer defaults to a
      // 1:1 pixel ratio, so the exported clip would otherwise be exactly as
      // low-res as this one small viewport panel) - restored the moment
      // recording stops, so the live on-screen viewer itself is never
      // affected outside the export. the canvas's own on-screen CSS size
      // must also stay CONSTANT for the whole recording, or captureStream's
      // video track resolution changes mid-stream and MediaRecorder
      // produces a corrupted file - see the 3D Morphing tab's own layout
      // comment for why this viewer now gets a dedicated, never-resized
      // container instead of sharing a CSS grid row with anything whose own
      // width can change.
      startRecording({ fps = 30, bitsPerSecond = 12_000_000, pixelRatio = 3 } = {}) {
        const sceneBag = sceneBagRef.current;
        if (!sceneBag) throw new Error("viewer not ready");
        if (recorderRef.current) throw new Error("already recording");
        const mimeType = pickSupportedVideoMimeType();
        if (!mimeType) throw new Error("this browser can't record video (MediaRecorder isn't supported here)");

        const previousPixelRatio = sceneBag.renderer.getPixelRatio();
        sceneBag.renderer.setPixelRatio(Math.max(previousPixelRatio, pixelRatio));
        // force one immediate re-render at the new resolution, so the very
        // first captured frame isn't a leftover lower-res one from before
        // the pixel ratio bump.
        sceneBag.renderer.render(sceneBag.scene, sceneBag.camera);

        const stream = sceneBag.renderer.domElement.captureStream(fps);
        const chunks = [];
        const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: bitsPerSecond });
        recorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) chunks.push(event.data);
        };
        recorder.start();
        recorderRef.current = { recorder, chunks, previousPixelRatio, mimeType };
      },
      stopRecording() {
        const state = recorderRef.current;
        if (!state) return Promise.reject(new Error("not recording"));
        return new Promise((resolve, reject) => {
          state.recorder.onstop = () => {
            sceneBagRef.current?.renderer.setPixelRatio(state.previousPixelRatio);
            recorderRef.current = null;
            resolve({ blob: new Blob(state.chunks, { type: state.mimeType }), mimeType: state.mimeType });
          };
          state.recorder.onerror = (event) => {
            sceneBagRef.current?.renderer.setPixelRatio(state.previousPixelRatio);
            recorderRef.current = null;
            reject(event.error || new Error("recording failed"));
          };
          state.recorder.stop();
        });
      },
    };
  });

  return (
    <div ref={containerRef} className="viewer-container">
      <canvas ref={canvasRef} className="viewer-canvas" />
    </div>
  );
});

export default LongitudinalMorphViewer;
