import { LANDMARK_NAMES, LANDMARK_LABELS, LANDMARK_DESCRIPTIONS } from "../../lib/landmarks.js";

export default function RegisterPanel({ target, onTargetChange, landmarks, aligned, aligning, alignStatus, onAlign, onReset }) {
  const allPicked = LANDMARK_NAMES.every((n) => n in landmarks);

  return (
    <section>
      <label className="checkbox">
        <input type="radio" name="target" checked={target === "cranium"} onChange={() => onTargetChange("cranium")} />
        cranial (head measurements)
      </label>
      <label className="checkbox">
        <input type="radio" name="target" checked={target === "face"} onChange={() => onTargetChange("face")} />
        facial (asymmetry)
      </label>

      <p className="hint">
        <strong>ctrl/cmd-click</strong> to place a point, <strong>alt-drag</strong> to move one. Pick in this order:
      </p>
      <ol id="landmark-list">
        {LANDMARK_NAMES.map((name) => {
          const p = landmarks[name];
          return (
            <li key={name} data-name={name} className={p ? "picked" : ""}>
              <span className="landmark-swatch" />
              <span className="landmark-label">{LANDMARK_LABELS[name]}</span>
              <span className="landmark-desc">{LANDMARK_DESCRIPTIONS[name]}</span>
              <span className="landmark-value">{p ? `${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}` : "not picked"}</span>
            </li>
          );
        })}
      </ol>

      <div className="toggle-row">
        <button type="button" onClick={onAlign} disabled={!allPicked || aligning || aligned}>
          align
        </button>
        <button type="button" onClick={onReset}>
          reset
        </button>
      </div>
      <p className="status-line">{alignStatus}</p>
    </section>
  );
}
