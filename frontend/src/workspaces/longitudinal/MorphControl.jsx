import { useEffect, useRef, useState } from "react";
import { triggerDownload } from "../../lib/download.js";

// seconds for one full A -> B sweep - the dropdown's own choices. 2s was
// the old hardcoded rate (see this file's earlier version); kept as the
// default so existing behavior doesn't shift under anyone who never
// touches the new control.
const SWEEP_SECONDS_OPTIONS = [0.5, 1, 2, 4, 8];
const DEFAULT_SWEEP_SECONDS = 2;

// drives t through one full A -> B -> A round trip at the given per-leg
// duration, calling setTFn every frame - the exported video's own
// animation, kept separate from the play/pause loop above (which runs
// indefinitely) since an export needs to know exactly when it's done so
// it can stop recording.
function runRoundTripSweep(secondsPerLeg, setTFn) {
  return new Promise((resolve) => {
    const totalSeconds = secondsPerLeg * 2;
    let start = null;
    function tick(now) {
      if (start === null) start = now;
      const elapsed = (now - start) / 1000;
      if (elapsed >= totalSeconds) {
        setTFn(0);
        resolve();
        return;
      }
      const t = elapsed <= secondsPerLeg ? elapsed / secondsPerLeg : 1 - (elapsed - secondsPerLeg) / secondsPerLeg;
      setTFn(Math.max(0, Math.min(1, t)));
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}

function extensionForMimeType(mimeType) {
  return mimeType.startsWith("video/mp4") ? "mp4" : "webm";
}

// scrubber + play/pause for LongitudinalMorphViewer - a plain 0..1 range
// input always available (manual scrub), plus an optional auto-play
// ping-pong loop (start -> end -> start, chaining through every leg in
// between when the viewer's loaded a sequence of more than two timepoints -
// see LongitudinalMorphViewer.jsx's own setT) for a hands-free preview, at a
// user-chosen speed. onT fires on every change, scrub or animated alike -
// the parent just forwards it straight to the viewer's imperative setT(t).
// the readout is a bare percentage, not "62% from Timepoint 0 to Timepoint
// 1" - a leg-label version of this used to widen/rejumble the whole toolbar
// as playback moved between legs with different-length labels, which read
// as the panel itself jittering. this component never needs to know how
// many legs there are - that's entirely the viewer's own concern.
//
// morphViewerRef (optional) additionally enables "export video": one full
// start -> end -> start sweep at the current speed, captured straight off
// the viewer's own canvas via the browser's MediaRecorder (see
// LongitudinalMorphViewer.jsx's startRecording/stopRecording) - no GIF
// encoder library, no server round-trip. a real video clip rather than a
// GIF: better quality per byte (no 256-color palette limit, which a smooth
// heatmap gradient would show as visible banding), and MediaRecorder is
// already built into the browser this app runs in either way (a Chromium
// engine, whether that's a real browser tab or the desktop app's own
// pywebview/WebView2 window) - a GIF would need a whole extra JS encoder
// dependency for a strictly worse result.
export default function MorphControl({ onT, morphViewerRef }) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [sweepSeconds, setSweepSeconds] = useState(DEFAULT_SWEEP_SECONDS);
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState("");
  const [opacity, setOpacity] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const directionRef = useRef(1);
  const rafRef = useRef(null);
  const lastRef = useRef(null);
  const sweepSecondsRef = useRef(sweepSeconds);

  useEffect(() => {
    onT(t);
  }, [t]);

  useEffect(() => {
    morphViewerRef?.current?.setMeshOpacity(opacity);
  }, [opacity, morphViewerRef]);

  // synced from the browser's own fullscreenchange event, not just the
  // button click - Escape (or the browser/OS's own fullscreen exit
  // control) leaves fullscreen without ever calling handleToggleFullscreen,
  // and the button's own label needs to reflect that either way.
  useEffect(() => {
    function onFullscreenChange() {
      setIsFullscreen(!!morphViewerRef?.current?.isFullscreenElement());
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [morphViewerRef]);

  function handleToggleFullscreen() {
    if (!morphViewerRef?.current) return;
    if (morphViewerRef.current.isFullscreenElement()) morphViewerRef.current.exitFullscreen();
    else morphViewerRef.current.requestFullscreen();
  }

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

  async function handleExportVideo() {
    if (!morphViewerRef?.current || exporting) return;
    setPlaying(false);
    setExporting(true);
    setExportStatus("recording...");
    try {
      morphViewerRef.current.startRecording();
      await runRoundTripSweep(sweepSecondsRef.current, setT);
      const { blob, mimeType } = await morphViewerRef.current.stopRecording();
      const url = URL.createObjectURL(blob);
      triggerDownload(url, `morph_animation.${extensionForMimeType(mimeType)}`);
      // the download itself is synchronous (the anchor click fires
      // immediately), but WebView2/some browsers read the blob lazily
      // right after - revoking too early can turn that into an empty/
      // corrupt file, so this waits a beat rather than revoking inline.
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
      setExportStatus("");
    } catch (err) {
      setExportStatus(`export failed: ${err.message}`);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="longitudinal-morph-control">
      <button type="button" onClick={() => setPlaying((p) => !p)} disabled={exporting}>
        {playing ? "pause" : "play"}
      </button>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={t}
        disabled={exporting}
        onChange={(e) => {
          setPlaying(false);
          setT(Number(e.target.value));
        }}
      />
      <label className="longitudinal-morph-speed">
        speed
        <select value={sweepSeconds} onChange={(e) => setSweepSeconds(Number(e.target.value))} disabled={exporting}>
          {SWEEP_SECONDS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}s / sweep
            </option>
          ))}
        </select>
      </label>
      <span className="hint longitudinal-morph-readout">{Math.round(t * 100)}%</span>
      <label className="longitudinal-morph-opacity">
        opacity
        <input
          type="range"
          min={0.1}
          max={1}
          step={0.05}
          value={opacity}
          disabled={exporting}
          onChange={(e) => setOpacity(Number(e.target.value))}
        />
      </label>
      {morphViewerRef && (
        <button type="button" className="button-subtle" onClick={handleExportVideo} disabled={exporting}>
          {exporting ? "recording..." : "export video"}
        </button>
      )}
      {morphViewerRef && (
        <button type="button" className="button-subtle" onClick={handleToggleFullscreen}>
          {isFullscreen ? "exit fullscreen" : "fullscreen"}
        </button>
      )}
      {exportStatus && <span className="hint">{exportStatus}</span>}
    </div>
  );
}
