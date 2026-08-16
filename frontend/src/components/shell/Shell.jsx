import ResizablePane from "./ResizablePane.jsx";

// the persistent application shell: left nav, top context bar, center
// workspace (with its own tab strip), right inspector. only "Patients" is
// rendered in the nav - Research/References/History have nothing behind
// them yet, and a nav entry with nowhere to go is worse than no entry. no
// routing here either - workspace switching is local tab state until
// patient persistence gives routes something real to key on (:patientId).
// a bottom jobs bar slots into this grid once an async job (register,
// analyze) actually exists to report on.
//
// nav/inspector are each wrapped in a ResizablePane (its own width/collapse
// state) rather than fixed grid columns - "auto 1fr auto" below just lets
// each pane's own inline-styled width drive its track directly, so Shell
// itself carries no width state.
export default function Shell({
  contextLabel,
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
        <span className="shell-brand">CraniumPy</span>
        {contextLabel && <span className="shell-context">{contextLabel}</span>}
      </header>

      <ResizablePane side="left" defaultWidth={230} storageKey="nav">
        <nav className="shell-nav">
          <div className="shell-nav-top">
            <div className="shell-nav-item active">Patients</div>
          </div>
          {metadataForm && <div className="shell-nav-bottom">{metadataForm}</div>}
        </nav>
      </ResizablePane>

      <main className="shell-workspace">
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
