import { useEffect, useRef } from "react";
import { createScene } from "./scene.js";

// bridges createScene's imperative Three.js world into React: builds the
// scene once on mount (a ref, not state - none of this should ever trigger
// a re-render), runs the render loop, keeps the canvas sized to its
// container via ResizeObserver (a strict superset of a window-resize
// listener - the container can resize without the window doing so once a
// sidebar layout is involved), and disposes everything on unmount. legacy's
// version of this never unmounted its canvas, so it never had to.
export function useThreeScene(canvasRef, containerRef) {
  const sceneBagRef = useRef(null);

  useEffect(() => {
    const sceneBag = createScene(canvasRef.current);
    sceneBagRef.current = sceneBag;

    const container = containerRef.current;
    const resizeObserver = new ResizeObserver(() => {
      sceneBag.resize(container.clientWidth, container.clientHeight);
    });
    resizeObserver.observe(container);
    sceneBag.resize(container.clientWidth, container.clientHeight);

    // several workspaces (Longitudinal's Compare/3D-Morphing split, Facial
    // Anthropometrics' Define/Batch split) keep every tab's Viewer mounted
    // via CSS display:none rather than unmounting it, specifically to
    // preserve loaded meshes/GPU state across tab switches - but that means
    // a fully hidden Viewer would otherwise still render every frame at
    // full cost forever. offsetParent is null exactly when this element (or
    // an ancestor) is display:none - the same check costs nothing extra and
    // needs no new prop threaded down, unlike an IntersectionObserver.
    // still scheduling the next frame either way, so rendering resumes
    // immediately (no stale frame) the moment the tab becomes visible again.
    let rafId;
    (function animate() {
      rafId = requestAnimationFrame(animate);
      if (container.offsetParent === null) return;
      sceneBag.controls.update();
      sceneBag.renderer.render(sceneBag.scene, sceneBag.camera);
    })();

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      sceneBag.dispose();
      sceneBagRef.current = null;
    };
  }, [canvasRef, containerRef]);

  return sceneBagRef;
}
