// plain-language "what is this and how is it derived" text for the hover
// (?) icons next to each measurement/graph in the Analysis workspace - see
// components/InfoTooltip.jsx. mirrors the wording of api/results_bundle.py's
// own METRIC_EXPLAINERS (the PDF report's equivalent) where the same metric
// exists there, plus entries for the rows/graphs only the live viewer shows.

export const MEASUREMENT_EXPLAINERS = {
  depthMm: "Head length (OFD), measured front to back at the head-circumference slice.",
  breadthMm: "Head width (BPD), measured side to side at the head-circumference slice.",
  cephalicIndex: "Ratio of width to length (BPD/OFD x 100) - describes the overall head shape.",
  circumferenceCm: "Head circumference, measured around the widest part (the HC slice, shown as the red ring).",
  meshVolumeCc: "Estimated volume enclosed by the mesh.",
  cranialAsymmetryIndex:
    "Average left-right difference across the head: one half is mirrored onto the other and the leftover " +
    "gap is measured at every point. Lower means more symmetric.",
  facialAsymmetryIndex:
    "Average left-right difference across the face: one half is mirrored onto the other and the leftover " +
    "gap is measured at every point. Lower means more symmetric.",
  frontalBossingAngle:
    "Angle between horizontal and the line from sellion (the nasal bridge) to the forehead at the " +
    "head-circumference height. A smaller angle means a more prominent/bossed forehead; a larger angle " +
    "means flatter or more receding.",
  frontalAngleDeg:
    "The angle at the forehead's central ridge point, measured between two points a fixed distance to its " +
    "left and right. A sharper (smaller) angle can suggest a more pointed/ridged forehead shape.",
  midlineCurvatureConcentration:
    "How much of the forehead's total outward curvature is concentrated right at the centerline (ridge " +
    "window) versus spread out evenly across the whole forehead. Higher means a sharper, more localized ridge.",
  ridgeProtrusion:
    "How far the central forehead ridge is located behind or in front of the ideal parabola (see the note above the " +
    "graphs) at that same point.",
  ridgeArea:
    "Net area between the forehead contour and the ideal parabola, across the central ridge window: " +
    "positive means the center sticks out on net, negative means it falls short on net (flatter/recessed " +
    "relative to what the sides predict). Near zero doesn't mean 'normal' - see the note above the graphs. " +
    "The number in parentheses is the same area normalized by forehead width, so it's comparable across " +
    "different-sized heads.",
  temporalHollowing:
    "How sunken in the temple is compared to the ideal parabola, summed across that side's temporal window - " +
    "(an area).",
  maxTemporalDepth: "The single deepest point within that side's temporal window, compared to the ideal parabola.",
  parabolicDeviationIndex:
    "An overall score (root-mean-square) for how much the whole forehead contour differs from the ideal " +
    "parabola, combining every point along it into one number.",
};

export const GRAPH_EXPLAINERS = {
  gradient:
    "The tangent angle of the forehead contour at each point along it (solid line), against what a perfectly " +
    "parabolic forehead's angle would be at that same point (dashed line). Where the solid line pulls away " +
    "from the dashed one, the contour is steeper or flatter there than the ideal shape. Shaded = the ridge/" +
    "temple windows the table above is computed from.",
  curvature:
    "How sharply the contour bends at each point (solid line, positive = bulging outward), against the ideal " +
    "parabola's own curvature there (dashed line). A spike inside the red (ridge) shading, above the dashed " +
    "line, is a localized ridge; a rise inside the teal (temple) shading is a hollow flattening back out. " +
    "The plain, unshaded stretches at the very left/right ends aren't part of any measured window - a sharp " +
    "spike only out there is almost always the mesh's own clip-boundary edge, not a real anatomical feature.",
  deviation:
    "The straight-line gap between the contour and the ideal parabola at each point, in mm (positive = " +
    "contour sticks out further than the parabola). The dashed line at zero is what a perfectly parabolic " +
    "forehead would show - the parabolic deviation index is this graph's overall spread.",
};

// the "ideal parabola" every measurement/graph above compares against - one
// persistent note near the top of the section rather than only a hover
// tooltip, since it's the one piece of context everything else depends on.
export const IDEAL_PARABOLA_EXPLAINER =
  "\"Ideal (parabola)\": z = a·x² + c, fit only to the sides of this same forehead (not the center, not a " +
  "healthy-head template). It's self-referential: if this forehead's own sides are already affected too, " +
  "the parabola inherits that, and deviation from it reads as \"more localized to the center than the rest " +
  "of this forehead\" rather than \"abnormal\".";
