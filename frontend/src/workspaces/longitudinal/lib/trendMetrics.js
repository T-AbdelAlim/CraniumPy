// the metric catalog for the Trends tab's "measurements over time" chart -
// every scalar field group_measurements_response (api/routers/
// _group_measurements.py) can carry, grouped the same way AnalysisPanel.jsx
// groups its own tables (cranial measurements / frontal bossing+asymmetry /
// metopic forehead shape). deliberately excludes the non-measurement fields
// of those same result shapes - curve-fit coefficients (parabola_a/c),
// arc-length positions (midline_u, *_position), and the three window-bound
// tuples - none of those are a value you'd plot over time, they're internal
// parameters the real measurements above are computed from.
export const TREND_METRIC_GROUPS = [
  {
    title: "Cranial measurements",
    metrics: [
      { id: "depth_mm", group: "craniometrics", key: "depth_mm", label: "OFD (head length)", unit: "mm", explainer: "depthMm" },
      { id: "breadth_mm", group: "craniometrics", key: "breadth_mm", label: "BPD (head width)", unit: "mm", explainer: "breadthMm" },
      { id: "cephalic_index", group: "craniometrics", key: "cephalic_index", label: "Cephalic index", unit: "", explainer: "cephalicIndex" },
      { id: "circumference_cm", group: "craniometrics", key: "circumference_cm", label: "Head circumference (HC)", unit: "cm", explainer: "circumferenceCm" },
      { id: "mesh_volume_cc", group: "craniometrics", key: "mesh_volume_cc", label: "Volume", unit: "cc", explainer: "meshVolumeCc" },
    ],
  },
  {
    title: "Frontal bossing & asymmetry",
    metrics: [
      { id: "frontal_bossing_angle_deg", group: "frontal_bossing", key: "angle_deg", label: "Frontal bossing angle", unit: "deg", explainer: "frontalBossingAngle" },
      { id: "mean_asymmetry_index", group: "asymmetry", key: "mean_asymmetry_index", label: "Asymmetry index", unit: "mm", explainer: null },
    ],
  },
  {
    title: "Forehead shape (metopic)",
    metrics: [
      { id: "metopic_frontal_angle_deg", group: "metopic", key: "frontal_angle_deg", label: "Metopic frontal angle", unit: "deg", explainer: "frontalAngleDeg" },
      { id: "forehead_width_mm", group: "metopic", key: "forehead_width_mm", label: "Forehead width", unit: "mm", explainer: null },
      { id: "midline_curvature_concentration", group: "metopic", key: "midline_curvature_concentration", label: "Midline curvature concentration", unit: "", explainer: "midlineCurvatureConcentration" },
      { id: "midline_max_curvature", group: "metopic", key: "midline_max_curvature", label: "Midline max curvature", unit: "1/mm", explainer: null },
      { id: "ridge_protrusion_mm", group: "metopic", key: "ridge_protrusion_mm", label: "Ridge protrusion", unit: "mm", explainer: "ridgeProtrusion" },
      { id: "ridge_area_mm2", group: "metopic", key: "ridge_area_mm2", label: "Ridge area", unit: "mm2", explainer: "ridgeArea" },
      { id: "ridge_area_normalized", group: "metopic", key: "ridge_area_normalized", label: "Ridge area (normalized)", unit: "", explainer: "ridgeArea" },
      { id: "left_temporal_hollowing", group: "metopic", key: "left_temporal_hollowing", label: "Temporal hollowing (left)", unit: "", explainer: "temporalHollowing" },
      { id: "right_temporal_hollowing", group: "metopic", key: "right_temporal_hollowing", label: "Temporal hollowing (right)", unit: "", explainer: "temporalHollowing" },
      { id: "mean_temporal_hollowing", group: "metopic", key: "mean_temporal_hollowing", label: "Temporal hollowing (mean)", unit: "", explainer: "temporalHollowing" },
      { id: "left_max_temporal_depth_mm", group: "metopic", key: "left_max_temporal_depth_mm", label: "Max temporal depth (left)", unit: "mm", explainer: "maxTemporalDepth" },
      { id: "right_max_temporal_depth_mm", group: "metopic", key: "right_max_temporal_depth_mm", label: "Max temporal depth (right)", unit: "mm", explainer: "maxTemporalDepth" },
      { id: "parabolic_deviation_index", group: "metopic", key: "parabolic_deviation_index", label: "Parabolic deviation index", unit: "mm", explainer: "parabolicDeviationIndex" },
    ],
  },
];

export const ALL_TREND_METRICS = TREND_METRIC_GROUPS.flatMap((g) => g.metrics);

// per-metric colors, keyed by position across the flattened catalog above -
// the first 3 reuse this app's own --hc/--bpd/--ofd hex values (see
// index.css) so HC/BPD/OFD read exactly like they do everywhere else in the
// app; the rest are a plain qualitative palette, cycled if more metrics are
// selected than colors (20 metrics total above, all distinct here, so this
// only ever cycles for a hypothetical future addition to the catalog).
const TREND_METRIC_COLOR_PALETTE = [
  "#16a34a", // --ofd - depth_mm
  "#2563eb", // --bpd - breadth_mm
  "#7c3aed", // cephalic_index
  "#d1453d", // --hc - circumference_cm
  "#ea580c", // mesh_volume_cc
  "#0891b2", // frontal_bossing angle
  "#c026d3", // asymmetry index
  "#0d9488", // metopic frontal angle
  "#f59e0b", // forehead width
  "#4ade80", // midline curvature concentration
  "#a855f7", // midline max curvature
  "#dc2626", // ridge protrusion
  "#0e7490", // ridge area
  "#65a30d", // ridge area normalized
  "#e11d48", // left temporal hollowing
  "#1d4ed8", // right temporal hollowing
  "#9333ea", // mean temporal hollowing
  "#b45309", // left max temporal depth
  "#0369a1", // right max temporal depth
  "#be185d", // parabolic deviation index
];

export function trendMetricColor(metricId) {
  const index = ALL_TREND_METRICS.findIndex((m) => m.id === metricId);
  return TREND_METRIC_COLOR_PALETTE[index % TREND_METRIC_COLOR_PALETTE.length];
}

// a sensible starting selection: the 4 headline cranial measurements (the
// reference mockup this feature was built from shows exactly these) when
// any slot has cranial measurements at all, otherwise the closest facial
// equivalent (the metopic frontal angle and its overall deviation score,
// plus asymmetry - both targets share that one).
export function defaultTrendMetricIds(slots) {
  const hasCraniometrics = slots.some((s) => s.ready && s.measurements?.craniometrics);
  if (hasCraniometrics) return ["depth_mm", "breadth_mm", "cephalic_index", "circumference_cm"];
  return ["metopic_frontal_angle_deg", "parabolic_deviation_index", "mean_asymmetry_index"];
}
