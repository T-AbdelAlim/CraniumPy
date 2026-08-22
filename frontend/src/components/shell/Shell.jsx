import ResizablePane from "./ResizablePane.jsx";

// the persistent application shell: left nav, top context bar, center
// workspace (with its own tab strip), right inspector. the nav switches
// between the top-level app modes - "Per patient" (single-patient
// preprocess/analyze/export, everything else in this app), "Longitudinal"
// (follow-up comparison across a patient's own timepoints - see
// workspaces/longitudinal/LongitudinalWorkspace.jsx), "Facial Anthropometrics"
// (custom point-to-point measurements batch-extracted across many
// NICP-registered meshes - see workspaces/facial/FacialWorkspace.jsx), and
// "Cohort" (batch/cohort analysis across already-exported patients - see
// workspaces/cohort/CohortWorkspace.jsx). no routing here either -
// workspace switching is local tab state until patient persistence gives
// routes something real to key on (:patientId). a bottom jobs bar slots
// into this grid once an async job (register, analyze) actually exists to
// report on.
//
// nav/inspector are each wrapped in a ResizablePane (its own width/collapse
// state) rather than fixed grid columns - "auto 1fr auto" below just lets
// each pane's own inline-styled width drive its track directly, so Shell
// itself carries no width state.
export default function Shell({
  contextLabel,
  appMode,
  onAppModeChange,
  workspaces,
  activeWorkspace,
  onWorkspaceChange,
  workspace,
  inspectorTitle,
  inspector,
  metadataForm,
}) {
  return (
    <div className="shell">
      <header className="shell-topbar">
        <span className="shell-brand">CraniumPy v2.0</span>
        {contextLabel && <span className="shell-context">{contextLabel}</span>}
      </header>

      <ResizablePane side="left" defaultWidth={230} storageKey="nav">
        <nav className="shell-nav">
          <div className="shell-nav-top">
            <h3 className="metadata-form-title">Workspace</h3>
            <button
              type="button"
              className={appMode === "patients" ? "shell-nav-item active" : "shell-nav-item"}
              onClick={() => onAppModeChange("patients")}
            >
              Per patient
            </button>
            <button
              type="button"
              className={appMode === "longitudinal" ? "shell-nav-item active" : "shell-nav-item"}
              onClick={() => onAppModeChange("longitudinal")}
            >
              Longitudinal
            </button>
            <button
              type="button"
              className={appMode === "facial" ? "shell-nav-item active" : "shell-nav-item"}
              onClick={() => onAppModeChange("facial")}
            >
              Facial Anthropometrics
            </button>
            <button
              type="button"
              className={appMode === "cohort" ? "shell-nav-item active" : "shell-nav-item"}
              onClick={() => onAppModeChange("cohort")}
            >
              Cohort
            </button>
          </div>
          {metadataForm && <div className="shell-nav-bottom">{metadataForm}</div>}
        </nav>
      </ResizablePane>

      <main className="shell-workspace">
        {workspaces.length > 0 && (
          <div className="shell-workspace-tabs">
            {workspaces.map((w) => (
              <button
                key={w.id}
                type="button"
                className={w.id === activeWorkspace ? "shell-tab active" : "shell-tab"}
                onClick={() => onWorkspaceChange(w.id)}
              >
                {w.label}
              </button>
            ))}
          </div>
        )}
        <div className="shell-workspace-content">{workspace}</div>
      </main>

      <ResizablePane side="right" defaultWidth={320} storageKey="inspector">
        <aside className="shell-inspector">
          <h2>{inspectorTitle}</h2>
          {inspector}
        </aside>
      </ResizablePane>
    </div>
  );
}
