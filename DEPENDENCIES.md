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
| `openpyxl` | the per-session/cohort export spreadsheet (`_summary.xlsx`) - real columns, not raw CSV text, so it opens correctly regardless of the user's Excel locale (comma vs semicolon list separator - a plain CSV opened by double-click would otherwise land as one big unsplit column for a lot of people) | plain `csv` module, which is what this actually was until someone hit exactly that "everything in one cell" problem |
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
| `pywebview[cocoa]` (macOS only, via `sys_platform == 'darwin'` marker) | pywebview's Mac backend needs pyobjc's Cocoa/WebKit bindings - without it "import webview" just fails on a Mac | n/a, new |
| `pyinstaller` | builds the actual .exe / macOS .app | same tool the old app used |

## `dev` extra (`pip install craniumpy[dev]`)

| package | what it's for |
|---|---|
| `pytest` | test runner (old repo had exactly zero tests) |
| `httpx` | fastapi's TestClient needs this |

## frontend

`frontend/` is now a Vite + React project (plain JS, not TypeScript - matches
the minimal-tooling approach used everywhere else in this repo; not a
one-way door, TS can be adopted incrementally later if it ever earns its
keep). the old plain-HTML/JS viewer (no bundler, no react) is kept around at
`frontend_legacy/` purely as a reference while its functionality gets ported
over piece by piece - it isn't wired into anything anymore.

reason for the reversal: the suite rebuild needs a real multi-workspace
shell (routed workspaces, an inspector panel, tables, protocol/model
builders) - squarely React territory, and past the point where hand-rolled
DOM wiring in one `app.js` file stays maintainable. this is exactly the
"vite + something light" escape hatch this file used to flag as the
obvious next step once componentization was actually needed.

`frontend/dist/` (the build output, gitignored - see `frontend/.gitignore`)
is what actually gets served in every run mode: `api/main.py`'s
`FRONTEND_DIR`, and both PyInstaller specs' `datas`, point at `dist/`, not
the Vite source tree. `npm run build` in `frontend/` is a required one-time
step before running the backend from source or building the exe/app - see
`README.md`. `npm run dev` (Vite's own dev server, proxying `/api/*` to the
FastAPI backend) is for live frontend iteration instead.

| package | what it's for | replaced |
|---|---|---|
| `react`, `react-dom` | UI | hand-rolled DOM wiring in `frontend_legacy/app.js` |
| `react-router-dom` | routing between workspaces | n/a, new - the old app was one screen |
| `three` | 3D viewer (mesh, landmarks, heatmaps, template overlay) | the hand-vendored `frontend_legacy/vendor/three/` files below - now a real npm dependency, bundled by Vite into the built output, so the standalone exe still works fully offline (no CDN fetch at runtime either way) |
| `vite`, `@vitejs/plugin-react` | dev server + production build | n/a, new |

### vendored JS (`frontend_legacy/vendor/three/`) - historical, superseded

kept only because `frontend_legacy/` itself is kept, as a porting reference.
pulled from unpkg.com (mirrors npm packages directly). MIT licensed, straight
from the official `three` package, version 0.180.0 - the same version now
pinned as a real npm dependency above.

## looked at and passed on

| candidate | for what | why not |
|---|---|---|
| `open3d` | mesh I/O / ICP / viewing | trimesh + scipy's cKDTree cover the same ground, lighter install, and no separate viewer stack to keep in sync with the frontend. |
| pyacvd (voronoi resampling) | resampling | genuinely needs pyvista/VTK, no way around it - its Clustering class is built directly on pyvista.PolyData. unlike pymeshfix there's no VTK-free path here. staying with quadric decimation for now. |

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
