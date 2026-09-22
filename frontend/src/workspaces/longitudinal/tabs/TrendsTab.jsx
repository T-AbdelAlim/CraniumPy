import { useState } from "react";
import TrendsChart from "../../../components/TrendsChart.jsx";
import InfoTooltip from "../../../components/InfoTooltip.jsx";
import { MEASUREMENT_EXPLAINERS } from "../../../lib/measurementExplainers.js";
import { TREND_METRIC_GROUPS, ALL_TREND_METRICS, trendMetricColor } from "../lib/trendMetrics.js";
import { slotLabel } from "../lib/meshRef.js";
import { exportFolderName } from "../lib/exportNaming.js";
import { saveTrendsExport } from "../../../api/longitudinal.js";
import { isDesktopApp, pickFolderNative } from "../../../lib/desktop.js";

const metricColumnLabel = (m) => (m.unit ? `${m.label} (${m.unit})` : m.label);

// the third Longitudinal tab: any cranial/facial measurement or angle,
// plotted across every staged timepoint (see lib/trendMetrics.js for the
// full catalog and where it's grouped/colored). reads the same slots
// CompareTab/MeasurementComparisonTable already read - no fetch of its own,
// every ready slot's measurements are already sitting in slot.measurements.
export default function TrendsTab({ slots, selectedMetricIds, onSelectedMetricIdsChange, exportDestDir, onExportDestDirChange }) {
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState("");

  const ready = slots.filter((s) => s.ready && s.measurements);
  if (ready.length === 0) {
    return <p className="hint">Register at least one timepoint to see its measurements here.</p>;
  }

  const readyIndices = slots.map((s, i) => i).filter((i) => slots[i].ready);
  const selectedMetrics = ALL_TREND_METRICS.filter((m) => selectedMetricIds.includes(m.id));
  const xLabels = slots.map((s, i) => slotLabel(s, i));
  const series = selectedMetrics.map((m) => ({
    id: m.id,
    label: m.label,
    unit: m.unit,
    color: trendMetricColor(m.id),
    points: slots.map((s, i) => ({ x: i, y: s.ready && s.measurements ? (s.measurements[m.group]?.[m.key] ?? null) : null })),
  }));
  const units = new Set(selectedMetrics.map((m) => m.unit).filter(Boolean));
  const folderName = exportFolderName("trend", slots, readyIndices);

  function toggleMetric(id) {
    onSelectedMetricIdsChange(
      selectedMetricIds.includes(id) ? selectedMetricIds.filter((x) => x !== id) : [...selectedMetricIds, id]
    );
  }

  async function handleChooseFolder() {
    const folder = await pickFolderNative((msg) => setExportStatus(`Couldn't open the folder picker: ${msg}`));
    if (folder) onExportDestDirChange(folder);
  }

  async function handleExportResults() {
    setExporting(true);
    setExportStatus("exporting...");
    try {
      const payload = series.map((s) => ({ label: s.label, unit: s.unit, color: s.color, values: s.points.map((p) => p.y) }));
      const { saved_to: savedTo } = await saveTrendsExport(xLabels, payload, exportDestDir, folderName);
      setExportStatus(`Saved to ${savedTo}`);
    } catch (err) {
      setExportStatus(`export failed: ${err.message}`);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="trends-tab">
      <div className="trends-metric-picker">
        {TREND_METRIC_GROUPS.map((group) => (
          <div key={group.title} className="trends-metric-group">
            <p className="trends-metric-group-title">{group.title}</p>
            {group.metrics.map((m) => (
              <label key={m.id} className="checkbox trends-metric-checkbox">
                <input type="checkbox" checked={selectedMetricIds.includes(m.id)} onChange={() => toggleMetric(m.id)} />
                <span className="viewer-legend-swatch" style={{ background: trendMetricColor(m.id), display: "inline-block" }} />
                {metricColumnLabel(m)}
                {m.explainer && <InfoTooltip text={MEASUREMENT_EXPLAINERS[m.explainer]} />}
              </label>
            ))}
          </div>
        ))}
      </div>

      {units.size > 1 && (
        <p className="hint">
          Selected measurements use different units ({Array.from(units).join(", ")}) - shown on one shared axis.
        </p>
      )}

      <TrendsChart series={series} xLabels={xLabels} />

      {isDesktopApp() && (
        <>
          <p className="hint">
            export to: {exportDestDir ? `${exportDestDir}\\${folderName}` : "no folder chosen yet"}
          </p>
          <div className="trends-toolbar">
            <button type="button" className="button-subtle" onClick={handleChooseFolder}>
              select export folder...
            </button>
            <button
              type="button"
              onClick={handleExportResults}
              disabled={exporting || selectedMetrics.length === 0 || !exportDestDir}
            >
              export results
            </button>
          </div>
          {exportStatus && <p className="status-line">{exportStatus}</p>}
        </>
      )}
    </div>
  );
}
