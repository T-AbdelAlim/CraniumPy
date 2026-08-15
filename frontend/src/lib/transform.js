// forward: aligned = raw @ R.T + t (matches RigidTransform.apply in
// craniumpy_core.registration.rigid). rotation is 3x3 row-major,
// translation is [x, y, z] - see RegisteredTransformResponse.
export function applyTransform(point, transform) {
  const { rotation: R, translation: t } = transform;
  const p = [point.x, point.y, point.z];
  const out = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    let sum = t[i];
    for (let j = 0; j < 3; j++) sum += p[j] * R[i][j];
    out[i] = sum;
  }
  return { x: out[0], y: out[1], z: out[2] };
}

// inverse of the above - R is orthogonal (a pure rotation), so R^-1 = R.T
// and raw = (aligned - t) @ R.
export function applyInverseTransform(point, transform) {
  const { rotation: R, translation: t } = transform;
  const d = [point.x - t[0], point.y - t[1], point.z - t[2]];
  const out = [0, 0, 0];
  for (let j = 0; j < 3; j++) {
    let sum = 0;
    for (let i = 0; i < 3; i++) sum += d[i] * R[i][j];
    out[j] = sum;
  }
  return { x: out[0], y: out[1], z: out[2] };
}
