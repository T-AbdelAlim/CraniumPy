import { useState } from "react";
import { downloadFacialBatchExport } from "../../api/facial.js";

// after final review, the batch's own Excel export - identifiers, one
// column per measurement ("Name (ABBR)"), plus a color-swatch legend
// sheet and a "failed" sheet if anything errored (see
// api/routers/facial.py's export_batch). this exact file is also what the
// Cohort workspace later loads as an attached "custom measurements"
// dataset - see frontend/src/workspaces/cohort/CustomMeasurementsPanel.jsx.
export default function ExportPanel({ batchId, resultCount, okCount }) {
  const [status, setStatus] = useState("");

  async function handleExport() {
    setStatus("exporting...");
    try {
      await downloadFacialBatchExport(batchId);
      setStatus("");
    } catch (err) {
      setStatus(`export failed: ${err.message}`);
    }
  }

  return (
    <div className="facial-export-panel">
      <p className="hint">
        {okCount} of {resultCount} files measured successfully.
      </p>
      <button type="button" onClick={handleExport}>
        confirm & export to Excel
      </button>
      {status && <p className="status-line">{status}</p>}
    </div>
  );
}
