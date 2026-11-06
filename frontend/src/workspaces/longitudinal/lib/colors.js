// per-slot palette for the Longitudinal workspace - each timepoint gets its
// own colour family so its 3D overlays (HC ring/BPD/OFD, metopic contour,
// frontal bossing profile) and its legend swatch all read as the same
// "thing" across the comparison, distinct from every other slot's. all
// drawn from the Erasmus MC blues (navy, light blue, accent) and their
// tints/shades; slots past six repeat.
const PALETTE = [
  // the baseline keeps the single-patient view's own measurement colours, so
  // the two read the same; later timepoints use one shade family each
  { swatch: "#86d2ee", hc: 0xd1453d, bpd: 0x2563eb, ofd: 0x16a34a },
  { swatch: "#1f8fc7", hc: 0x1f8fc7, bpd: 0x5fb3d9, ofd: 0x15688f },
  { swatch: "#e1f4fc", hc: 0xe1f4fc, bpd: 0xbfe6f6, ofd: 0x9fd2ea },
  { swatch: "#5b75d6", hc: 0x5b75d6, bpd: 0x8fa0e0, ofd: 0x3d58c4 },
  { swatch: "#b8c2e8", hc: 0xb8c2e8, bpd: 0xd4dbf2, ofd: 0x9aa7d6 },
  { swatch: "#4fb6dd", hc: 0x4fb6dd, bpd: 0x86d2ee, ofd: 0x2a7fb0 },
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
export const CORRESPONDENCE_MARKER_COLORS = [0x86d2ee, 0x1f8fc7, 0xe1f4fc, 0x5b75d6, 0xb8c2e8];
