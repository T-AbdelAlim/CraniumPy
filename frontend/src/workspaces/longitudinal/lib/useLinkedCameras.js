import { useEffect, useRef } from "react";

// synchronizes OrbitControls state (position/target) across N independent
// <Viewer> instances - rotating/panning/zooming any one of them mirrors the
// same camera state into every other linked viewer, the Longitudinal
// workspace's "rotate one, both rotate" requirement. relies on Viewer.jsx's
// getControls/getCameraState/setCameraState (see that component) - this hook
// attaches/detaches its own 'change' listeners on the raw OrbitControls
// instances externally, so Viewer itself stays unaware that linking exists.
//
// viewerRefs is an array of React refs (one per mounted <Viewer>, stable
// identity not required - only .current is read, on every effect run).
// enabled toggles the whole thing on/off, e.g. the workspace's own "link
// cameras" checkbox.
//
// two independently-registered meshes already land in the exact same fixed
// coordinate frame (see registration.rigid.REFERENCE_TRIANGLE) - so mirroring
// raw camera/target position (not a relative transform) is exactly right
// here, no per-viewer offset math needed.
export function useLinkedCameras(viewerRefs, enabled) {
  const syncingRef = useRef(false);

  useEffect(() => {
    if (!enabled) return undefined;
    const controlsList = viewerRefs.map((r) => r.current?.getControls()).filter(Boolean);
    if (controlsList.length < 2) return undefined;

    function makeHandler(sourceIndex) {
      return () => {
        // setCameraState below calls controls.update(), which itself fires
        // a 'change' event on THAT instance - without this guard, two (or
        // more) linked viewers would immediately recurse into each other.
        if (syncingRef.current) return;
        syncingRef.current = true;
        const state = viewerRefs[sourceIndex].current?.getCameraState();
        if (state) {
          viewerRefs.forEach((r, i) => {
            if (i !== sourceIndex) r.current?.setCameraState(state);
          });
        }
        syncingRef.current = false;
      };
    }

    const handlers = controlsList.map((_, i) => makeHandler(i));
    controlsList.forEach((controls, i) => controls.addEventListener("change", handlers[i]));
    return () => {
      controlsList.forEach((controls, i) => controls.removeEventListener("change", handlers[i]));
    };
  }, [viewerRefs, enabled]);
}
