import * as THREE from "three";

// draws what "preprocess mesh" is about to cut away, on the registered mesh,
// so the choice of region is made looking at the actual geometry rather than
// after the fact. every element the clip really uses is drawn (both planes
// and the trim spheres) - the numbers come from the backend
// (craniumpy_core.clipping.clip_preview_geometry via GET
// /api/sessions/{id}/clip-preview), never re-typed here, so the picture
// can't drift away from the operation it claims to describe.
//
// both regions' planes are drawn at once: the selected one in red, the
// other in faint grey, and each carries a small disc at its boundary plane
// that selects that region when clicked. that's the whole point of showing
// them together - you pick the region by pointing at it. only the SELECTED
// region's trim sphere is drawn, though: two nested spheres a couple of
// hundred millimetres across are just noise, and the sphere is the one
// piece of the preview the user can actually move and resize (see
// setClipPreviewSphere), which only makes sense for the active region.

const SELECTED_COLOR = 0xd1453d; // --hc, the same red the app uses elsewhere
const UNSELECTED_COLOR = 0x8a949f;

// the boundary plane is the region's actual edge, so it gets real presence;
// the trim sphere only strips stray scan junk and stays faint. all of it
// must stay see-through enough to read the mesh underneath.
const OPACITY = {
  boundaryFillSelected: 0.22,
  boundaryFillUnselected: 0.08,
  sphereFill: 0.03,
  sphereWire: 0.16,
};

function planeQuad(normal, origin, size, color, fillOpacity) {
  const group = new THREE.Group();
  const geo = new THREE.PlaneGeometry(size, size);

  group.add(
    new THREE.Mesh(
      geo,
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: fillOpacity,
        side: THREE.DoubleSide,
        // without this the translucent quad writes depth and punches a
        // hole through the head behind it
        depthWrite: false,
      }),
    ),
  );

  // the rim is what actually makes a near-transparent plane legible - the
  // fill alone reads as a faint haze, especially edge-on.
  const rim = new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 }),
  );
  group.add(rim);

  // PlaneGeometry is born in the XY plane facing +Z; point it along the
  // clip normal and drop it on the clip origin.
  const n = new THREE.Vector3(...normal).normalize();
  group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
  group.position.set(...origin);
  return { group, normal: n };
}

function sphereShell(center, radius, color) {
  const group = new THREE.Group();
  // the radius is baked into the geometry, so resizing later is a scale -
  // hence remembering what 1.0 means.
  group.userData.baseRadius = radius;
  group.userData.baseCenter = [...center];
  // coarse on purpose: enough lines to read as a sphere, few enough that
  // it stays a boundary rather than becoming a second object in the way.
  const geo = new THREE.SphereGeometry(radius, 16, 12);

  group.add(
    new THREE.Mesh(
      geo,
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: OPACITY.sphereFill,
        side: THREE.BackSide, // inside faces only, so it never veils the head
        depthWrite: false,
      }),
    ),
  );
  // only the boundary is meant to read - the cranial trim sphere is 175mm
  // and would otherwise swallow the whole viewport.
  group.add(
    new THREE.Mesh(
      geo,
      new THREE.MeshBasicMaterial({
        color,
        wireframe: true,
        transparent: true,
        opacity: OPACITY.sphereWire,
        depthWrite: false,
      }),
    ),
  );
  group.position.set(...center);
  return group;
}

// the clickable "circled window" in a boundary plane, plus a small bead at
// its centre. the ring alone would vanish whenever its plane is seen
// edge-on - which for the near-horizontal cranial plane is most of the
// time - so the bead is what guarantees there is always something to aim
// at, while the ring says which plane it belongs to. both are tagged via
// userData so Viewer's raycast can tell which region was hit without
// needing to know anything else about this overlay's structure.
function selectorDisc(target, radius, color, selected) {
  const disc = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 32),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: selected ? 0.55 : 0.3,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const ring = new THREE.LineLoop(
    new THREE.CircleGeometry(radius, 32),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 }),
  );
  // CircleGeometry's first vertex is its centre point - fine as a filled
  // disc, but as a LineLoop it would drag a spoke out to the middle.
  ring.geometry = new THREE.BufferGeometry().setFromPoints(
    Array.from({ length: 33 }, (_, i) => {
      const a = (i / 32) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0);
    }),
  );
  disc.add(ring);
  disc.userData.clipSelectTarget = target;

  // the one part of the overlay that is meant to be caught rather than
  // seen through - it's small, and you can't click what you can't find.
  const bead = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 0.5, 16, 12),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: selected ? 1 : 0.85 }),
  );
  bead.userData.clipSelectTarget = target;
  return { disc, bead };
}

// geometryByTarget: {cranium: {planes, spheres}, face: {...}} exactly as the
// backend returns it. meshObject sizes the drawing to this patient's own
// head. returns a handle for removeClipPreview, plus the discs for hit-testing.
export function addClipPreview({ sceneBag, meshObject, geometryByTarget, selectedTarget }) {
  const box = new THREE.Box3().setFromObject(meshObject);
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 1);
  const planeSize = span * 1.25;
  const discRadius = span * 0.085;

  const root = new THREE.Group();
  const discs = [];
  let activeSphere = null;

  for (const [target, geometry] of Object.entries(geometryByTarget)) {
    if (!geometry) continue;
    const selected = target === selectedTarget;
    const color = selected ? SELECTED_COLOR : UNSELECTED_COLOR;

    for (const plane of geometry.planes ?? []) {
      // only the plane that actually delimits the region is drawn. the
      // cranial clip's angled rear/neck trim is housekeeping - it takes off
      // shoulders and stray scan geometry a horizontal cut would miss - and
      // drawing it put a second, inexplicably slanted plane through the
      // picture that read as another boundary. it still happens; it just
      // isn't something you choose a region by looking at.
      if (!plane.boundary) continue;
      const { group } = planeQuad(
        plane.normal,
        plane.origin,
        planeSize,
        color,
        selected ? OPACITY.boundaryFillSelected : OPACITY.boundaryFillUnselected,
      );
      root.add(group);

      if (plane.boundary) {
        const { disc, bead } = selectorDisc(target, discRadius, color, selected);
        // both boundary planes pass through the head, so a disc at the
        // plane's own origin would sit buried inside the mesh - invisible,
        // and clickable only through the skull. pushed out into the quad's
        // corner instead, where it's in clear air next to the head.
        const offset = planeSize * 0.33;
        disc.position
          .set(...plane.origin)
          .addScaledVector(new THREE.Vector3(1, 0, 0).applyQuaternion(group.quaternion), offset)
          .addScaledVector(new THREE.Vector3(0, 1, 0).applyQuaternion(group.quaternion), offset);
        disc.quaternion.copy(group.quaternion);
        bead.position.copy(disc.position);
        root.add(disc);
        root.add(bead);
        discs.push(disc, bead);
      }
    }

    if (!selected) continue; // only the active region's trim sphere, see above
    for (const sphere of geometry.spheres ?? []) {
      activeSphere = sphereShell(sphere.center, sphere.radius, color);
      root.add(activeSphere);
    }
  }

  sceneBag.scene.add(root);
  return { root, discs, activeSphere };
}

// moves and resizes the drawn trim sphere to match what the user has dialled
// in ("adjust clipping sphere"). offset is a displacement in the registered
// frame and radius is absolute mm, exactly what gets sent to /clip - so what
// they see here is what the clip will cut with. null radius means the tuned
// default the backend reported.
export function setClipPreviewSphere(handle, { offset, radius } = {}) {
  const sphere = handle?.activeSphere;
  if (!sphere) return;
  const [dx, dy, dz] = offset ?? [0, 0, 0];
  const [cx, cy, cz] = sphere.userData.baseCenter;
  sphere.position.set(cx + dx, cy + dy, cz + dz);
  sphere.scale.setScalar(radius ? radius / sphere.userData.baseRadius : 1);
}

export function removeClipPreview(sceneBag, handle) {
  if (!handle?.root) return;
  sceneBag.scene.remove(handle.root);
  handle.root.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
  });
}
