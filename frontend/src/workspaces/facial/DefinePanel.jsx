import Viewer from "../../components/Viewer.jsx";
import MeasurementForm from "./MeasurementForm.jsx";
import MeasurementLegend from "./MeasurementLegend.jsx";
import { isDesktopApp, pickFileNative } from "../../lib/desktop.js";

// the definition phase: place points on the template (ctrl-click) and move
// them (alt-drag) exactly like the Patients workspace's own landmark
// picking (see Viewer.jsx - reused completely unchanged, just fed a
// dynamic points dict instead of the fixed sellion/tragus set), build up
// measurements against it, see live values, then move to Batch once ready.
export default function DefinePanel({
  viewerRef,
  points,
  landmarkColorByPoint,
  onPick,
  onDrag,
  templateStatus,
  templateSource,
  onLoadCustomTemplate,
  onUseDefaultTemplate,
  measurements,
  measurementValues,
  measurementValueErrors,
  pendingMeasurement,
  onStartType,
  onConfirmMeasurement,
  onCancelPending,
  onRemoveMeasurement,
  canProceedToBatch,
  onProceedToBatch,
}) {
  async function handleChooseCustomTemplate() {
    if (!isDesktopApp()) return; // browser custom-template upload isn't wired yet - desktop-only for now, same scope as this app's other custom-template flows
    const paths = await pickFileNative(false, (msg) => onLoadCustomTemplate(null, msg));
    if (!paths || paths.length === 0) return;
    onLoadCustomTemplate(paths[0], null);
  }

  return (
    <div className="facial-define-panel">
      <div className="facial-toolbar">
        <span className="hint">
          template: {templateSource === "custom" ? "custom" : "face (nasion origin)"} - {templateStatus}
        </span>
        {templateSource === "custom" ? (
          <button type="button" className="button-subtle" onClick={onUseDefaultTemplate}>
            use default template
          </button>
        ) : (
          isDesktopApp() && (
            <button type="button" className="button-subtle" onClick={handleChooseCustomTemplate}>
              use custom template...
            </button>
          )
        )}
      </div>

      <div className="facial-define-layout">
        <div className="facial-define-viewer">
          <Viewer ref={viewerRef} wireframe={false} textureEnabled={false} landmarks={points} landmarkColors={landmarkColorByPoint} onPick={onPick} onDrag={onDrag} />
          <p className="hint facial-define-hint">ctrl-click to place a point, alt-drag to move one.</p>
        </div>
        <div className="facial-define-sidebar">
          <MeasurementForm
            pendingType={pendingMeasurement?.type ?? null}
            pendingPointCount={pendingMeasurement?.pointIds.length ?? 0}
            existingNames={measurements.map((m) => m.name)}
            existingAbbreviations={measurements.map((m) => m.abbreviation)}
            onStartType={onStartType}
            onConfirm={onConfirmMeasurement}
            onCancel={onCancelPending}
          />
          <MeasurementLegend
            measurements={measurements}
            values={measurementValues}
            valueErrors={measurementValueErrors}
            onRemove={onRemoveMeasurement}
          />
          <button type="button" onClick={onProceedToBatch} disabled={!canProceedToBatch}>
            continue to batch extraction
          </button>
          {!canProceedToBatch && <p className="hint">define at least one measurement first.</p>}
        </div>
      </div>
    </div>
  );
}
