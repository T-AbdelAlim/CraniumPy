import { useEffect, useRef, useState } from "react";
import { fetchShippedTemplates, meshUrl, openFromPaths, pollStatus, startRun, uploadSession } from "../../../api/sessions.js";
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
import { useLinkedCameras } from "../lib/useLinkedCameras.js";
import { CORRESPONDENCE_MARKER_COLORS } from "../lib/colors.js";
import { detectNicpTargetFromFilename } from "../lib/detectTarget.js";
import { triggerDownload } from "../../../lib/download.js";
import { isDesktopApp, pickFileNative } from "../../../lib/desktop.js";

function memberLabel(slot) {
  return slot.label || `Timepoint ${slot.index}`;
}

// chronological order (t0 -> t1 -> t2 -> ...) regardless of which member was
// picked as the correspondence SOURCE - the source can be any timepoint (or
// a template), so correspondenceSet.members isn't necessarily already in
// timepoint order (see handleEstablish: the source is always pushed first,
// followed by every other ready slot in whatever order they appear in
// `slots`). the morph animation chains legs in this order, not the order
// members happened to be established in.
function orderedMembers(correspondenceSet) {
  return [...(correspondenceSet?.members ?? [])].sort((a, b) => a.index - b.index);
}

function meshRefUrl(ref) {
  if (ref.fitId) return nicpFitMeshUrl(ref.fitId);
  return meshUrl(ref.sessionId, ref.stage);
}

function slotStageRef(slot) {
  return { sessionId: slot.sessionId, stage: slot.stage === "original" ? "original" : "clipped" };
}

// establishes point correspondence across EVERY ready timepoint at once
// (not just a chosen pair), all against one shared SOURCE mesh - either one
// of the timepoints themselves, or a shipped/custom template. "source"
// because its own topology (vertex count/connectivity) is exactly what
// survives into every fitted result - every other mesh gets deformed to
// approximate that one's shape, but none of them change ITS layout:
//   - source = a timepoint: that timepoint's own mesh becomes the template
//     for a direct NICP fit onto every OTHER ready timepoint (see
//     api/routers/longitudinal.py's /nicp-fit) - N-1 fits, one per other
//     timepoint, each producing a result in the source's own topology. the
//     source itself needs no fit at all; it already defines the topology
//     everything else is being fit into.
//   - source = a template: every ready timepoint (including what would
//     otherwise be "the source") independently runs its EXISTING session
//     /run with that template (see api/schemas.py's NicpConfig) - no new
//     backend code, just N ordinary template fits instead of 2.
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
  const [legHeatmaps, setLegHeatmaps] = useState(null); // one per-vertex diff per consecutive pair in orderedMembers
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [checkStatus, setCheckStatus] = useState("");
  const [checkActive, setCheckActive] = useState(false);
  const [linkCameras, setLinkCameras] = useState(false);
  const [importTarget, setImportTarget] = useState("cranium");
  const [importBusy, setImportBusy] = useState(false);
  const [importStatus, setImportStatus] = useState("");

  const heatmapViewerRef = useRef(null);
  const morphViewerRef = useRef(null);
  const checkViewerARef = useRef(null);
  const checkViewerBRef = useRef(null);
  const importInputRef = useRef(null);

  useLinkedCameras([heatmapViewerRef, morphViewerRef, checkViewerARef, checkViewerBRef], linkCameras);

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
          newMembers.push({ index: slot.index, label, ref: { sessionId: slot.sessionId, stage: "nicp_result" }, target: slot.target });
        }
      } else {
        const reference = readySlots.find((s) => s.index === referenceSlotIndex);
        if (!reference) throw new Error("pick a source timepoint first");
        const referenceRef = slotStageRef(reference);
        newMembers.push({ index: reference.index, label: memberLabel(reference), ref: referenceRef, target: reference.target });
        const others = readySlots.filter((s) => s.index !== reference.index);
        for (const [i, other] of others.entries()) {
          const label = memberLabel(other);
          setStatus(`fitting ${memberLabel(reference)} onto ${label} (${i + 1}/${others.length}, each can take a minute)...`);
          const targetRef = slotStageRef(other);
          const fitId = await startNicpFit(referenceRef, targetRef);
          const finalStatus = await pollNicpFitStatus(fitId, (s, d) => setStatus(`${label}: ${s} ${d}`));
          if (finalStatus.status === "error") throw new Error(`${label}: ${finalStatus.error}`);
          newMembers.push({ index: other.index, label, ref: { fitId }, target: other.target });
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

  // the fast path: meshes that were already NICP-fit to the same shared
  // template somewhere else (a prior session, another machine, this app's
  // own Patients workspace exported as "..._CN.ply"/"..._FN.ply" - see
  // api/results_bundle.py's _build_mesh_files) already ARE mutually
  // vertex-correspondent - there's nothing left to fit, so this skips
  // startNicpFit/startRun (each a real, multi-minute optimization) entirely
  // and just uploads each file as its own session, straight into a
  // correspondenceSet. doesn't touch the Compare tab's slots at all - these
  // files never went through that pipeline and don't need to.
  //
  // vertex count is the one cheap, immediate check available here (the
  // session-creation endpoint already parses the mesh and reports it, no
  // extra round trip) - a real guarantee of "same template" would mean
  // actually comparing topology/connectivity, but a vertex-count mismatch
  // is a guaranteed sign these AREN'T correspondent, so it's worth catching
  // early rather than only surfacing later as a confusing diff/report
  // error. a MATCHING count doesn't prove correspondence on its own - that's
  // what the existing "check correspondence" markers are for once these are
  // loaded.
  async function importFromEntries(entries) {
    if (entries.length < 2) {
      setImportStatus("pick at least two mesh files");
      return;
    }
    setImportBusy(true);
    setImportStatus("");
    setCorrespondenceSet(null);
    setDiffHeatmap(null);
    setCheckActive(false);
    try {
      const newMembers = [];
      let expectedVertexCount = null;
      for (const [i, entry] of entries.entries()) {
        setImportStatus(`uploading ${entry.name} (${i + 1}/${entries.length})...`);
        const { sessionId, vertexCount } = await entry.open();
        if (expectedVertexCount === null) {
          expectedVertexCount = vertexCount;
        } else if (vertexCount !== expectedVertexCount) {
          throw new Error(
            `${entry.name} has ${vertexCount} vertices, but ${entries[0].name} has ${expectedVertexCount} - these don't share the same template`,
          );
        }
        newMembers.push({ index: i, label: entry.name, ref: { sessionId, stage: "original" }, target: importTarget });
      }
      setCorrespondenceSet({ referenceLabel: "imported (already NICP-fit)", members: newMembers });
      setPairIndexA(0);
      setPairIndexB(newMembers.length > 1 ? 1 : 0);
      setImportStatus("");
    } catch (err) {
      setImportStatus(`import failed: ${err.message}`);
    } finally {
      setImportBusy(false);
    }
  }

  // desktop: one native multi-select dialog, one session per picked path
  // (openFromPaths([path]) rather than one path array - each file here is
  // its own standalone timepoint, not companion files for a single mesh the
  // way UploadPanel.jsx's own multi-select is). browser: the hidden file
  // input below. either way, the FIRST file's name seeds the target
  // auto-detect (see detectNicpTargetFromFilename) - these are assumed to
  // all be the same target, since they're fit to one shared template.
  async function handleImportClick() {
    if (!isDesktopApp()) {
      importInputRef.current?.click();
      return;
    }
    const paths = await pickFileNative(true, (msg) => setImportStatus(`Couldn't open the file picker: ${msg}`));
    if (!paths || paths.length === 0) return;
    const names = paths.map((p) => p.split(/[\\/]/).pop());
    const detected = detectNicpTargetFromFilename(names[0]);
    if (detected) setImportTarget(detected);
    await importFromEntries(paths.map((p, i) => ({ name: names[i], open: () => openFromPaths([p]) })));
  }

  function handleImportFilesSelected(event) {
    const files = Array.from(event.target.files);
    event.target.value = "";
    if (files.length === 0) return;
    const detected = detectNicpTargetFromFilename(files[0].name);
    if (detected) setImportTarget(detected);
    importFromEntries(files.map((f) => ({ name: f.name, open: () => uploadSession([f]) })));
  }

  // recomputes whenever the chosen pair (or the correspondence set itself)
  // changes - every member shares the same topology, so ANY two of them
  // can be diffed/checked, not just the pair that happened to get fit
  // first. drives only the Change map panel (heatmapViewerRef) - the Morph
  // animation panel below no longer follows this pair at all, see the
  // separate effect after this one.
  //
  // displayMesh is explicitly awaited BEFORE the diff is computed and
  // BEFORE setDiffHeatmap fires - that's deliberate: the separate heatmap-
  // visibility effect below reacts to diffHeatmap changing by calling
  // showHeatmap() on this same viewer, and showHeatmap silently no-ops
  // against a Viewer with no mesh loaded yet. with this NOT awaited (the
  // original version), a fast diff computation racing a slower mesh load
  // meant showHeatmap ran before the mesh was actually there - the tint got
  // applied to nothing, and once the mesh DID finish loading moments later
  // (fresh, opaque, untinted materials), nothing ever reapplied it. that
  // was the "show heatmap is checked but nothing shows until you uncheck
  // and recheck it" bug.
  useEffect(() => {
    if (!memberA || !memberB || pairIndexA === pairIndexB) {
      setDiffHeatmap(null);
      return undefined;
    }
    let cancelled = false;
    setCheckActive(false);
    (async () => {
      try {
        setStatus("loading change map...");
        await heatmapViewerRef.current?.displayMesh(meshRefUrl(memberB.ref), { selectionHasTexture: false });
        if (cancelled) return;
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

  // the Morph animation panel: chains EVERY established timepoint in
  // chronological order (t0 -> t1 -> t2 -> ...), not just the picked A/B
  // pair - showing only the first-to-last morph when 3+ timepoints are
  // available would be no different from having only ever established
  // correspondence between those two, defeating the point of registering
  // the intermediate ones at all. legHeatmaps mirrors that: one diff per
  // consecutive pair along the chain, computed once here rather than
  // per-frame - LongitudinalMorphViewer's own setT scales whichever leg is
  // currently playing by its own local progress (see that component's
  // applyCurrentFrame).
  useEffect(() => {
    const ordered = orderedMembers(correspondenceSet);
    if (ordered.length < 2) {
      setLegHeatmaps(null);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        await morphViewerRef.current?.loadSequence(ordered.map((m) => meshRefUrl(m.ref)));
        if (cancelled) return;
        const diffs = await Promise.all(
          ordered.slice(0, -1).map((m, i) => computeLongitudinalDiff(m.ref, ordered[i + 1].ref)),
        );
        if (!cancelled) setLegHeatmaps(diffs.map((d) => d.heatmap));
      } catch (err) {
        if (!cancelled) setStatus(`morph sequence failed: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [correspondenceSet]);

  useEffect(() => {
    if (showHeatmap && diffHeatmap) heatmapViewerRef.current?.showHeatmap(diffHeatmap, { dim: false });
    else heatmapViewerRef.current?.hideHeatmap();
  }, [diffHeatmap, showHeatmap]);

  useEffect(() => {
    if (showHeatmap && legHeatmaps) morphViewerRef.current?.showHeatmapSequence(legHeatmaps);
    else morphViewerRef.current?.hideHeatmap();
  }, [legHeatmaps, showHeatmap]);

  // samples a handful of evenly-spread vertex INDICES (same indices are
  // valid on both meshes - that's exactly what "correspondence" means
  // here) and drops a distinctly-colored marker at that index's position
  // on each mesh - point i is the same color on both, so a real mismatch
  // (the same color landing somewhere totally different) is obvious at a
  // glance rather than something you'd have to trust a diff number for.
  //
  // a checkbox, not a one-shot button - toggling it off just hides the two
  // panels again (see the checkActive && <...> block below) rather than
  // leaving no way back out of them.
  function handleCheckCorrespondenceToggle(checked) {
    setCheckActive(checked);
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
    const a =
      memberA ??
      (readySlots[0] && { index: readySlots[0].index, label: memberLabel(readySlots[0]), ref: slotStageRef(readySlots[0]), target: readySlots[0].target });
    const b =
      memberB ??
      (readySlots[1] && { index: readySlots[1].index, label: memberLabel(readySlots[1]), ref: slotStageRef(readySlots[1]), target: readySlots[1].target });
    if (!a || !b) return;
    setStatus("generating report...");
    try {
      const target = a.target ?? "cranium";
      const url = await downloadLongitudinalReport(a.ref, b.ref, target, a.label, b.label, !!correspondenceSet);
      triggerDownload(url, "longitudinal_comparison_report.pdf");
      setStatus("");
    } catch (err) {
      setStatus(`report failed: ${err.message}`);
    }
  }

  return (
    <div className="longitudinal-correspondence-tab">
      {readySlots.length >= 2 ? (
        <>
          <div className="longitudinal-toolbar longitudinal-correspondence-controls">
            <label>
              <input type="radio" checked={referenceMode === "slot"} onChange={() => setReferenceMode("slot")} />
              source mesh:
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
          <p className="hint">
            the source mesh's own topology (vertex count and connectivity) is exactly what's preserved across every
            timepoint once correspondence is established - every other mesh gets deformed to approximate the source's
            shape, never the other way around.
          </p>
          {status && <p className="status-line">{status}</p>}
        </>
      ) : (
        <p className="hint">Register at least two timepoints in the Compare tab to fit correspondence automatically, or import already-NICP-fit meshes below.</p>
      )}

      <div className="longitudinal-toolbar longitudinal-correspondence-import">
        <span className="hint">already have meshes NICP-fit to the same template (from a prior session, or another machine)? skip fitting entirely:</span>
        <label>
          target:
          <select value={importTarget} onChange={(e) => setImportTarget(e.target.value)}>
            <option value="cranium">cranium</option>
            <option value="face">face</option>
          </select>
        </label>
        <button type="button" className="button-subtle" onClick={handleImportClick} disabled={importBusy}>
          {importBusy ? "importing..." : "import pre-NICP'd meshes..."}
        </button>
        <input
          ref={importInputRef}
          type="file"
          accept=".ply,.obj,.stl"
          multiple
          className="hidden"
          onChange={handleImportFilesSelected}
        />
      </div>
      {importStatus && <p className="status-line">{importStatus}</p>}

      {correspondenceSet && (
        <>
          <p className="hint">
            {correspondenceSet.members.length} timepoints share point correspondence now (source mesh: {correspondenceSet.referenceLabel}).
            The morph animation below plays through all of them in order; pick any two below for a standalone change
            map.
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
            <label>
              <input type="checkbox" checked={linkCameras} onChange={(e) => setLinkCameras(e.target.checked)} />
              link cameras
            </label>
            <label>
              <input type="checkbox" checked={checkActive} onChange={(e) => handleCheckCorrespondenceToggle(e.target.checked)} />
              check correspondence
            </label>
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
                <h3>Morph animation ({orderedMembers(correspondenceSet).map((m) => m.label).join(" → ")})</h3>
                <MorphControl
                  onT={(t) => morphViewerRef.current?.setT(t)}
                  morphViewerRef={morphViewerRef}
                  legLabels={orderedMembers(correspondenceSet).map((m) => m.label)}
                />
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
