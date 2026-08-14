// centralizes session-related fetch calls so later slices (align/clip/run)
// extend this module instead of scattering fetch() through components.

export async function uploadSession(files) {
  const formData = new FormData();
  for (const f of files) formData.append("files", f);
  const response = await fetch("/api/sessions", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { sessionId: data.session_id, vertexCount: data.vertex_count, faceCount: data.face_count };
}

export function meshUrl(sessionId, stage = "original") {
  return `/api/sessions/${sessionId}/mesh/${stage}`;
}

// landmarks here is the fixed-order array the API expects ([sellion,
// left_tragus, right_tragus] as {x,y,z} objects), not the name-keyed dict
// components work with - callers convert via LANDMARK_NAMES.map(...).
export async function startAlign(sessionId, { target, landmarks }) {
  const response = await fetch(`/api/sessions/${sessionId}/align`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, landmarks }),
  });
  if (!response.ok) throw new Error(await response.text());
}

// polls /status until the job is done or errored - written generically
// since /clip and /run need the identical loop, not just /align.
export async function pollStatus(sessionId) {
  while (true) {
    const response = await fetch(`/api/sessions/${sessionId}/status`);
    const data = await response.json();
    if (data.status === "done" || data.status === "error") return data;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}
