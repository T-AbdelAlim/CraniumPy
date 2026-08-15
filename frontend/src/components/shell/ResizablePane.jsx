import { useEffect, useRef, useState } from "react";

const COLLAPSED_WIDTH = 36;

// generic resizable/collapsible sidebar wrapper - used for both the left
// nav and right inspector so relocating either later (there's a live
// request to reconsider which side the inspector lives on) is a prop
// change, not a rewrite. owns its own width/collapsed state, persisted to
// localStorage per storageKey so the preference survives a reload.
export default function ResizablePane({ side, defaultWidth, minWidth = 180, maxWidth = 560, storageKey, children }) {
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(`shell-pane-width-${storageKey}`));
    return stored > 0 ? stored : defaultWidth;
  });
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(`shell-pane-collapsed-${storageKey}`) === "true");
  const dragStateRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(`shell-pane-width-${storageKey}`, String(width));
  }, [width, storageKey]);

  useEffect(() => {
    localStorage.setItem(`shell-pane-collapsed-${storageKey}`, String(collapsed));
  }, [collapsed, storageKey]);

  function handlePointerDown(event) {
    dragStateRef.current = { startX: event.clientX, startWidth: width };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event) {
    if (!dragStateRef.current) return;
    const delta = event.clientX - dragStateRef.current.startX;
    // dragging the left pane's (right-edge) handle rightward should grow
    // it; dragging the right pane's (left-edge) handle leftward should
    // grow it - opposite signs for the same screen-space delta.
    const signedDelta = side === "left" ? delta : -delta;
    const next = Math.min(maxWidth, Math.max(minWidth, dragStateRef.current.startWidth + signedDelta));
    setWidth(next);
  }

  function handlePointerUp(event) {
    dragStateRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  const collapseIcon = side === "left" ? "‹" : "›";
  const expandIcon = side === "left" ? "›" : "‹";

  return (
    <div className={`shell-pane shell-pane-${side}${collapsed ? " collapsed" : ""}`} style={{ width: collapsed ? COLLAPSED_WIDTH : width }}>
      <button
        type="button"
        className="shell-pane-toggle"
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "Expand" : "Collapse"}
      >
        {collapsed ? expandIcon : collapseIcon}
      </button>
      {!collapsed && <div className="shell-pane-content">{children}</div>}
      {!collapsed && (
        <div
          className={`shell-pane-handle shell-pane-handle-${side}`}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        />
      )}
    </div>
  );
}
