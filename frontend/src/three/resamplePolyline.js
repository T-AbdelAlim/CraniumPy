// resamples a polyline (an array of {x,y,z} or {x,z} points, in order) to
// exactly N evenly-arc-length-spaced points - used by the 3D Morphing tab
// to make two timepoints' own overlay geometry lerp-able frame by frame.
// craniumpy_core's own measurement geometry (hc_slice_polygon, the metopic
// contour, the frontal-bossing profile) is a variable-length point array
// per mesh - however many points a slicing plane happened to intersect on
// THAT mesh's own triangulation - with no shared per-index meaning across
// two different meshes, so lerping point[i] of timepoint A against point[i]
// of timepoint B directly would misalign (or, if the two arrays differ in
// length, crash) whenever the two meshes' own raw point counts don't
// happen to match. resampling both onto the same fixed N first (this
// function) makes point i mean "the same fractional distance along the
// curve" on both, which is what actually needs to line up for a lerp to
// look like smooth motion rather than a jump.
//
// closed=true treats the polyline as a loop (the HC ring) - the segment
// from the last point back to the first counts toward total arc length,
// and resampling wraps around instead of stopping at the last point.
export function resamplePolylineByArcLength(points, n, closed = false) {
  if (points.length === 0) return [];
  if (points.length === 1) return Array.from({ length: n }, () => points[0]);

  const pts = closed ? [...points, points[0]] : points;
  const segLengths = [];
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const dx = pts[i + 1].x - pts[i].x;
    const dy = (pts[i + 1].y ?? 0) - (pts[i].y ?? 0);
    const dz = (pts[i + 1].z ?? 0) - (pts[i].z ?? 0);
    const len = Math.sqrt(dx * dx + dy * dy + dz * dz);
    segLengths.push(len);
    total += len;
  }
  if (total === 0) return Array.from({ length: n }, () => points[0]);

  const denom = closed ? n : Math.max(n - 1, 1);
  const out = [];
  for (let i = 0; i < n; i++) {
    const target = (i / denom) * total;
    let acc = 0;
    let segIndex = pts.length - 2;
    for (let s = 0; s < segLengths.length; s++) {
      if (acc + segLengths[s] >= target || s === segLengths.length - 1) {
        segIndex = s;
        break;
      }
      acc += segLengths[s];
    }
    const segLen = segLengths[segIndex] || 1e-9;
    const localT = Math.max(0, Math.min(1, (target - acc) / segLen));
    const a = pts[segIndex];
    const b = pts[segIndex + 1];
    out.push({
      x: a.x + (b.x - a.x) * localT,
      y: (a.y ?? 0) + ((b.y ?? 0) - (a.y ?? 0)) * localT,
      z: (a.z ?? 0) + ((b.z ?? 0) - (a.z ?? 0)) * localT,
    });
  }
  return out;
}

// resamples a u-parametrized point array (each point already carries its
// own fractional position along the curve, 0..1 - the metopic contour's
// own normalized_arc_length) onto N evenly-spaced u values via linear
// interpolation between whichever two original points bracket each target
// u - cheaper than resamplePolylineByArcLength since the parametrization is
// already given, no arc-length computation needed.
export function resampleByU(points, us, n) {
  if (points.length === 0) return [];
  if (points.length === 1) return Array.from({ length: n }, () => points[0]);

  const out = [];
  for (let i = 0; i < n; i++) {
    const targetU = i / Math.max(n - 1, 1);
    let lo = 0;
    while (lo < us.length - 2 && us[lo + 1] < targetU) lo++;
    const u0 = us[lo];
    const u1 = us[lo + 1] ?? u0;
    const span = u1 - u0 || 1e-9;
    const localT = Math.max(0, Math.min(1, (targetU - u0) / span));
    const a = points[lo];
    const b = points[lo + 1] ?? points[lo];
    out.push({
      x: a.x + (b.x - a.x) * localT,
      y: (a.y ?? 0) + ((b.y ?? 0) - (a.y ?? 0)) * localT,
      z: (a.z ?? 0) + ((b.z ?? 0) - (a.z ?? 0)) * localT,
    });
  }
  return out;
}

// per-point linear interpolation between two ALREADY same-length point
// arrays - the shared last-mile step every resampled overlay field uses
// once per-frame, in LongitudinalMorphViewer.jsx.
export function lerpPoints(a, b, t) {
  return a.map((p, i) => ({
    x: p.x + (b[i].x - p.x) * t,
    y: (p.y ?? 0) + ((b[i].y ?? 0) - (p.y ?? 0)) * t,
    z: (p.z ?? 0) + ((b[i].z ?? 0) - (p.z ?? 0)) * t,
  }));
}

export function lerpPoint(a, b, t) {
  return {
    x: a.x + (b.x - a.x) * t,
    y: (a.y ?? 0) + ((b.y ?? 0) - (a.y ?? 0)) * t,
    z: (a.z ?? 0) + ((b.z ?? 0) - (a.z ?? 0)) * t,
  };
}

export function lerpScalar(a, b, t) {
  return a + (b - a) * t;
}
