import { useEffect, useRef, useState } from "react";
import { fetchShippedTemplates, meshUrl, pollStatus, startRun } from "../../../api/sessions.js";
import {
  computeLongitudinalDiff,
  downloadLongitudinalReport,
  nicpFitMeshUrl,
  pollNicpFitStatus,
  startNicpFit,
} from "../../../api/longitudinal.js";
import Viewer from "../../../components/Viewer.jsx";
import LongitudinalMorphViewer from "../LongitudinalMorphViewer.jsx";
import MorphControl from "../MorphControl.jsx";
import { CORRESPONDENCE_MARKER_COLORS } from "../lib/colors.js";

function memberLabel(slot) {
  return slot.label || `Timepoint ${slot.index + 1}`;
}

function meshRefUrl(ref) {
  if (ref.fitId) return nicpFitMeshUrl(ref.fitId);
  return meshUrl(ref.sessionId, ref.stage);
}

function slotStageRef(slot) {
  return { sessionId: slot.sessionId, stage: slot.stage === "original" ? "original" : "clipped" };
}

// establishes point correspondence across EVERY ready timepoint at once
// (not just a chosen pair), all against one shared reference - either one
// of the timepoints themselves, or a shipped/custom template:
//   - reference = a timepoint: that timepoint's own mesh becomes the
//     template for a direct NICP fit onto every OTHER ready timepoint (see
//     api/routers/longitudinal.py's /nicp-fit) - N-1 fits, one per other
//     timepoint, each producing a result in the reference's own topology.
//     the reference itself needs no fit at all; it already defines the
//     topology everything else is being fit into.
//   - reference = a template: every ready timepoint (including what would
//     otherwise be "the reference") independently runs its EXISTING
//     session /run with that template (see api/schemas.py's NicpConfig) -
//     no new backend code, just N ordinary template fits instead of 2.
// either way the result is a `correspondenceSet` of N mutually
// vertex-correspondent meshes (same topology, same vertex order across all
// of them) - the pair-picker below then selects any 2 of those N for the
// change-map/morph/check-correspondence tools, rather than only ever
// working with exactly 2 timepoints the way a purely pairwise flow would.
export default function CorrespondenceTab({ slots }) {
  const readySlots = slots.map((s, i) => ({ ...s, index: i })).filter((s) => s.ready && s.sessionId);

  const [referenceMode, setReferenceMode] = useState("slot"); // "slot" | "template"
  const [referenceSlotIndex, setReferenceSlotIndex] = useState(readySlots[0]?.index ?? 0);
  const [templates, setTemplates] = useState([]);
  const [template, setTemplate] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [correspondenceSet, setCorrespondenceSet] = useState(null); // {referenceLabel, members: [{index,label,ref}]}
  const [pairIndexA, setPairIndexA] = useState(0); // index into correspondenceSet.members
  const [pairIndexB, setPairIndexB] = useState(1);
  const [diffHeatmap, setDiffHeatmap] = useState(null);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [checkStatus, setCheckStatus] = useState("");
  const [checkActive, setCheckActive] = useState(false);

  const heatmapViewerRef = useRef(null);
  const morphViewerRef = useRef(null);
  const checkViewerARef = useRef(null);
  const checkViewerBRef = useRef(null);

  useEffect(() => {
    fetchShippedTemplates()
      .then((list) => {
        setTemplates(list);
        if (list.length > 0) setTemplate((prev) => prev || list[0].name);
      })
      .catch(() => {});
  }, []);

  const members = correspondenceSet?.members ?? [];
  const memberA = members[pairIndexA];
  const memberB = members[pairIndexB];

  async function handleEstablish() {
    if (readySlots.length < 2) {
      setStatus("register at least two timepoints in the Compare tab first");
      return;
    }
    setBusy(true);
    setCorrespondenceSet(null);
    setDiffHeatmap(null);
    setCheckActive(false);
    try {
      const newMembers = [];
      if (referenceMode === "template") {
        if (!template) throw new Error("pick a template first");
        for (const [i, slot] of readySlots.entries()) {
          const label = memberLabel(slot);
          setStatus(`fitting ${label} to template (${i + 1}/${readySlots.length})...`);
          await startRun(slot.sessionId, { nVertices: null, nicp: { template } });
          await pollStatus(slot.sessionId, (s, d) => setStatus(`${label}: ${s} ${d}`));
          newMembers.push({ index: slot.index, label, ref: { sessionId: slot.sessionId, stage: "nicp_result" } });
        }
      } else {
        const reference = readySlots.find((s) => s.index === referenceSlotIndex);
        if (!reference) throw new Error("pick a reference timepoint first");
        const referenceRef = slotStageRef(reference);
        newMembers.push({ index: reference.index, label: memberLabel(reference), ref: referenceRef });
        const others = readySlots.filter((s) => s.index !== reference.index);
        for (const [i, other] of others.entries()) {
          const label = memberLabel(other);
          setStatus(`fitting ${memberLabel(reference)} onto ${label} (${i + 1}/${others.length}, each can take a minute)...`);
          const targetRef = slotStageRef(other);
          const fitId = await startNicpFit(referenceRef, targetRef);
          const finalStatus = await pollNicpFitStatus(fitId, (s, d) => setStatus(`${label}: ${s} ${d}`));
          if (finalStatus.status === "error") throw new Error(`${label}: ${finalStatus.error}`);
          newMembers.push({ index: other.index, label, ref: { fitId } });
        }
      }
      setCorrespondenceSet({
        referenceLabel: referenceMode === "template" ? template : memberLabel(readySlots.find((s) => s.index === referenceSlotIndex)),
        members: newMembers,
      });
      setPairIndexA(0);
      setPairIndexB(newMembers.length > 1 ? 1 : 0);
      setStatus("");
    } catch (err) {
      setStatus(`failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  // recomputes whenever the chosen pair (or the correspondence set itself)
  // changes - every member shares the same topology, so ANY two of them
  // can be diffed/morphed/checked, not just the pair that happened to get
  // fit first.
  useEffect(() => {
    if (!memberA || !memberB || pairIndexA === pairIndexB) {
      setDiffHeatmap(null);
      return undefined;
    }
    let cancelled = false;
    heatmapViewerRef.current?.displayMesh(meshRefUrl(memberB.ref), { selectionHasTexture: false });
    morphViewerRef.current?.loadPair(meshRefUrl(memberA.ref), meshRefUrl(memberB.ref));
    setCheckActive(false);
    (async () => {
      try {
        setStatus("computing change map...");
        const diff = await computeLongitudinalDiff(memberA.ref, memberB.ref);
        if (!cancelled) {
          setDiffHeatmap(diff.heatmap);
          setStatus("");
        }
      } catch (err) {
        if (!cancelled) setStatus(`change map failed: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [correspondenceSet, pairIndexA, pairIndexB]);

  useEffect(() => {
    if (!diffHeatmap) return;
    if (showHeatmap) {
      heatmapViewerRef.current?.showHeatmap(diffHeatmap);
      morphViewerRef.current?.showHeatmap(diffHeatmap);
    } else {
      heatmapViewerRef.current?.hideHeatmap();
      morphViewerRef.current?.hideHeatmap();
    }
  }, [diffHeatmap, showHeatmap]);

  // samples a handful of evenly-spread vertex INDICES (same indices are
  // valid on both meshes - that's exactly what "correspondence" means
  // here) and drops a distinctly-colored marker at that index's position
  // on each mesh - point i is the same color on both, so a real mismatch
  // (the same color landing somewhere totally different) is obvious at a
  // glance rather than something you'd have to trust a diff number for.
  //
  // just flips checkActive on - the actual mesh-loading/marker-placement
  // work happens in the effect below, AFTER that state change has
  // actually committed and the two check viewers below have mounted (they
  // only render at all once checkActive is true). doing this inline here
  // instead would read checkViewerARef/BRef.current while they're still
  // null - refs don't attach until React commits the render their JSX
  // came from, which hasn't happened yet inside this same event handler.
  function handleCheckCorrespondence() {
    if (!memberA || !memberB) return;
    setCheckActive(true);
  }

  useEffect(() => {
    if (!checkActive || !memberA || !memberB) return undefined;
    let cancelled = false;
    setCheckStatus("loading meshes...");
    (async () => {
      try {
        await Promise.all([
          checkViewerARef.current.displayMesh(meshRefUrl(memberA.ref), { selectionHasTexture: false }),
          checkViewerBRef.current.displayMesh(meshRefUrl(memberB.ref), { selectionHasTexture: false }),
        ]);
        const posA = checkViewerARef.current.getVertexPositions();
        const posB = checkViewerBRef.current.getVertexPositions();
        if (!posA || !posB) throw new Error("meshes didn't load");
        const vertexCount = posA.length / 3;
        if (posB.length / 3 !== vertexCount) {
          throw new Error(`vertex count mismatch (${vertexCount} vs ${posB.length / 3}) - these aren't actually correspondent`);
        }
        const n = Math.min(CORRESPONDENCE_MARKER_COLORS.length, vertexCount);
        const indices = Array.from({ length: n }, (_, i) => Math.round((i * (vertexCount - 1)) / Math.max(n - 1, 1)));
        const pointsAt = (pos) => indices.map((idx) => [pos[idx * 3], pos[idx * 3 + 1], pos[idx * 3 + 2]]);
        const colors = CORRESPONDENCE_MARKER_COLORS.slice(0, n);
        if (!cancelled) {
          checkViewerARef.current.showCorrespondenceMarkers(pointsAt(posA), colors);
          checkViewerBRef.current.showCorrespondenceMarkers(pointsAt(posB), colors);
          setCheckStatus("");
        }
      } catch (err) {
        if (!cancelled) setCheckStatus(`check failed: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkActive]);

  // works with or without an established correspondence - with one, the
  // report's final page includes the per-vertex change map (same heatmap
  // shown above); without one, it's just each timepoint's own full
  // measurement report back to back (see
  // api/results_bundle.longitudinal_comparison_report_pdf's include_diff
  // param), using whichever registered mesh each slot already has.
  async function handleDownloadReport() {
    const a = memberA ?? (readySlots[0] && { index: readySlots[0].index, label: memberLabel(readySlots[0]), ref: slotStageRef(readySlots[0]) });
    const b = memberB ?? (readySlots[1] && { index: readySlots[1].index, label: memberLabel(readySlots[1]), ref: slotStageRef(readySlots[1]) });
    if (!a || !b) return;
    setStatus("generating report...");
    try {
      const target = slots[a.index]?.target ?? "cranium";
      const url = await downloadLongitudinalReport(a.ref, b.ref, target, a.label, b.label, !!correspondenceSet);
      window.open(url, "_blank");
      setStatus("");
    } catch (err) {
      setStatus(`report failed: ${err.message}`);
    }
  }

  if (readySlots.length < 2) {
    return <p className="hint">Register at least two timepoints in the Compare tab before establishing correspondence.</p>;
  }

  return (
    <div className="longitudinal-correspondence-tab">
      <div className="longitudinal-toolbar longitudinal-correspondence-controls">
        <label>
          <input type="radio" checked={referenceMode === "slot"} onChange={() => setReferenceMode("slot")} />
          reference:
          <select
            disabled={referenceMode !== "slot"}
            value={referenceSlotIndex}
            onChange={(e) => setReferenceSlotIndex(Number(e.target.value))}
          >
            {readySlots.map((s) => (
              <option key={s.id} value={s.index}>
                {memberLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="radio" checked={referenceMode === "template"} onChange={() => setReferenceMode("template")} />
          shared template:
          <select disabled={referenceMode !== "template"} value={template} onChange={(e) => setTemplate(e.target.value)}>
            {templates.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={handleEstablish} disabled={busy}>
          {busy ? "working..." : `establish correspondence (${readySlots.length} timepoints)`}
        </button>
        <button type="button" className="button-subtle" onClick={handleDownloadReport} disabled={busy}>
          download comparison report
        </button>
      </div>
      {status && <p className="status-line">{status}</p>}

      {correspondenceSet && (
        <>
          <p className="hint">
            {correspondenceSet.members.length} timepoints share point correspondence now (reference: {correspondenceSet.referenceLabel}).
            Pick any two to compare below.
          </p>
          <div className="longitudinal-toolbar">
            <label>
              A:{" "}
              <select value={pairIndexA} onChange={(e) => setPairIndexA(Number(e.target.value))}>
                {correspondenceSet.members.map((m, i) => (
                  <option key={m.index} value={i}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              B:{" "}
              <select value={pairIndexB} onChange={(e) => setPairIndexB(Number(e.target.value))}>
                {correspondenceSet.members.map((m, i) => (
                  <option key={m.index} value={i}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="button-subtle" onClick={handleCheckCorrespondence}>
              check correspondence
            </button>
          </div>

          {memberA && memberB && (
            <div className="longitudinal-correspondence-viewers">
              <div className="longitudinal-correspondence-panel">
                <h3>
                  Change map ({memberA.label} &rarr; {memberB.label})
                </h3>
                <label>
                  <input type="checkbox" checked={showHeatmap} onChange={(e) => setShowHeatmap(e.target.checked)} />
                  show heatmap
                </label>
                <div className="longitudinal-slot-viewer">
                  <Viewer ref={heatmapViewerRef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
                </div>
              </div>
              <div className="longitudinal-correspondence-panel">
                <h3>Morph animation</h3>
                <MorphControl onT={(t) => morphViewerRef.current?.setT(t)} />
                <div className="longitudinal-slot-viewer">
                  <LongitudinalMorphViewer ref={morphViewerRef} />
                </div>
              </div>
            </div>
          )}

          {checkActive && (
            <div className="longitudinal-correspondence-viewers">
              <div className="longitudinal-correspondence-panel">
                <h3>{memberA?.label} - sample points</h3>
                <div className="longitudinal-slot-viewer">
                  <Viewer ref={checkViewerARef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
                </div>
              </div>
              <div className="longitudinal-correspondence-panel">
                <h3>{memberB?.label} - sample points</h3>
                <div className="longitudinal-slot-viewer">
                  <Viewer ref={checkViewerBRef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
                </div>
              </div>
              {checkStatus && <p className="status-line">{checkStatus}</p>}
              <p className="hint">
                each sample point is the same color on both meshes - if a color lands somewhere completely different
                between the two, that index isn't actually correspondent.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
