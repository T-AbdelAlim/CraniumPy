// resamples and lerps the measurements/metopic/frontal-bossing overlay
// geometry between two timepoints - see three/resamplePolyline.js's own
// comment for why resampling has to happen first (craniumpy_core's own
// slice/contour/profile point arrays are variable-length per mesh, no
// shared per-index meaning across two different meshes). used by
// LongitudinalMorphViewer.jsx: resampleStageOverlays runs ONCE per stage,
// when the morph sequence loads; lerpStageOverlays runs every frame, on
// data that's already fixed-shape and cheap to interpolate.
import { resamplePolylineByArcLength, resampleByU, lerpPoints, lerpPoint, lerpScalar } from "../../../three/resamplePolyline.js";

const HC_POLYGON_SAMPLES = 48;
const METOPIC_CONTOUR_SAMPLES = 48;
const FRONTAL_BOSSING_PROFILE_SAMPLES = 32;

// measurementsResponse is one timepoint's own CohortMeanShapeMeasurementsResponse
// (api/longitudinal.js's measureMesh result) - {craniometrics, asymmetry,
// metopic, frontal_bossing}. asymmetry isn't touched here - that's the
// existing per-vertex heatmap path (showHeatmapSequence), unrelated to
// this line/marker overlay geometry.
export function resampleStageOverlays(measurementsResponse) {
  const m = measurementsResponse || {};

  const craniometrics = m.craniometrics
    ? {
        hcPolygon: m.craniometrics.hc_slice_polygon && m.craniometrics.hc_slice_polygon.length > 2
          ? resamplePolylineByArcLength(m.craniometrics.hc_slice_polygon, HC_POLYGON_SAMPLES, true)
          : null,
        frontOpt: m.craniometrics.front_opt,
        occOpt: m.craniometrics.occ_opt,
        lhOpt: m.craniometrics.lh_opt,
        rhOpt: m.craniometrics.rh_opt,
      }
    : null;

  const metopic = m.metopic
    ? {
        contour: resampleByU(m.metopic.contour, m.metopic.normalized_arc_length, METOPIC_CONTOUR_SAMPLES),
        // the resampled contour is evenly u-spaced BY CONSTRUCTION (that's
        // what resampleByU's own target u's are) - no need to resample the
        // arc-length array too, it's just 0..1 in N even steps.
        normalizedArcLength: Array.from({ length: METOPIC_CONTOUR_SAMPLES }, (_, i) => i / Math.max(METOPIC_CONTOUR_SAMPLES - 1, 1)),
        sliceHeight: m.metopic.slice_height,
        parabolaA: m.metopic.parabola_a,
        parabolaC: m.metopic.parabola_c,
        centralWindow: m.metopic.central_window,
        leftTemporalWindow: m.metopic.left_temporal_window,
        rightTemporalWindow: m.metopic.right_temporal_window,
        frontalAnglePoints: m.metopic.frontal_angle_points,
      }
    : null;

  const frontalBossing = m.frontal_bossing
    ? {
        sellion: m.frontal_bossing.sellion,
        frontalPoint: m.frontal_bossing.frontal_point,
        horizontal: m.frontal_bossing.horizontal,
        profile: m.frontal_bossing.profile && m.frontal_bossing.profile.length > 1
          ? resamplePolylineByArcLength(m.frontal_bossing.profile, FRONTAL_BOSSING_PROFILE_SAMPLES, false)
          : null,
      }
    : null;

  return { craniometrics, metopic, frontalBossing };
}

function lerpWindow(a, b, t) {
  return [lerpScalar(a[0], b[0], t), lerpScalar(a[1], b[1], t)];
}

// lerps two ALREADY-resampled stage descriptors (resampleStageOverlays's
// own output) at local leg parameter t, and translates back into the plain
// {x,y,z}-point shapes three/measurementsLayer.js's addMeasurementsOverlay/
// three/metopicOverlay.js's addMetopicOverlay/three/frontalBossingOverlay.js's
// addFrontalBossingOverlay each expect - the per-frame cost, deliberately
// just arithmetic over fixed-shape arrays/points/scalars already computed
// once, nothing that touches the network or recomputes real geometry.
export function lerpStageOverlays(a, b, t) {
  const craniometrics =
    a?.craniometrics && b?.craniometrics && a.craniometrics.hcPolygon && b.craniometrics.hcPolygon
      ? {
          hcPolygon: lerpPoints(a.craniometrics.hcPolygon, b.craniometrics.hcPolygon, t),
          frontOpt: lerpPoint(a.craniometrics.frontOpt, b.craniometrics.frontOpt, t),
          occOpt: lerpPoint(a.craniometrics.occOpt, b.craniometrics.occOpt, t),
          lhOpt: lerpPoint(a.craniometrics.lhOpt, b.craniometrics.lhOpt, t),
          rhOpt: lerpPoint(a.craniometrics.rhOpt, b.craniometrics.rhOpt, t),
        }
      : null;

  const metopic =
    a?.metopic && b?.metopic
      ? {
          contour: lerpPoints(a.metopic.contour, b.metopic.contour, t),
          normalized_arc_length: a.metopic.normalizedArcLength,
          slice_height: lerpScalar(a.metopic.sliceHeight, b.metopic.sliceHeight, t),
          parabola_a: lerpScalar(a.metopic.parabolaA, b.metopic.parabolaA, t),
          parabola_c: lerpScalar(a.metopic.parabolaC, b.metopic.parabolaC, t),
          central_window: lerpWindow(a.metopic.centralWindow, b.metopic.centralWindow, t),
          left_temporal_window: lerpWindow(a.metopic.leftTemporalWindow, b.metopic.leftTemporalWindow, t),
          right_temporal_window: lerpWindow(a.metopic.rightTemporalWindow, b.metopic.rightTemporalWindow, t),
          frontal_angle_points: [
            lerpPoint(a.metopic.frontalAnglePoints[0], b.metopic.frontalAnglePoints[0], t),
            lerpPoint(a.metopic.frontalAnglePoints[1], b.metopic.frontalAnglePoints[1], t),
            lerpPoint(a.metopic.frontalAnglePoints[2], b.metopic.frontalAnglePoints[2], t),
          ],
        }
      : null;

  const frontalBossing =
    a?.frontalBossing && b?.frontalBossing
      ? {
          sellion: lerpPoint(a.frontalBossing.sellion, b.frontalBossing.sellion, t),
          frontal_point: lerpPoint(a.frontalBossing.frontalPoint, b.frontalBossing.frontalPoint, t),
          horizontal: a.frontalBossing.horizontal && b.frontalBossing.horizontal
            ? lerpPoint(a.frontalBossing.horizontal, b.frontalBossing.horizontal, t)
            : a.frontalBossing.horizontal || b.frontalBossing.horizontal,
          profile: a.frontalBossing.profile && b.frontalBossing.profile
            ? lerpPoints(a.frontalBossing.profile, b.frontalBossing.profile, t)
            : null,
        }
      : null;

  return { craniometrics, metopic, frontalBossing };
}
