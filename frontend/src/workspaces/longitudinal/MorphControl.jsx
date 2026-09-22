import { useEffect, useRef, useState } from "react";
import { triggerDownload } from "../../lib/download.js";
import { saveVideo } from "../../api/longitudinal.js";

// seconds for one full A -> B sweep - the dropdown's own choices.
const SWEEP_SECONDS_OPTIONS = [0.5, 1, 2, 4, 8];
const DEFAULT_SWEEP_SECONDS = 4;

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
// encoder library, the recording itself needs no server round-trip either.
// a real video clip rather than a GIF: better quality per byte (no
// 256-color palette limit, which a smooth heatmap gradient would show as
// visible banding), and MediaRecorder is already built into the browser
// this app runs in either way (a Chromium engine, whether that's a real
// browser tab or the desktop app's own pywebview/WebView2 window) - a GIF
// would need a whole extra JS encoder dependency for a strictly worse
// result.
//
// exportDestDir/videoFolderName (optional, desktop-only - see
// MorphingTab.jsx's own folder-picker control) redirect the finished
// recording to a real save-to-folder call (api/routers/longitudinal.py's
// save_video) instead of the plain browser download below - the ONE step
// that does round-trip through the backend, since only it can write to an
// arbitrary filesystem path.
export default function MorphControl({ onT, morphViewerRef, fullscreenRef, exportDestDir, videoFolderName }) {
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
  //
  // fullscreenRef points at MorphingTab.jsx's own outer wrapper (toolbars +
  // this control + the canvas, all together) rather than anything inside
  // LongitudinalMorphViewer - fullscreening just the viewer's internal
  // canvas-only container used to take every control (including this
  // button) out of view the moment fullscreen started, leaving only Escape
  // as a way out. plain Fullscreen API here, nothing viewer-specific about
  // it.
  useEffect(() => {
    function onFullscreenChange() {
      setIsFullscreen(document.fullscreenElement === fullscreenRef?.current);
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [fullscreenRef]);

  function handleToggleFullscreen() {
    if (!fullscreenRef?.current) return;
    if (document.fullscreenElement === fullscreenRef.current) document.exitFullscreen?.();
    else fullscreenRef.current.requestFullscreen?.();
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

  // tries every mimeType the browser claims to support, one whole
  // recording attempt at a time, instead of trusting the first one blindly
  // - see LongitudinalMorphViewer.jsx's own supportedVideoMimeTypes/
  // stopRecording comments for why: isTypeSupported()===true isn't a
  // guarantee a codec will actually work for THIS stream, and on some
  // WebView2/Chromium builds a broken one doesn't error, it just never
  // calls onstop - previously that left the export stuck on "recording..."
  // forever with no way out. stopRecording's own timeout now bounds each
  // attempt, and abortRecording cleans up a still-stuck one before moving
  // to the next candidate.
  async function handleExportVideo() {
    if (!morphViewerRef?.current || exporting) return;
    const viewer = morphViewerRef.current;
    const candidates = viewer.getSupportedVideoMimeTypes();
    if (candidates.length === 0) {
      setExportStatus("export failed: this browser can't record video (MediaRecorder isn't supported here)");
      return;
    }
    setPlaying(false);
    setExporting(true);
    let lastError = null;
    for (let i = 0; i < candidates.length; i++) {
      setExportStatus(i === 0 ? "recording..." : "recording (retrying with a different video format)...");
      try {
        viewer.startRecording({ mimeType: candidates[i] });
        await runRoundTripSweep(sweepSecondsRef.current, setT);
        const { blob, mimeType } = await viewer.stopRecording();
        if (!blob || blob.size === 0) throw new Error("the recording came out empty");
        const extension = extensionForMimeType(mimeType);
        if (exportDestDir) {
          // desktop, with a destination folder picked (see MorphingTab.jsx's
          // own folder-picker control) - write the bytes straight to disk
          // instead of a browser download, same folder-naming convention
          // the Trends tab's "export results" uses.
          const { saved_to: savedTo } = await saveVideo(blob, extension, exportDestDir, videoFolderName);
          setExportStatus(`Saved to ${savedTo}`);
        } else {
          const url = URL.createObjectURL(blob);
          triggerDownload(url, `morph_animation.${extension}`);
          // the download itself is synchronous (the anchor click fires
          // immediately), but WebView2/some browsers read the blob lazily
          // right after - revoking too early can turn that into an empty/
          // corrupt file, so this waits a beat rather than revoking inline.
          setTimeout(() => URL.revokeObjectURL(url), 30_000);
          setExportStatus("");
        }
        lastError = null;
        break;
      } catch (err) {
        lastError = err;
        viewer.abortRecording();
      }
    }
    if (lastError) setExportStatus(`export failed: ${lastError.message}`);
    setExporting(false);
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
          export video
        </button>
      )}
      {fullscreenRef && (
        <button type="button" className="button-subtle" onClick={handleToggleFullscreen} disabled={exporting}>
          {isFullscreen ? "exit fullscreen" : "fullscreen"}
        </button>
      )}
      {/* always rendered (visibility toggled via CSS, not conditional
          mounting) so this reserves fixed layout space whether idle,
          recording, or showing an error - a conditionally-mounted status
          chip used to grow/shrink the whole toolbar row every time export
          started or finished. */}
      <span className={exportStatus ? "hint longitudinal-morph-export-status is-visible" : "hint longitudinal-morph-export-status"}>
        {exportStatus}
      </span>
    </div>
  );
}
