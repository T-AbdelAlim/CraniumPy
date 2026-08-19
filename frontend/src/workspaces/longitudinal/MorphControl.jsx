import { useEffect, useRef, useState } from "react";

// seconds for one full A -> B sweep - the dropdown's own choices. 2s was
// the old hardcoded rate (see this file's earlier version); kept as the
// default so existing behavior doesn't shift under anyone who never
// touches the new control.
const SWEEP_SECONDS_OPTIONS = [0.5, 1, 2, 4, 8];
const DEFAULT_SWEEP_SECONDS = 2;

// scrubber + play/pause for LongitudinalMorphViewer - a plain 0..1 range
// input always available (manual scrub), plus an optional auto-play
// ping-pong loop (A -> B -> A) for a hands-free preview, at a user-chosen
// speed. onT fires on every change, scrub or animated alike - the parent
// just forwards it straight to the viewer's imperative setT(t).
export default function MorphControl({ onT }) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [sweepSeconds, setSweepSeconds] = useState(DEFAULT_SWEEP_SECONDS);
  const directionRef = useRef(1);
  const rafRef = useRef(null);
  const lastRef = useRef(null);
  const sweepSecondsRef = useRef(sweepSeconds);

  useEffect(() => {
    onT(t);
  }, [t]);

  // read from the tick loop below via a ref, not the sweepSeconds state
  // directly - so changing speed mid-playback takes effect on the very
  // next frame instead of only once the RAF loop's own effect re-runs
  // (which setPlaying/playing already have to control separately).
  useEffect(() => {
    sweepSecondsRef.current = sweepSeconds;
  }, [sweepSeconds]);

  useEffect(() => {
    if (!playing) return undefined;
    lastRef.current = null;
    function tick(now) {
      if (lastRef.current == null) lastRef.current = now;
      const dt = (now - lastRef.current) / 1000;
      lastRef.current = now;
      setT((prev) => {
        let next = prev + (directionRef.current * dt) / sweepSecondsRef.current;
        if (next >= 1) {
          next = 1;
          directionRef.current = -1;
        } else if (next <= 0) {
          next = 0;
          directionRef.current = 1;
        }
        return next;
      });
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [playing]);

  return (
    <div className="longitudinal-morph-control">
      <button type="button" onClick={() => setPlaying((p) => !p)}>
        {playing ? "pause" : "play"}
      </button>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={t}
        onChange={(e) => {
          setPlaying(false);
          setT(Number(e.target.value));
        }}
      />
      <label className="longitudinal-morph-speed">
        speed
        <select value={sweepSeconds} onChange={(e) => setSweepSeconds(Number(e.target.value))}>
          {SWEEP_SECONDS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}s / sweep
            </option>
          ))}
        </select>
      </label>
      <span className="hint longitudinal-morph-readout">
        {t < 0.02 ? "baseline" : t > 0.98 ? "follow-up" : `${Math.round(t * 100)}% toward follow-up`}
      </span>
    </div>
  );
}
