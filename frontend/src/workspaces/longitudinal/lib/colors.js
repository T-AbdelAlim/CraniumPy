// per-slot palette for the Longitudinal workspace - each timepoint gets its
// own hue family so its 3D overlays (HC ring/BPD/OFD, metopic contour,
// frontal bossing profile) and its legend swatch all read as the same
// "thing" across the comparison, distinct from every other slot's. slot 0
// (baseline) is warm, slot 1 (follow-up) is cool - matching the red/blue
// baseline-vs-follow-up convention already used elsewhere in this app (see
// api/results_bundle.py's longitudinal_comparison_report_pdf) - additional
// slots (N>2) cycle through the rest of a fixed, readable 6-color set.
const PALETTE = [
  { swatch: "#2563eb", hc: 0xd1453d, bpd: 0x2563eb, ofd: 0x16a34a }, // baseline - matches existing default overlay colors
  { swatch: "#d1453d", hc: 0xea580c, bpd: 0xd1453d, ofd: 0xf59e0b }, // follow-up - warm family, distinct from baseline's
  { swatch: "#16a34a", hc: 0x0891b2, bpd: 0x16a34a, ofd: 0x0d9488 },
  { swatch: "#7c3aed", hc: 0xa855f7, bpd: 0x7c3aed, ofd: 0xc026d3 },
  { swatch: "#0891b2", hc: 0x2563eb, bpd: 0x0891b2, ofd: 0x0e7490 },
  { swatch: "#ea580c", hc: 0xf59e0b, bpd: 0xea580c, ofd: 0xd97706 },
];

export function slotColor(index) {
  return PALETTE[index % PALETTE.length];
}

// the {hc, bpd, ofd} shape addMeasurementsOverlay's colors param expects -
// same values as slotColor, just the subset that overlay needs.
export function measurementsColors(index) {
  const { hc, bpd, ofd } = slotColor(index);
  return { hc, bpd, ofd };
}

// metopicOverlay/frontalBossingOverlay each key their own overlay elements
// slightly differently (contour/parabola/central/temporal/frontalAngle/
// midline vs. profile/angle/reference) - both derived from the same two
// "primary" (bpd-ish) and "secondary" (ofd-ish) hues per slot so a given
// timepoint reads as one consistent color story across every overlay type,
// rather than needing a separate hand-picked palette per overlay.
export function metopicColors(index) {
  const { hc, bpd, ofd } = slotColor(index);
  return { contour: 0x3a3a3a, parabola: bpd, central: hc, temporal: ofd, frontalAngle: bpd, midline: 0x999999 };
}

export function frontalBossingColors(index) {
  const { hc, bpd } = slotColor(index);
  return { profile: 0x999999, angle: bpd, reference: hc };
}

// 5 maximally-distinct colors for the Correspondence tab's "check
// correspondence" markers - deliberately unrelated to the per-slot PALETTE
// above (these color individual sample POINTS, not timepoints), picked so
// no two are easily confused even on a small sphere marker: point i gets
// the same color on every mesh it's shown on, so a mismatched
// correspondence (the same color landing somewhere totally different)
// jumps out immediately.
export const CORRESPONDENCE_MARKER_COLORS = [0xe63946, 0x1d4ed8, 0x16a34a, 0xf59e0b, 0x9333ea];
