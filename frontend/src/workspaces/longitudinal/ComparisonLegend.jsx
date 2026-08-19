// one swatch + label per compared slot - reuses the .viewer-legend* CSS
// already defined for the template-overlay comparison (see index.css),
// just rendered as a normal (non-viewer-overlaid) row strip here instead of
// pinned to a corner of the canvas, since the Longitudinal workspace shows
// N separate viewers rather than one shared scene.
export default function ComparisonLegend({ slots }) {
  return (
    <div className="longitudinal-legend">
      {slots.map((slot, i) => (
        <div key={slot.id} className="longitudinal-legend-row">
          <span className="viewer-legend-swatch" style={{ background: slot.color }} />
          <span>{slot.label || `Timepoint ${i}`}</span>
        </div>
      ))}
    </div>
  );
}
