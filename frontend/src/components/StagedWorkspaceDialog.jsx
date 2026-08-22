// shown when switching into the Longitudinal workspace while one or more
// meshes are staged (see App.jsx's handleStageForLongitudinal, set from the
// Preprocessing panel's "stage for Longitudinal" control) - unlike
// ConfirmDialog.jsx (one destructive action vs "stay here"), both choices
// here are equally valid, just different: pick up the staged meshes, or
// start from a blank workspace anyway. same visual language/CSS classes as
// ConfirmDialog for consistency, "load staged" as a plain (primary-blue)
// button since it's the more likely choice, "load clean" as button-subtle
// (grey) - matching the emphasis every other primary/secondary action pair
// in this app already uses.
export default function StagedWorkspaceDialog({ count, onLoadStaged, onLoadClean }) {
  return (
    <div className="confirm-dialog-backdrop" onClick={onLoadClean}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>Staged meshes found</h3>
        <p>
          {count} mesh{count === 1 ? "" : "es"} {count === 1 ? "was" : "were"} staged for Longitudinal analysis from
          the Per patient workspace. Load them into this workspace now, or start clean?
        </p>
        <div className="confirm-dialog-actions">
          <button type="button" className="button-subtle" onClick={onLoadClean}>
            load clean workspace
          </button>
          <button type="button" onClick={onLoadStaged}>
            load staged workspace
          </button>
        </div>
      </div>
    </div>
  );
}
