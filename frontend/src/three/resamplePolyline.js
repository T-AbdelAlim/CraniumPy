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

// gives a polyline a canonical walk direction/start so two timepoints' own
// copies of "the same" curve line up index-for-index before resampling.
// craniumpy_core's sagittal profile is mesh.section()'s own connectivity
// walk - which end it starts at, which way it winds, and (for a closed
// loop) where on the loop it starts are all arbitrary per mesh. resampling
// by arc length alone preserves that arbitrariness, so lerping point i of
// one timepoint against point i of the next could pair the forehead with
// the occiput (or the top with the bottom) and sweep the whole line across
// the head mid-morph.
//
// anchors on `anchor` (the sellion - a real landmark, present and near the
// curve on every timepoint): an open curve is flipped so the end nearer the
// anchor comes first; a closed curve (endpoints within 2% of its length of
// each other) is rotated to start at the point nearest the anchor and
// wound in the (z, y) plane with a fixed sign. returns { points, closed }.
export function canonicalizeSagittalProfile(points, anchor) {
  if (!points || points.length < 3 || !anchor) return { points, closed: false };
  const dist = (p, q) => Math.hypot(p.x - q.x, (p.y ?? 0) - (q.y ?? 0), (p.z ?? 0) - (q.z ?? 0));

  let total = 0;
  for (let i = 0; i < points.length - 1; i++) total += dist(points[i], points[i + 1]);
  const closed = total > 0 && dist(points[0], points[points.length - 1]) < 0.02 * total;

  if (!closed) {
    const flip = dist(points[points.length - 1], anchor) < dist(points[0], anchor);
    return { points: flip ? [...points].reverse() : points, closed: false };
  }

  // drop the duplicated closing point if there is one
  let ring = dist(points[0], points[points.length - 1]) < 1e-6 ? points.slice(0, -1) : points.slice();
  let area = 0; // shoelace in (z, y)
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i];
    const q = ring[(i + 1) % ring.length];
    area += (p.z ?? 0) * (q.y ?? 0) - (q.z ?? 0) * (p.y ?? 0);
  }
  if (area < 0) ring = ring.reverse();
  let start = 0;
  let best = Infinity;
  ring.forEach((p, i) => {
    const d = dist(p, anchor);
    if (d < best) { best = d; start = i; }
  });
  return { points: [...ring.slice(start), ...ring.slice(0, start)], closed: true };
}

// same idea as canonicalizeSagittalProfile, for the horizontal head-
// circumference ring: the slice polygon's start vertex and winding direction
// are arbitrary per mesh, so two timepoints' rings can be rotated or
// mirrored relative to each other index-for-index, and the lerp spins the
// ring around the head instead of growing it. rotates the ring to start at
// the point nearest `anchor` (the frontmost HC point, front_opt - a landmark
// present on every timepoint) and winds it with a fixed sign in the (x, z)
// plane. the ring is implicitly closed (no repeated end point).
export function canonicalizeClosedRing(points, anchor) {
  if (!points || points.length < 3 || !anchor) return points;
  let ring = points.slice();
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (Math.hypot(first.x - last.x, (first.z ?? 0) - (last.z ?? 0)) < 1e-6) ring.pop();

  let area = 0; // shoelace in (x, z)
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i];
    const q = ring[(i + 1) % ring.length];
    area += p.x * (q.z ?? 0) - q.x * (p.z ?? 0);
  }
  if (area < 0) ring.reverse();

  let start = 0;
  let best = Infinity;
  ring.forEach((p, i) => {
    const d = Math.hypot(p.x - anchor.x, (p.y ?? 0) - (anchor.y ?? 0), (p.z ?? 0) - (anchor.z ?? 0));
    if (d < best) { best = d; start = i; }
  });
  return [...ring.slice(start), ...ring.slice(0, start)];
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
