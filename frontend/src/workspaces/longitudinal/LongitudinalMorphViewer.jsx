import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useThreeScene } from "../../three/useThreeScene.js";
import { loadGlb, disposeMesh, plainMaterial } from "../../three/meshDisplay.js";
import { applyHeatmap, heatmapMaxAbs, removeHeatmap } from "../../three/measurementsLayer.js";

function firstMesh(object3D) {
  let found = null;
  object3D.traverse((child) => {
    if (!found && child.isMesh) found = child;
  });
  return found;
}

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
// actually visited along the way (see CorrespondenceTab.jsx's own comment
// on why: jumping straight from t0 to t3 would show exactly what just
// picking those two timepoints already would, defeating the point of
// having the intermediate ones at all). meaningful only because every
// timepoint shares the same vertex count/order (the same point-
// correspondence guarantee NICP template-fitting provides, see
// api/routers/longitudinal.py's /nicp-fit and /diff).
const LongitudinalMorphViewer = forwardRef(function LongitudinalMorphViewer(_props, ref) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const sceneBagRef = useThreeScene(canvasRef, containerRef);
  const gltfLoaderRef = useRef(null);
  const stateRef = useRef(null); // {object, mesh, posA, posB}
  const recorderRef = useRef(null); // {recorder, chunks, previousPixelRatio, mimeType}

  useEffect(() => {
    gltfLoaderRef.current = new GLTFLoader();
    return () => {
      const sceneBag = sceneBagRef.current;
      if (sceneBag && stateRef.current) {
        sceneBag.scene.remove(stateRef.current.object);
      }
      disposeMesh(stateRef.current?.object);
      stateRef.current = null;
      // an export mid-flight when this unmounts (switching tabs, tearing
      // down the correspondence set) would otherwise leave a MediaRecorder
      // running against a canvas that's about to be disposed.
      if (recorderRef.current) {
        recorderRef.current.recorder.stop();
        recorderRef.current = null;
      }
    };
  }, []);

  useImperativeHandle(ref, () => {
    // shared by setT/showHeatmapSequence below so both go through the exact
    // same per-leg math - recomputes the current frame's vertex positions
    // (and, if a heatmap's showing, its tint) from stateRef.current.lastT.
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
      // own interpolation - resets to white at the start of every leg and
      // ramps back up to that leg's own full change by its end, rather than
      // accumulating across the whole sequence - see showHeatmapSequence's
      // own comment for why.
      if (state.legHeatmaps) {
        const legHeatmap = state.legHeatmaps[legIndex];
        const scaledHeatmap = legHeatmap.map((v) => v * localT);
        applyHeatmap(state.object, scaledHeatmap, state.heatmapMaxAbs);
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
          legHeatmaps: null,
          heatmapMaxAbs: 0,
        };
      },
      setT(t) {
        const state = stateRef.current;
        if (!state) return;
        state.lastT = Math.max(0, Math.min(1, t));
        applyCurrentFrame();
      },
      // heatmaps: one per-vertex signed diff array PER LEG (length ===
      // positions.length - 1, i.e. one between each consecutive pair of
      // timepoints) - not one diff spanning the whole sequence. displacement
      // within leg i at local parameter u is exactly u*(pos[i+1]-pos[i]), so
      // each leg's own diff heatmap scales by that same u - see
      // applyCurrentFrame above. fixedMaxAbs is the largest |deviation| seen
      // in ANY leg, shared across all of them, so the color scale itself
      // stays constant through the whole playback (otherwise a small leg
      // would look just as saturated as a big one, and the point of
      // comparing them visually would be lost) - see applyHeatmap's own
      // comment for why a heatmap that's been scaled down must not
      // renormalize against its own (now smaller) max.
      showHeatmapSequence(heatmaps) {
        const state = stateRef.current;
        if (!state) return;
        state.legHeatmaps = heatmaps;
        state.heatmapMaxAbs = Math.max(...heatmaps.map((h) => heatmapMaxAbs(h)), 1e-6);
        applyCurrentFrame();
      },
      hideHeatmap() {
        const state = stateRef.current;
        if (!state) return;
        state.legHeatmaps = null;
        removeHeatmap(state.object);
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
    // affected outside the export.
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
