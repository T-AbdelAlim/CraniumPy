import { useEffect, useMemo, useRef, useState } from "react";
import Viewer from "../../../components/Viewer.jsx";
import { computeHcRingBand, computeMeanShape, computeMeanShapeMeasurements, computeMetopicBand, computeReferenceDiff, computeSagittalBand, meanShapeDownloadUrl, meanShapeMeshUrl } from "../../../api/cohort.js";
import { fetchShippedTemplates } from "../../../api/sessions.js";
import { heatmapMax, heatmapMaxAbs } from "../../../three/measurementsLayer.js";
import InfoTooltip from "../../../components/InfoTooltip.jsx";
import { MEASUREMENT_EXPLAINERS } from "../../../lib/measurementExplainers.js";
import { buildGroupLabel, buildMeanShapeFilename } from "../lib/naming.js";

const MEAN_SHAPE_EXPLAINER =
  "the vertex-by-vertex average shape of every patient in the selected group, each already fit to the same " +
  "template mesh via NICP (see the Preprocessing workspace's \"fit template\" step) - only patients fit to the " +
  "IDENTICAL template are vertex-correspondent and safe to average this way, which is why groups are keyed by " +
  "the template name, not mixed together.";

const SPREAD_EXPLAINER =
  "per-vertex mean distance (mm) from that vertex's own average position, across the patients in this group - " +
  "how much a given point on the surface varies from patient to patient. this is INTER-PATIENT shape spread " +
  "(always positive, teal scale) - not a per-patient asymmetry measure, and not a direction (compare the " +
  "reference-diff view below, or the Analysis workspace's own asymmetry heatmap).";

const REFERENCE_EXPLAINER =
  "signed per-vertex distance (mm) of the mean shape from the chosen reference template, along the template's " +
  "own surface normal - red where the mean shape sits OUTWARD of the reference (more protruded than the plain " +
  "template), blue where it sits INWARD. the reference has to be the exact template this group was NICP-fitted " +
  "to (defaulted below) - a different template's topology won't line up vertex-for-vertex, and the request " +
  "fails with a clear error rather than silently comparing the wrong points.";

const MEASUREMENTS_EXPLAINER =
  "the same craniometrics/asymmetry/frontal-morphology suite the Patients workspace's Analysis tab computes for " +
  "one patient, run instead on this group's averaged mean shape - every patient fed into the mean was already " +
  "rigidly registered onto the exact same fixed reference frame before NICP fitting, so the mean shape's own " +
  "sellion/tragus positions are that same fixed frame, with no per-group landmark tracking needed. numbers here " +
  "describe the AVERAGE shape, not any real patient - see the Stratify tab for the group's own scalar spread.";

const SPREAD_BAND_OVERLAY_EXPLAINER =
  "shows the same +/-1 SD ribbon(s) the PDF report can shade, live on the mesh here: the sagittal/frontal-bossing " +
  "band always (orange), plus the HC-ring band (red, cranium groups) or the metopic band (dark gray, face groups) " +
  "- same underlying data as the report, just rendered as a real 3D ribbon instead of a page in a PDF.";

// colors for the live 3D spread-band ribbons, matching the shading colors
// the PDF report already uses for the same bands (see results_bundle.py's
// _draw_measurements/_draw_metopic fill colors) - the sagittal one has no
// PDF fill color of its own to match (that page uses "#3a3a3a" too), so it
// reuses frontalBossingOverlay.js's own angle-line orange instead, to stay
// visually distinct from the metopic band whenever both could theoretically
// render (they never do - one applies to cranium groups, the other to face).
const HC_RING_BAND_COLOR = 0xd1453d;
const METOPIC_BAND_COLOR = 0x3a3a3a;
const SAGITTAL_BAND_COLOR = 0xea580c;

// groups rows by nicp_template, keeping only rows with a real nicp_mesh_path
// (see api/results_bundle.py's _nicp_mesh_path - blank when no NICP fit was
// ever exported for that patient) - these are the only rows this feature
// can do anything with.
function groupEligibleRows(rows) {
  const groups = {};
  for (const row of rows) {
    const template = row.nicp_template;
    const meshPath = row.nicp_mesh_path;
    if (!template || !meshPath) continue;
    (groups[template] ??= []).push(row);
  }
  return groups;
}

export default function MeanShapeTab({ rows, filters }) {
  const viewerRef = useRef(null);
  const groups = useMemo(() => groupEligibleRows(rows), [rows]);
  const templateNames = Object.keys(groups);
  const [selectedTemplate, setSelectedTemplate] = useState(templateNames[0] || "");
  const [computing, setComputing] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState(null); // {resultId, vertexCount, sourceCount, spreadHeatmap, target}

  // "spread" (unsigned inter-patient variability, sequential teal scale),
  // "reference" (signed diff against a chosen template, diverging red/blue
  // scale), or "measurements" (the same craniometrics/asymmetry/metopic
  // suite the Patients workspace shows) - three different views over the
  // SAME already-computed mean shape, so switching between them re-renders
  // instantly without recomputing the mean (reference diffs and
  // measurements are each fetched lazily, on first switch to that view,
  // and cached so flipping back and forth doesn't refetch).
  const [viewMode, setViewMode] = useState("spread");
  const [referenceTemplate, setReferenceTemplate] = useState("");
  const [shippedTemplates, setShippedTemplates] = useState([]);
  const [referenceHeatmaps, setReferenceHeatmaps] = useState({}); // {templateName: heatmap[]}
  const [referenceStatus, setReferenceStatus] = useState("");
  const [measurements, setMeasurements] = useState(null); // {craniometrics, asymmetry, metopic, frontal_bossing}
  const [measurementsView, setMeasurementsView] = useState("primary"); // "primary" | "asymmetry"
  const [measurementsStatus, setMeasurementsStatus] = useState("");
  // {y, mean_z, sd_z, source_count} - fetched lazily by refreshSpreadBands
  // below (the "show +/-1 SD spread ribbon on mesh" checkbox), the only
  // remaining consumer of this data on this tab.
  const [sagittalBand, setSagittalBand] = useState(null);
  // live 3D spread-band ribbons in "measurements" mode - only enabled while
  // measurementsView is "primary" (see the checkbox render below), cached
  // per band the same way referenceHeatmaps/sagittalBand already are so
  // toggling on/off after the first fetch is instant.
  const [showSpreadBandsOverlay, setShowSpreadBandsOverlay] = useState(false);
  const [hcRingBand, setHcRingBand] = useState(null); // {mean, inner, outer, closed, source_count}
  const [metopicBandData, setMetopicBandData] = useState(null);
  const [spreadBandStatus, setSpreadBandStatus] = useState("");

  const eligibleRows = groups[selectedTemplate] || [];

  useEffect(() => {
    fetchShippedTemplates().then(setShippedTemplates).catch(() => {});
  }, []);

  function clearOverlays() {
    const v = viewerRef.current;
    if (!v) return;
    v.hideMeasurementsOverlay();
    v.hideMetopicOverlay();
    v.hideFrontalBossingOverlay();
    v.hideAllSpreadBands();
    v.setMeshOpacity(1.0);
  }

  // fetches (once, then reuses the cache) and shows every spread band that
  // applies to this group's target, or hides all of them - called by the
  // "show spread ribbon" checkbox and re-called whenever measurements mode
  // is re-entered while that checkbox is already on (see showMeasurements/
  // switchMeasurementsView below).
  async function refreshSpreadBands(enabled) {
    const v = viewerRef.current;
    if (!v || !result) return;
    if (!enabled) {
      v.hideAllSpreadBands();
      return;
    }
    setSpreadBandStatus("computing spread bands...");
    try {
      const meshPaths = eligibleRows.map((row) => row.nicp_mesh_path);

      let sagittal = sagittalBand;
      if (!sagittal) {
        sagittal = await computeSagittalBand(meshPaths, result.target);
        setSagittalBand(sagittal);
      }
      // sagittal_midline_band's own points live at a fixed x (~0, the
      // sellion's x-coordinate in this mesh's own registered frame - see
      // craniumpy_core.cohort.sagittal_band_to_spread_band) - embedding
      // client-side here avoids a whole extra endpoint just for this 3D case.
      const sagittalInner = sagittal.y.map((y, i) => ({ x: 0, y, z: sagittal.mean_z[i] - sagittal.sd_z[i] }));
      const sagittalOuter = sagittal.y.map((y, i) => ({ x: 0, y, z: sagittal.mean_z[i] + sagittal.sd_z[i] }));
      v.showSpreadBand("sagittal", sagittalInner, sagittalOuter, false, SAGITTAL_BAND_COLOR);

      if (result.target === "cranium") {
        let band = hcRingBand;
        if (!band) {
          band = await computeHcRingBand(meshPaths, result.target);
          setHcRingBand(band);
        }
        v.showSpreadBand("hc-ring", band.inner, band.outer, band.closed, HC_RING_BAND_COLOR);
      }
      if (result.target === "face") {
        let band = metopicBandData;
        if (!band) {
          band = await computeMetopicBand(meshPaths, result.target);
          setMetopicBandData(band);
        }
        v.showSpreadBand("metopic", band.inner, band.outer, band.closed, METOPIC_BAND_COLOR);
      }
      setSpreadBandStatus("");
    } catch (err) {
      setSpreadBandStatus(`failed: ${err.message}`);
    }
  }

  function toggleSpreadBands(checked) {
    setShowSpreadBandsOverlay(checked);
    refreshSpreadBands(checked);
  }

  async function handleCompute() {
    setComputing(true);
    setStatus("computing mean shape...");
    setResult(null);
    setReferenceHeatmaps({});
    setMeasurements(null);
    setMeasurementsView("primary");
    setSagittalBand(null);
    setShowSpreadBandsOverlay(false);
    setHcRingBand(null);
    setMetopicBandData(null);
    setSpreadBandStatus("");
    setViewMode("spread");
    // the only reference guaranteed to match this mean shape's topology is
    // the template the group was actually fit to - default to it, the
    // user can still pick a different shipped template and see the real
    // error if it doesn't line up.
    setReferenceTemplate(selectedTemplate);
    try {
      const meshPaths = eligibleRows.map((row) => row.nicp_mesh_path);
      const response = await computeMeanShape(meshPaths);
      await viewerRef.current.displayMesh(meanShapeMeshUrl(response.result_id), { selectionHasTexture: false });
      viewerRef.current.showSequentialHeatmap(response.heatmap);
      viewerRef.current.setMeshOpacity(1.0);
      setResult({
        resultId: response.result_id,
        vertexCount: response.vertex_count,
        sourceCount: response.source_count,
        spreadHeatmap: response.heatmap,
        target: eligibleRows[0]?.target || "cranium",
      });
      setStatus("");
    } catch (err) {
      setStatus(`failed: ${err.message}`);
    } finally {
      setComputing(false);
    }
  }

  async function showSpread() {
    clearOverlays();
    setViewMode("spread");
    viewerRef.current?.showSequentialHeatmap(result.spreadHeatmap);
    // showSequentialHeatmap always dims the mesh to
    // ANALYSIS_DEFAULT_MESH_OPACITY as a side effect (see Viewer.jsx) - that
    // makes sense for the single-patient Analysis workspace, where a
    // measurement/frontal-bossing construction is drawn on top and needs to
    // stay visible through the surface, but this is a plain heatmap with
    // nothing else overlaid, so there's nothing to dim FOR - put it back to
    // fully opaque, same as the very first time this view shows (right
    // after handleCompute).
    viewerRef.current?.setMeshOpacity(1.0);
  }

  async function showReferenceDiff(templateName) {
    clearOverlays();
    setViewMode("reference");
    setReferenceTemplate(templateName);
    const cached = referenceHeatmaps[templateName];
    if (cached) {
      viewerRef.current?.showHeatmap(cached);
      viewerRef.current?.setMeshOpacity(1.0); // see showSpread's own comment
      return;
    }
    setReferenceStatus("computing reference diff...");
    try {
      const { heatmap } = await computeReferenceDiff(result.resultId, templateName);
      setReferenceHeatmaps((prev) => ({ ...prev, [templateName]: heatmap }));
      viewerRef.current?.showHeatmap(heatmap);
      viewerRef.current?.setMeshOpacity(1.0); // see showSpread's own comment
      setReferenceStatus("");
    } catch (err) {
      setReferenceStatus(`failed: ${err.message}`);
    }
  }

  function applyMeasurementsOverlay(data, view) {
    const v = viewerRef.current;
    if (!v) return;
    clearOverlays();
    v.hideHeatmap();
    if (view === "asymmetry") {
      v.showHeatmap(data.asymmetry.heatmap);
      return;
    }
    if (data.craniometrics) {
      v.showMeasurementsOverlay({
        hcPolygon: data.craniometrics.hc_slice_polygon,
        frontOpt: data.craniometrics.front_opt,
        occOpt: data.craniometrics.occ_opt,
        lhOpt: data.craniometrics.lh_opt,
        rhOpt: data.craniometrics.rh_opt,
      });
    }
    if (data.metopic) {
      v.showMetopicOverlay(data.metopic);
    }
    if (data.frontal_bossing) {
      v.showFrontalBossingOverlay(data.frontal_bossing);
    }
    v.setMeshOpacity(0.35);
  }

  async function showMeasurements() {
    setViewMode("measurements");
    if (measurements) {
      applyMeasurementsOverlay(measurements, measurementsView);
      if (measurementsView !== "asymmetry" && showSpreadBandsOverlay) refreshSpreadBands(true);
      return;
    }
    setMeasurementsStatus("computing measurements...");
    try {
      const data = await computeMeanShapeMeasurements(result.resultId, result.target);
      setMeasurements(data);
      applyMeasurementsOverlay(data, "primary");
      setMeasurementsView("primary");
      setMeasurementsStatus("");
      if (showSpreadBandsOverlay) refreshSpreadBands(true);
    } catch (err) {
      setMeasurementsStatus(`failed: ${err.message}`);
    }
  }

  function switchMeasurementsView(view) {
    setMeasurementsView(view);
    if (measurements) applyMeasurementsOverlay(measurements, view);
    if (view !== "asymmetry" && showSpreadBandsOverlay) refreshSpreadBands(true);
  }

  if (templateNames.length === 0) {
    return (
      <p className="hint">
        No NICP-fitted patients in this cohort yet. fit a template to a patient in the Preprocessing workspace and
        export it (with meshes included) to make it eligible here.
      </p>
    );
  }

  const activeReferenceHeatmap = referenceHeatmaps[referenceTemplate];
  const showModeToggle = measurements && (measurements.craniometrics || measurements.metopic);

  return (
    <section>
      <p className="hint">
        3D mean shape across a template group
        <InfoTooltip text={MEAN_SHAPE_EXPLAINER} />
      </p>
      <label htmlFor="mean-shape-template">template group</label>
      <select
        id="mean-shape-template"
        value={selectedTemplate}
        onChange={(e) => {
          setSelectedTemplate(e.target.value);
          setResult(null);
          setStatus("");
        }}
      >
        {templateNames.map((name) => (
          <option key={name} value={name}>
            {name} ({groups[name].length} eligible)
          </option>
        ))}
      </select>

      {eligibleRows.length > 0 && (
        <p className="hint">
          Will average {eligibleRows.length} patient{eligibleRows.length === 1 ? "" : "s"} matching:{" "}
          <strong>{buildGroupLabel(filters, selectedTemplate)}</strong>
        </p>
      )}
      <button type="button" onClick={handleCompute} disabled={computing || eligibleRows.length === 0}>
        compute mean shape
      </button>
      {status && <p className="status-line">{status}</p>}
      {result && (
        <>
          <p className="hint">
            {result.sourceCount} patients averaged, {result.vertexCount} vertices.
          </p>
          <button
            type="button"
            className="button-subtle"
            onClick={() => {
              window.location.href = meanShapeDownloadUrl(result.resultId, buildMeanShapeFilename(filters, selectedTemplate));
            }}
          >
            download mesh (.ply)
          </button>
        </>
      )}

      {result && (
        <>
          <div className="mode-toggle">
            <button type="button" className={viewMode === "spread" ? "active" : ""} onClick={showSpread}>
              spread
            </button>
            <button
              type="button"
              className={viewMode === "reference" ? "active" : ""}
              onClick={() => showReferenceDiff(referenceTemplate || selectedTemplate)}
            >
              vs reference template
            </button>
            <button type="button" className={viewMode === "measurements" ? "active" : ""} onClick={showMeasurements}>
              measurements
            </button>
          </div>
          {viewMode === "spread" && (
            <p className="hint">
              inter-patient shape spread
              <InfoTooltip text={SPREAD_EXPLAINER} />
            </p>
          )}
          {viewMode === "reference" && (
            <>
              <label htmlFor="mean-shape-reference">
                reference template
                <InfoTooltip text={REFERENCE_EXPLAINER} />
              </label>
              <select
                id="mean-shape-reference"
                value={referenceTemplate}
                onChange={(e) => showReferenceDiff(e.target.value)}
              >
                {shippedTemplates.map((t) => (
                  <option key={t.name} value={t.name}>{t.description}</option>
                ))}
              </select>
              {referenceStatus && <p className="status-line">{referenceStatus}</p>}
            </>
          )}
          {viewMode === "measurements" && (
            <>
              <p className="hint">
                same measurements as the Patients workspace, on this group's mean shape
                <InfoTooltip text={MEASUREMENTS_EXPLAINER} />
              </p>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showSpreadBandsOverlay}
                  disabled={measurementsView === "asymmetry"}
                  onChange={(e) => toggleSpreadBands(e.target.checked)}
                />
                show +/-1 SD spread ribbon on mesh
                <InfoTooltip text={SPREAD_BAND_OVERLAY_EXPLAINER} />
              </label>
              {spreadBandStatus && <p className="status-line">{spreadBandStatus}</p>}
              {measurementsStatus && <p className="status-line">{measurementsStatus}</p>}
              {measurements && (
                <>
                  {showModeToggle && (
                    <div className="mode-toggle">
                      <button
                        type="button"
                        className={measurementsView !== "asymmetry" ? "active" : ""}
                        onClick={() => switchMeasurementsView("primary")}
                      >
                        {measurements.craniometrics ? "Cranial Measurements" : "Forehead Morphology"}
                      </button>
                      <button
                        type="button"
                        className={measurementsView === "asymmetry" ? "active" : ""}
                        onClick={() => switchMeasurementsView("asymmetry")}
                      >
                        Asymmetry
                      </button>
                    </div>
                  )}
                  {measurementsView !== "asymmetry" && measurements.craniometrics && (
                    <table className="measurements-table cohort-ws-table">
                      <tbody>
                        <tr>
                          <th>OFD (depth)<InfoTooltip text={MEASUREMENT_EXPLAINERS.depthMm} /></th>
                          <td>{measurements.craniometrics.depth_mm.toFixed(1)} mm</td>
                        </tr>
                        <tr>
                          <th>BPD (breadth)<InfoTooltip text={MEASUREMENT_EXPLAINERS.breadthMm} /></th>
                          <td>{measurements.craniometrics.breadth_mm.toFixed(1)} mm</td>
                        </tr>
                        <tr>
                          <th>Cephalic index<InfoTooltip text={MEASUREMENT_EXPLAINERS.cephalicIndex} /></th>
                          <td>{measurements.craniometrics.cephalic_index.toFixed(1)}</td>
                        </tr>
                        <tr>
                          <th>Head circumference<InfoTooltip text={MEASUREMENT_EXPLAINERS.circumferenceCm} /></th>
                          <td>{measurements.craniometrics.circumference_cm.toFixed(1)} cm</td>
                        </tr>
                        <tr>
                          <th>Volume<InfoTooltip text={MEASUREMENT_EXPLAINERS.meshVolumeCc} /></th>
                          <td>{measurements.craniometrics.mesh_volume_cc.toFixed(1)} cc</td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                  {measurementsView !== "asymmetry" && measurements.metopic && (
                    <table className="measurements-table cohort-ws-table">
                      <tbody>
                        <tr>
                          <th>Frontal angle<InfoTooltip text={MEASUREMENT_EXPLAINERS.frontalAngleDeg} /></th>
                          <td>{measurements.metopic.frontal_angle_deg.toFixed(1)}&deg;</td>
                        </tr>
                        <tr>
                          <th>Ridge protrusion<InfoTooltip text={MEASUREMENT_EXPLAINERS.ridgeProtrusion} /></th>
                          <td>{measurements.metopic.ridge_protrusion_mm.toFixed(1)} mm</td>
                        </tr>
                        <tr>
                          <th>Parabolic deviation index<InfoTooltip text={MEASUREMENT_EXPLAINERS.parabolicDeviationIndex} /></th>
                          <td>{measurements.metopic.parabolic_deviation_index.toFixed(2)} mm</td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                  {measurementsView !== "asymmetry" && measurements.frontal_bossing && (
                    <table className="measurements-table cohort-ws-table">
                      <tbody>
                        <tr>
                          <th>Frontal bossing angle<InfoTooltip text={MEASUREMENT_EXPLAINERS.frontalBossingAngle} /></th>
                          <td>{measurements.frontal_bossing.angle_deg.toFixed(1)}&deg;</td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                  {measurementsView === "asymmetry" && (
                    <table className="measurements-table cohort-ws-table">
                      <tbody>
                        <tr>
                          <th>
                            Mean asymmetry index
                            <InfoTooltip
                              text={measurements.craniometrics ? MEASUREMENT_EXPLAINERS.cranialAsymmetryIndex : MEASUREMENT_EXPLAINERS.facialAsymmetryIndex}
                            />
                          </th>
                          <td>{measurements.asymmetry.mean_asymmetry_index.toFixed(2)} mm</td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      <div className="cohort-ws-mean-shape-viewer">
        <Viewer ref={viewerRef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
        {!result && <p className="hint overlay">Pick a group and compute a mean shape to see it here.</p>}
        {result && viewMode === "spread" && (
          <div className="heatmap-scalar-bar">
            <span>+{heatmapMax(result.spreadHeatmap).toFixed(1)} mm spread</span>
            <div className="scalar-bar-gradient scalar-bar-gradient-sequential" />
            <span>0 mm</span>
          </div>
        )}
        {result && viewMode === "reference" && activeReferenceHeatmap && (
          <div className="heatmap-scalar-bar">
            <span>+{heatmapMaxAbs(activeReferenceHeatmap).toFixed(1)} mm out</span>
            <div className="scalar-bar-gradient" />
            <span>-{heatmapMaxAbs(activeReferenceHeatmap).toFixed(1)} mm in</span>
          </div>
        )}
        {result && viewMode === "measurements" && measurementsView === "asymmetry" && measurements && (
          <div className="heatmap-scalar-bar">
            <span>+{heatmapMaxAbs(measurements.asymmetry.heatmap).toFixed(1)} mm</span>
            <div className="scalar-bar-gradient" />
            <span>-{heatmapMaxAbs(measurements.asymmetry.heatmap).toFixed(1)} mm</span>
          </div>
        )}
      </div>
    </section>
  );
}
