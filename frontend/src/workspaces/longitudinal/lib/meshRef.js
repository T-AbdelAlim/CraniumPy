import { meshUrl, nicpResultMeshUrl } from "../../../api/sessions.js";

// a ready slot's own mesh, as the {sessionId, stage} ref shape
// api/longitudinal.js's calls (measureMesh/computeLongitudinalDiff) expect
// - shared by CompareTab.jsx and the 3D Morphing tab, both of which just
// read whatever stage TimepointSlot.jsx already loaded (every slot here is
// already NICP-fit before it's ever ready - see that file's own comment -
// so "clipped" never actually applies in practice, kept only as a safe
// fallback for a slot shape from before that was true). "nicp_result" here
// (underscore) matches api/schemas.py's LongitudinalMeshRef.stage Literal -
// the JSON body value those two calls send, NOT a URL path segment (see
// stageMeshUrl below for the REST endpoint's own, differently-punctuated
// naming).
export function slotStageRef(slot) {
  return { sessionId: slot.sessionId, stage: slot.stage === "original" ? "original" : slot.stage || "nicp_result" };
}

// a ready slot's own mesh, as a GLB url - for displayMesh/loadSequence,
// NOT the JSON-body {sessionId, stage} shape slotStageRef above builds.
// api/sessions.js's own mesh endpoints don't use one uniform stage-name
// convention: /mesh/{stage} handles "original"/"clipped"/"result" directly,
// but the NICP-fitted mesh lives at its own dedicated /mesh/nicp-result
// route (dash, not underscore - see api/routers/mesh.py's own comment on
// why: {stage} would otherwise need "nicp-preview"/"nicp-result" added as
// literal cases, and FastAPI resolves a more specific route ahead of a
// wildcard one anyway). building `meshUrl(sessionId, "nicp_result")`
// directly 400s - there's no such {stage} case - so this translates the
// slot's own stage value into whichever URL actually serves it.
export function stageMeshUrl(sessionId, stage) {
  if (stage === "nicp_result") return nicpResultMeshUrl(sessionId);
  return meshUrl(sessionId, stage || "original");
}

// a slot's own label, falling back to the positional "Timepoint N" every
// other display in this workspace already uses (0-indexed, matching
// TimepointSlot.jsx's own placeholder).
export function slotLabel(slot, index) {
  return slot.label || `Timepoint ${index}`;
}
