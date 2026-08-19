// builds a short, human-readable filename for a mean-shape export from the
// active FilterBar filters (see FilterBar.jsx for the filter shape) - so a
// saved file names itself after whatever the user actually stratified to,
// without them having to remember and retype it (e.g. filtering to
// diagnosis=trigonocephaly, image_timing=pre-op, treatment=surgical gives
// "trigonocephaly_pre-op_surgical_mean.ply").

const SHORT_COLUMN_LABELS = {
  age_imaging: "age",
  age_intervention_months: "interventionage",
};

function sanitizeSegment(value) {
  return String(value)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// falls back to the template group's own name when no filters are active,
// so the file is still self-describing rather than just "mean.ply".
export function buildMeanShapeFilename(filters, templateName) {
  const segments = [];
  for (const filter of filters || []) {
    if (filter.type === "numeric") {
      if (filter.min === null && filter.max === null) continue;
      const label = SHORT_COLUMN_LABELS[filter.column] || sanitizeSegment(filter.column);
      segments.push(`${label}${filter.min ?? ""}-${filter.max ?? ""}`);
    } else {
      if (!filter.values || filter.values.length === 0) continue;
      const shown = filter.values.slice(0, 2).map(sanitizeSegment).join("-");
      segments.push(filter.values.length > 2 ? `${shown}-${filter.values.length}grp` : shown);
    }
  }
  if (segments.length === 0) segments.push(sanitizeSegment(templateName) || "cohort");
  return `${segments.join("_")}_mean.ply`;
}

// same active-filter summary as buildMeanShapeFilename, but as a plain
// human-readable comma-joined phrase (e.g. "trigonocephaly, pre-op,
// surgical") rather than a sanitized filename segment - used for the mean
// shape PDF report's own title page and its downloaded filename (see
// api/cohort.js's downloadMeanShapeReport), where actual punctuation/case
// reads better than a filename-safe slug.
export function buildGroupLabel(filters, templateName) {
  const segments = [];
  for (const filter of filters || []) {
    if (filter.type === "numeric") {
      if (filter.min === null && filter.max === null) continue;
      const label = SHORT_COLUMN_LABELS[filter.column] || filter.column;
      const lo = filter.min ?? "";
      const hi = filter.max ?? "";
      segments.push(`${label} ${lo}-${hi}`);
    } else {
      if (!filter.values || filter.values.length === 0) continue;
      segments.push(filter.values.join("/"));
    }
  }
  if (segments.length === 0) segments.push(templateName || "cohort");
  return segments.join(", ");
}
