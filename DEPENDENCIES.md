# dependencies

keeping track of every runtime dependency and why it's here, and what it
replaced from the old stack. pyproject.toml has the actual version pins,
this file is just for the "why" so I don't forget in six months.

update this whenever something gets added, removed, or swapped out.

## core (`pip install craniumpy`)

| package | what it's for | replaced |
|---|---|---|
| `numpy` | array math | (same as always) |
| `scipy` | KD-tree for ICP/correspondence | `scikit-learn` (KDTree) |
| `trimesh` | mesh I/O, geometry, repair/remesh, closest-point queries | `pyvista`, `vtk`, `pymeshfix`+`pyvista` combo, `pyacvd`, `menpo`/`menpo3d` (only ever used there for `VTKClosestPointLocator`), and 3 different hand-rolled PLY writers I found scattered around the old repo |
| `shapely` | trimesh's `slice_mesh_plane` needs this internally, even with cap=False | n/a, new - trimesh pulls it in whether you want capping or not |
| `fast-simplification` | quadric decimation resampling | `pyacvd` (needs pyvista) |
| `networkx` | trimesh's `fix_winding` needs this for graph coloring | n/a, new - pulled in by trimesh's repair module |
| `rtree` | spatial index for trimesh's closest-point queries (asymmetry.py) | menpo3d's `VTKClosestPointLocator` |
| `pillow` | trimesh needs this to decode a texture image referenced from an OBJ's MTL | n/a - found out the hard way, uploading a textured .obj failed with "no module named PIL" until I added this |
| `pymeshfix` | real hole-filling/repair, no pyvista needed for this part | (this used to be considered "needs VTK, skip it" - turns out that's wrong, see below) |
| `matplotlib` | the measurements figure (red HC line etc) in the results bundle | old app used pyvista for this kind of plot |
| `fastapi` | web API, shared by both the web version and the desktop app | nothing, old app had no service layer at all |
| `uvicorn` | ASGI server | nothing |
| `python-multipart` | file upload handling in fastapi | `tkinter.filedialog` |

**dropped and not replacing:** `mayavi`, `traits`/`traitsui`/`envisage`/`apptools`/`pyface`
(never actually used anywhere in the old repo, just sitting in requirements.txt),
`pandas` (craniometrics uses plain numpy/dataclasses now - also gets rid of the
`DataFrame.append()` call that broke on anything newer than pandas 1.3.3),
`open3d` (trimesh + scipy cover what it was doing here), `dash`/`plotly`/`flask`/
`opencv-python`/`jupyter*` and the rest of the old requirements.txt - that file
was just a `pip freeze` of someone's whole dev environment, not an actual
dependency list.

### about pymeshfix - I was wrong earlier

I originally said pymeshfix needed pyvista/VTK and skipped it to stay lean,
using trimesh's own repair instead. turns out that's not true. pymeshfix's
own `pip show` says `Requires: numpy` - full stop. pyvista is only needed for
its fancy visualization wrapper class, which I don't use. the low-level
`pymeshfix._meshfix.clean_from_arrays()` works entirely in memory, no VTK
anywhere. tested it on the real test mesh and it gets to fully watertight,
which trimesh's own repair couldn't manage. so now both are available -
pymeshfix is the default, trimesh stays as a fallback if pymeshfix is ever a
pain to install somewhere.

## `desktop` extra (`pip install craniumpy[desktop]`)

| package | what it's for | replaced |
|---|---|---|
| `pywebview` | native window pointed at the local server - this is what makes the web app into a desktop app with one shared codebase | `PyQt5`, `pyvistaqt`, `tkinter` |
| `pyinstaller` | builds the actual .exe | same tool the old app used |

## `dev` extra (`pip install craniumpy[dev]`)

| package | what it's for |
|---|---|
| `pytest` | test runner (old repo had exactly zero tests) |
| `httpx` | fastapi's TestClient needs this |

## frontend

no package.json, no node toolchain at all. the 3D viewer is plain HTML/JS
using three.js as a native ES module, no bundler, no react. reasons:
1. there's no node/npm on this machine and pulling in a whole JS toolchain
   just for a mesh viewer + landmark picker + results panel seemed like
   overkill.
2. keeps the standalone exe build a plain `pip install` + `pyinstaller` step,
   no separate JS build stage to worry about keeping in sync.

if the frontend ever grows enough to need real componentization, vite + something
light is the obvious next step. nothing in the backend cares either way.

### vendored JS (`frontend/vendor/three/`)

pulled from unpkg.com (mirrors npm packages directly), with the go-ahead to
download it. these are committed to the repo, not loaded from a CDN, so the
standalone exe actually works offline. MIT licensed, straight from the
official `three` package.

| file | source | size |
|---|---|---|
| `three.module.js` | `unpkg.com/three@0.180.0/build/three.module.js` | ~603 KB |
| `three.core.js` | `unpkg.com/three@0.180.0/build/three.core.js` (three.module.js needs this - found out when the browser 404'd on it, didn't grab it up front) | ~1.4 MB |
| `controls/OrbitControls.js` | `unpkg.com/three@0.180.0/examples/jsm/controls/OrbitControls.js` | ~39 KB |
| `loaders/GLTFLoader.js` | `unpkg.com/three@0.180.0/examples/jsm/loaders/GLTFLoader.js` | ~115 KB |
| `utils/BufferGeometryUtils.js` | `unpkg.com/three@0.180.0/examples/jsm/utils/BufferGeometryUtils.js` | ~35 KB (GLTFLoader needs this one) |

index.html points the bare `"three"` import at the vendored copy via an
import map. didn't touch the downloaded files otherwise. to bump the
version, just re-fetch all four from the same unpkg URL pattern (keep the
version numbers matching across all of them) and update this table.

## looked at and passed on

| candidate | for what | why not |
|---|---|---|
| `open3d` | mesh I/O / ICP / viewing | trimesh + scipy's cKDTree cover the same ground, lighter install, and no separate viewer stack to keep in sync with the frontend. |
| pyacvd (voronoi resampling) | resampling | genuinely needs pyvista/VTK, no way around it - its Clustering class is built directly on pyvista.PolyData. unlike pymeshfix there's no VTK-free path here. staying with quadric decimation for now. |
| react + vite | frontend | no node toolchain on this machine, and the UI (viewer + picker + results panel) doesn't need componentization yet. |

automatic landmark detection (deforming a full head template onto the scan
and reading landmarks back off it) was tried and then removed entirely -
took several minutes with no progress feedback, and attempts to speed it up
made the results wrong. non-rigid registration itself (deforming a template
onto a scan for topology-normalized output) was built, tested, and then
pulled too - too slow to be worth it for what this app is actually used
for. see pipeline.py.

## known trade-offs

- **resampling**: quadric decimation (`fast-simplification`) targets a face
  count, not vertex count directly - I approximate with `2 * n_vertices`.
  it's also just a different algorithm from ACVD/voronoi clustering, so the
  resulting vertex distribution won't look identical, just similarly
  uniform-ish. haven't specifically validated this against craniometrics
  accuracy yet.
