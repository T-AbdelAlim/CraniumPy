import { useRef, useState } from "react";

// hover/focus explainer - a real popup box, not the browser's native `title`
// tooltip (which turned out to just show the icon with no visible box at
// all for some users/environments - unreliable enough to not depend on).
// positioned with position:fixed, computed from the icon's own
// getBoundingClientRect() on hover, specifically so it escapes the
// workspace sidebar's own overflow-y:auto (see index.css's
// .shell-pane-content) - a plain position:absolute tooltip gets clipped or
// scrolled away by that ancestor instead of floating free over the page.
const BOX_WIDTH = 240;
const MARGIN = 10;

export default function InfoTooltip({ text }) {
  const iconRef = useRef(null);
  const [pos, setPos] = useState(null); // {top, left} in viewport coords, or null when hidden

  if (!text) return null;

  function show() {
    const rect = iconRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.min(Math.max(rect.left, MARGIN), window.innerWidth - BOX_WIDTH - MARGIN);
    setPos({ top: rect.bottom + 6, left });
  }
  function hide() {
    setPos(null);
  }

  return (
    <span
      ref={iconRef}
      className="info-tooltip"
      tabIndex={0}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      aria-label={text}
    >
      ⓘ
      {pos && (
        <span className="info-tooltip-box" style={{ top: pos.top, left: pos.left, width: BOX_WIDTH }}>
          {text}
        </span>
      )}
    </span>
  );
}
