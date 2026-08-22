// a small, generic modal confirmation - currently only used by App.jsx's
// workspace-switch guard (see handleAppModeChange: switching away from
// Per patient/Longitudinal/Cohort while it still has data loaded would
// silently throw that data away, since each top-level workspace's state
// lives only as long as it stays mounted - see App.jsx's own comment on
// why). built as a plain component rather than window.confirm() so it
// matches this app's own dark theme instead of the OS's native dialog
// chrome, and so its wording can actually explain what's about to happen
// instead of a bare "OK/Cancel".
export default function ConfirmDialog({ title, message, confirmLabel = "Switch anyway", cancelLabel = "Stay here", onConfirm, onCancel }) {
  return (
    <div className="confirm-dialog-backdrop" onClick={onCancel}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        {title && <h3>{title}</h3>}
        <p>{message}</p>
        <div className="confirm-dialog-actions">
          <button type="button" className="button-subtle" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
