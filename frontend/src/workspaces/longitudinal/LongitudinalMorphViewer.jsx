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

// a standalone Three.js viewer, deliberately NOT built on Viewer.jsx - the
// morph animation needs a persistent, directly-mutable geometry (the same
// BufferAttribute lerped in place every frame/scrub) which would fight
// Viewer.jsx's own invariant that displayMesh always fully replaces the
// previous mesh (see that component's meshStateRef). owns its own
// useThreeScene instance instead - proven safe to mount concurrently
// alongside other Viewer/scene instances (see useThreeScene.js's own
// comment on why every instance is fully independent).
//
// loadPair(urlA, urlB) loads both GLBs, keeps mesh A's own geometry as the
// thing actually displayed/animated, and just the raw vertex position
// arrays from both (mesh_to_glb always produces a single-mesh GLB with a
// stable vertex order, so a simple flat Float32Array is enough - no need to
// keep mesh B's Object3D around at all once its positions are copied out).
// setT(t) lerps every vertex between the two, 0 = fully A, 1 = fully B -
// meaningful only because both meshes share the same vertex count/order
// (the same point-correspondence guarantee NICP template-fitting provides,
// see api/routers/longitudinal.py's /nicp-fit and /diff).
const LongitudinalMorphViewer = forwardRef(function LongitudinalMorphViewer(_props, ref) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const sceneBagRef = useThreeScene(canvasRef, containerRef);
  const gltfLoaderRef = useRef(null);
  const stateRef = useRef(null); // {object, mesh, posA, posB}

  useEffect(() => {
    gltfLoaderRef.current = new GLTFLoader();
    return () => {
      const sceneBag = sceneBagRef.current;
      if (sceneBag && stateRef.current) {
        sceneBag.scene.remove(stateRef.current.object);
      }
      disposeMesh(stateRef.current?.object);
      stateRef.current = null;
    };
  }, []);

  useImperativeHandle(ref, () => ({
    async loadPair(urlA, urlB) {
      const sceneBag = sceneBagRef.current;
      if (!sceneBag) return;

      const [objectA, objectB] = await Promise.all([
        loadGlb(gltfLoaderRef.current, urlA),
        loadGlb(gltfLoaderRef.current, urlB),
      ]);
      const meshA = firstMesh(objectA);
      const meshB = firstMesh(objectB);
      const posA = meshA.geometry.attributes.position.array;
      const posB = meshB.geometry.attributes.position.array;
      if (posA.length !== posB.length) {
        disposeMesh(objectA);
        disposeMesh(objectB);
        throw new Error(
          `vertex count mismatch (${posA.length / 3} vs ${posB.length / 3}) - both meshes must share the same point correspondence`,
        );
      }

      if (stateRef.current) {
        sceneBag.scene.remove(stateRef.current.object);
        disposeMesh(stateRef.current.object);
      }
      meshA.geometry.computeVertexNormals();
      meshA.material = plainMaterial();
      disposeMesh(objectB); // only its position array was needed, already copied below

      sceneBag.scene.add(objectA);
      sceneBag.fitCameraToObject(objectA);
      stateRef.current = { object: objectA, mesh: meshA, posA: posA.slice(), posB: posB.slice(), lastT: 0, fullHeatmap: null, heatmapMaxAbs: 0 };
    },
    setT(t) {
      const state = stateRef.current;
      if (!state) return;
      const { mesh, posA, posB } = state;
      const positions = mesh.geometry.attributes.position;
      for (let i = 0; i < positions.array.length; i++) {
        positions.array[i] = posA[i] + t * (posB[i] - posA[i]);
      }
      positions.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
      mesh.geometry.computeBoundingSphere();
      state.lastT = t;
      // the heatmap (if one's showing) rescales right along with the
      // interpolation - see showHeatmap's own comment for the math this
      // relies on.
      if (state.fullHeatmap) {
        const scaled = state.fullHeatmap.map((v) => v * t);
        applyHeatmap(state.object, scaled, state.heatmapMaxAbs);
      }
    },
    // the diff heatmap scales down toward zero (all-white, "no difference
    // yet") as t -> 0 and back up to its full value at t -> 1, rather than
    // showing the FINAL diff at every point along the animation - since
    // displacement at parameter t is exactly t*(posB-posA), and the diff
    // heatmap is that same displacement projected onto meshA's own (fixed)
    // normals, the value at any t is exactly t * (the full diff) - a plain
    // linear scale of the array already computed for t=1, no new geometry
    // or backend call needed. fixedMaxAbs (computed once, from the FULL
    // heatmap) keeps the color scale itself constant across every t - see
    // applyHeatmap's own comment for why a heatmap scaled by t must NOT
    // renormalize against its own (now smaller) max each call, or the
    // color would never visibly change.
    showHeatmap(heatmap) {
      const state = stateRef.current;
      if (!state) return;
      state.fullHeatmap = heatmap;
      state.heatmapMaxAbs = heatmapMaxAbs(heatmap);
      applyHeatmap(state.object, heatmap.map((v) => v * state.lastT), state.heatmapMaxAbs);
    },
    hideHeatmap() {
      const state = stateRef.current;
      if (!state) return;
      state.fullHeatmap = null;
      removeHeatmap(state.object);
    },
  }));

  return (
    <div ref={containerRef} className="viewer-container">
      <canvas ref={canvasRef} className="viewer-canvas" />
    </div>
  );
});

export default LongitudinalMorphViewer;
