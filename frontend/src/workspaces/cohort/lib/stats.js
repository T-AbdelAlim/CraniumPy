// client-side descriptive stats + binning for the Cohort workspace - fast
// and interactive (no round trip per filter/stratify tweak), unlike the
// *inferential* tests (t-test/ANOVA/etc.), which stay server-side via
// api/cohort.js's runStatsTest (scipy.stats - accurate p-values are easy to
// get subtly wrong hand-rolled, not worth reimplementing here).
//
// every cell coming out of load_cohort_xlsx (see api/cohort.js) is a plain
// string, even the numeric ones - a cohort spreadsheet is sparse (a given
// row may just not have a value for a given column), so treating "" as
// "missing" rather than 0 matters everywhere below.

// "" -> null (missing), otherwise a finite number or null (not numeric).
export function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// a column counts as numeric when every non-blank cell parses as a finite
// number - one stray "n/a" or free-text note makes it categorical instead,
// which is the safer default (a categorical column just can't be plotted/
// stratified numerically, whereas silently coercing "n/a" to NaN would drop
// data with no indication anything was lost).
export function columnType(rows, column) {
  let sawValue = false;
  for (const row of rows) {
    const raw = row[column];
    if (raw === undefined || raw === "") continue;
    sawValue = true;
    if (toNumber(raw) === null) return "categorical";
  }
  return sawValue ? "numeric" : "categorical";
}

// fraction of rows with a non-blank value in `column`, 0..1.
export function completeness(rows, column) {
  if (rows.length === 0) return 0;
  let filled = 0;
  for (const row of rows) {
    if (row[column] !== undefined && row[column] !== "") filled += 1;
  }
  return filled / rows.length;
}

// numeric values for `column` across rows, skipping missing/non-numeric
// cells entirely (not coerced to 0) - the correct input for any descriptive
// stat or plot below.
export function numericValues(rows, column) {
  const out = [];
  for (const row of rows) {
    const n = toNumber(row[column]);
    if (n !== null) out.push(n);
  }
  return out;
}

// distinct non-blank values of a categorical column, in first-seen order -
// used for stratify-by-category dropdowns and legends.
export function distinctValues(rows, column) {
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const v = row[column];
    if (v === undefined || v === "" || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

// filters is [{column, type: "categorical", values: string[]}] for a
// categorical column (keep rows whose value is one of `values`) or
// [{column, type: "numeric", min: number|null, max: number|null}] for a
// numeric column (keep rows within [min, max], either bound optional) -
// AND'ed across different filters, OR'ed within one categorical filter's
// own values. this is the shape that backs "pre-op only", "compare pre-op
// vs post-op within one treatment group" (a categorical filter on
// treatment, then stratify by image_timing on what's left), or "age at
// imaging between 2 and 3" (a numeric range filter on age_imaging).
//
// an inactive filter (no values checked, or both bounds blank) is treated
// as a no-op rather than matching nothing - an empty/unset filter row is
// far more likely to be "haven't picked yet" than "deliberately show zero
// rows", and the latter is a confusing dead end a user would have to
// notice and undo. a numeric filter against a row missing that value
// entirely DOES exclude the row, though - there's no sensible "unbounded"
// reading of a blank cell against a real min/max range.
export function applyFilters(rows, filters) {
  const active = (filters || []).filter((f) =>
    f.type === "numeric" ? f.min !== null || f.max !== null : f.column && f.values.length > 0,
  );
  if (active.length === 0) return rows;
  return rows.filter((row) =>
    active.every((f) => {
      if (f.type !== "numeric") return f.values.includes(row[f.column]);
      const v = toNumber(row[f.column]);
      if (v === null) return false;
      if (f.min !== null && v < f.min) return false;
      if (f.max !== null && v > f.max) return false;
      return true;
    }),
  );
}

function quantile(sorted, q) {
  if (sorted.length === 0) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// mean/median/SD (sample, n-1)/quartiles/min/max/IQR for a plain number[].
// null fields when there isn't enough data (n=0 for everything, n=1 for SD)
// rather than 0/NaN, so a caller can render "-" instead of a misleading number.
export function describe(values) {
  const n = values.length;
  if (n === 0) {
    return { n: 0, mean: null, median: null, sd: null, min: null, max: null, q1: null, q3: null, iqr: null };
  }
  const sorted = [...values].sort((a, b) => a - b);
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const sd = n > 1 ? Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : null;
  const q1 = quantile(sorted, 0.25);
  const q3 = quantile(sorted, 0.75);
  return {
    n,
    mean,
    median: quantile(sorted, 0.5),
    sd,
    min: sorted[0],
    max: sorted[n - 1],
    q1,
    q3,
    iqr: q1 !== null && q3 !== null ? q3 - q1 : null,
  };
}

// groups `rows` by a categorical column's value, returning the numeric
// values of `metricColumn` per group - rows missing either field are
// dropped from that group entirely (not coalesced to a fake "unknown"
// bucket, which would silently mix incomparable patients together).
export function groupNumericByCategory(rows, categoryColumn, metricColumn) {
  const groups = {};
  for (const row of rows) {
    const label = row[categoryColumn];
    const value = toNumber(row[metricColumn]);
    if (label === undefined || label === "" || value === null) continue;
    (groups[label] ??= []).push(value);
  }
  return groups;
}

// splits a numeric column into `nBins` equal-width bins spanning its
// observed range, then groups rows the same way groupNumericByCategory
// does, keyed by a human-readable "[lo, hi)" bin label (the last bin is
// closed on both ends, so the max value itself lands somewhere).
// binningColumn and metricColumn may be the same column.
export function groupNumericByBins(rows, binningColumn, metricColumn, nBins) {
  const binValues = numericValues(rows, binningColumn);
  if (binValues.length === 0) return {};
  const lo = Math.min(...binValues);
  const hi = Math.max(...binValues);
  const width = (hi - lo) / nBins || 1;

  const edges = Array.from({ length: nBins + 1 }, (_, i) => lo + i * width);
  const labels = Array.from({ length: nBins }, (_, i) => `${edges[i].toFixed(1)}–${edges[i + 1].toFixed(1)}`);

  const groups = {};
  for (const row of rows) {
    const binVal = toNumber(row[binningColumn]);
    const metricVal = toNumber(row[metricColumn]);
    if (binVal === null || metricVal === null) continue;
    let idx = Math.floor((binVal - lo) / width);
    if (idx >= nBins) idx = nBins - 1; // the max value itself
    if (idx < 0) idx = 0;
    (groups[labels[idx]] ??= []).push(metricVal);
  }
  return groups;
}

// equal-width histogram bins for a single numeric column - [{x0, x1,
// count}], left-closed/right-open except the final bin (closed on both
// ends, same reasoning as groupNumericByBins).
export function histogramBins(values, nBins) {
  if (values.length === 0) return [];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const width = (hi - lo) / nBins || 1;
  const bins = Array.from({ length: nBins }, (_, i) => ({ x0: lo + i * width, x1: lo + (i + 1) * width, count: 0 }));
  for (const v of values) {
    let idx = Math.floor((v - lo) / width);
    if (idx >= nBins) idx = nBins - 1;
    if (idx < 0) idx = 0;
    bins[idx].count += 1;
  }
  return bins;
}
