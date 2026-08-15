// single source of truth for landmark identity - names, order, anatomical
// descriptions, and colors. the color values here have to match the
// --landmark-* custom properties in index.css by hand (Three.js materials
// need a JS hex number, CSS needs a hex string) - same duplication legacy
// had, same fix (a comment in each file pointing at the other).
export const LANDMARK_NAMES = ["sellion", "left_tragus", "right_tragus"];

// optional 4th point (cranium target only) - an alternate anchor (e.g.
// subnasale) that takes over the registration/clip/display frame while
// sellion stays mandatory and keeps driving the actual measurements. see
// pipeline.analyze_cranial for why these are two different knobs.
export const ALT_FRONTAL_NAME = "alt_frontal";

export const LANDMARK_COLORS = {
  sellion: 0x1a4922,
  left_tragus: 0x8b0002,
  right_tragus: 0x08457c,
  alt_frontal: 0x2a4d80,
};

export const LANDMARK_LABELS = {
  sellion: "sellion",
  left_tragus: "left landmark (e.g. LH tragus)",
  right_tragus: "right landmark (e.g. RH tragus)",
  alt_frontal: "secondary frontal landmark (optional, e.g. subnasale)",
};

export const LANDMARK_DESCRIPTIONS = {
  sellion: "bridge of the nose, between the eyes",
  left_tragus: "small cartilage flap in front of the left ear canal",
  right_tragus: "same, right ear",
  alt_frontal: "becomes the clipping plane for the displayed/saved mesh instead of sellion; measurements stay sellion-based",
};

export function activeLandmarkNames(useAltFrontal) {
  return useAltFrontal ? [...LANDMARK_NAMES, ALT_FRONTAL_NAME] : LANDMARK_NAMES;
}

export function nextUnpickedLandmark(landmarks, useAltFrontal) {
  return activeLandmarkNames(useAltFrontal).find((n) => !(n in landmarks));
}
