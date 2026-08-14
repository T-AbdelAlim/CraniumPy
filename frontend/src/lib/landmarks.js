// single source of truth for landmark identity - names, order, anatomical
// descriptions, and colors. the color values here have to match the
// --landmark-* custom properties in index.css by hand (Three.js materials
// need a JS hex number, CSS needs a hex string) - same duplication legacy
// had, same fix (a comment in each file pointing at the other).
export const LANDMARK_NAMES = ["sellion", "left_tragus", "right_tragus"];

export const LANDMARK_COLORS = {
  sellion: 0x1a4922,
  left_tragus: 0x8b0002,
  right_tragus: 0xd4af37,
};

export const LANDMARK_LABELS = {
  sellion: "sellion",
  left_tragus: "left landmark (e.g. LH tragus)",
  right_tragus: "right landmark (e.g. RH tragus)",
};

export const LANDMARK_DESCRIPTIONS = {
  sellion: "bridge of the nose, between the eyes",
  left_tragus: "small cartilage flap in front of the left ear canal",
  right_tragus: "same, right ear",
};

export function nextUnpickedLandmark(landmarks) {
  return LANDMARK_NAMES.find((n) => !(n in landmarks));
}
