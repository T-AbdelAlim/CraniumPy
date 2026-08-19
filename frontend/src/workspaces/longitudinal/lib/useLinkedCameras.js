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

  // a string fingerprint of which refs are currently populated (e.g.
  // "110" for three viewers, the third not mounted yet) - recomputed on
  // every render, not just inside the effect. this exists because
  // `viewerRefs` itself doesn't reliably change identity when a new viewer
  // becomes available: CompareTab.jsx passes the SAME array object every
  // render (elements pushed into it in place as slots are added), so the
  // effect below would never re-run to attach a listener on a newly-added
  // third/fourth viewer - "link cameras" would keep working for the
  // original two (their listeners were already attached) but a new viewer
  // would never get one of its own, so moving IT never propagated anywhere
  // even though moving one of the original two still (correctly) moved
  // everything including the new one, via the live/mutated array read
  // inside the handler below. depending on this fingerprint instead of
  // `viewerRefs` itself forces a re-attach exactly when the set of
  // populated refs actually changes.
  const populatedKey = viewerRefs.map((r) => (r.current ? "1" : "0")).join("");

  useEffect(() => {
    if (!enabled) return undefined;
    // pair each ref with its controls together, rather than filtering
    // controls into their own separately-indexed array - a `.filter` on
    // just the controls list used to desync its indices from `viewerRefs`
    // whenever any ref wasn't populated yet, so a handler could end up
    // reading/writing the wrong viewer entirely.
    const entries = viewerRefs
      .map((ref) => ({ ref, controls: ref.current?.getControls() }))
      .filter((e) => e.controls);
    if (entries.length < 2) return undefined;

    function makeHandler(sourceEntry) {
      return () => {
        // setCameraState below calls controls.update(), which itself fires
        // a 'change' event on THAT instance - without this guard, two (or
        // more) linked viewers would immediately recurse into each other.
        if (syncingRef.current) return;
        syncingRef.current = true;
        const state = sourceEntry.ref.current?.getCameraState();
        if (state) {
          entries.forEach((e) => {
            if (e !== sourceEntry) e.ref.current?.setCameraState(state);
          });
        }
        syncingRef.current = false;
      };
    }

    const handlers = entries.map((e) => makeHandler(e));
    entries.forEach((e, i) => e.controls.addEventListener("change", handlers[i]));
    return () => {
      entries.forEach((e, i) => e.controls.removeEventListener("change", handlers[i]));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, populatedKey]);
}
