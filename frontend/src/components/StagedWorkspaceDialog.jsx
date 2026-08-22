// shown either when switching into the Longitudinal workspace while one or
// more meshes are staged (see App.jsx's handleStageForLongitudinal, set
// from the Preprocessing panel's "stage for Longitudinal" control), or when
// returning to any workspace that has a preserved snapshot from the last
// time it was left (see App.jsx's longitudinalSnapshot/cohortSnapshot/
// pendingRestore) - both are "there's something here from before, pick it
// up or start clean?" prompts, just with different copy, so this stays one
// shared component with the title/message/confirmLabel driven by props
// (defaulting to the original staging wording) rather than two near-
// identical dialogs. unlike ConfirmDialog.jsx (one destructive action vs
// "stay here"), both choices here are equally valid, just different: pick
// up what's there, or start from a blank workspace anyway. same visual
// language/CSS classes as ConfirmDialog for consistency, the "load"
// choice as a plain (primary-blue) button since it's the more likely pick,
// "load clean" as button-subtle (grey) - matching the emphasis every other
// primary/secondary action pair in this app already uses.
export default function StagedWorkspaceDialog({
  title = "Staged meshes found",
  message,
  count,
  confirmLabel = "load staged workspace",
  onLoadStaged,
  onLoadClean,
}) {
  const body =
    message ??
    `${count} mesh${count === 1 ? "" : "es"} ${count === 1 ? "was" : "were"} staged for Longitudinal analysis from ` +
      "the Per patient workspace. Load them into this workspace now, or start clean?";
  return (
    <div className="confirm-dialog-backdrop" onClick={onLoadClean}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="confirm-dialog-actions">
          <button type="button" className="button-subtle" onClick={onLoadClean}>
            load clean workspace
          </button>
          <button type="button" onClick={onLoadStaged}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
