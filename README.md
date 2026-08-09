# CraniumPy

  * [Description](#description)
  * [Download](#download)
  * [Usage](#usage)
    * [Getting started](#getting-started)
    * [Preprocessing - landmarks](#preprocessing---landmarks)
    * [Registration](#registration)
    * [Comparing against a template](#comparing-against-a-template)
    * [Clipping](#clipping)
    * [Automated measurement extraction](#automated-measurement-extraction)
    * [Facial asymmetry calculation](#facial-asymmetry-calculation)
    * [Mesh cleanup](#mesh-cleanup)
    * [Saving your results](#saving-your-results)
  * [Running it from source](#running-it-from-source)
  * [Known issues](#known-issues)
  * [Citation](#citation)
  * [Author](#author)


## Description
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.5634153.svg)](https://doi.org/10.5281/zenodo.5634153)

CraniumPy registers and analyzes craniofacial 3D scans (.ply, .obj, .stl). give it
a raw scan and it'll take you from landmark picking through registration,
clipping, repair, and resampling, to either cephalometric measurements or a
facial asymmetry score.

this is a full rewrite of the original desktop app - same underlying methods,
new stack. it now runs either as a small local web app or as a standalone
desktop app (same codebase either way - see [Download](#download) if you just
want the app, or [Running it from source](#running-it-from-source) if you want
to run/modify the code yourself). the old PyQt5 version is still there on the
`legacy-craniumpy` branch if you need it.

what it does right now (rigid registration + manual landmarking only for the
moment - see [Registration](#registration) for why):
- rigid, landmark-based registration.
- overlay comparison against a reference template, with center-of-gravity
  offset, so you can sanity-check a registration at a glance.
- mesh repair via [PyMeshFix](https://pymeshfix.pyvista.org/) and resampling
  to a target vertex count you set (or skip resampling entirely).
- a [validated algorithm](http://dx.doi.org/10.1097/SCS.0000000000009448) for
  extracting the usual head measurements automatically.
- facial asymmetry scoring.

![Reconstruction](resources/CraniumPy_info.png)


## Download

the easiest way to use this is the standalone Windows app - no Python, no
dependencies, just an .exe. grab the latest build from the
[releases page](https://github.com/T-AbdelAlim/CraniumPy/releases/latest) and
run it - same way the older PyQt5 builds were distributed, just a much
smaller download now that SuiteSparse/VTK aren't in the dependency chain
anymore.

a couple of things worth knowing:
- it's not code-signed, so Windows SmartScreen / your antivirus will probably
  flag it the first time you run it ("Windows protected your PC" - click
  "more info" then "run anyway"). that's expected for an unsigned indie
  binary, not a sign anything's wrong.
- when it's running as the desktop app, "choose file(s)" and "save results"
  use a real native file picker, so results get written straight back next
  to your original scan automatically - no download folder to dig through
  (see [Saving your results](#saving-your-results)).

if you're not on Windows, or want to run it from source / modify it, see
[Running it from source](#running-it-from-source) below - it also runs as an
ordinary local web app from any platform Python supports.


## Usage

### Getting started
upload a mesh, pick 3 landmarks, register, clip, and run the analysis. the
sidebar walks you through it in order. `resources/test_mesh/test_mesh.ply` is
in the repo if you want something to try it on first.

the old step-by-step PDF guide (`resources/documentation.pdf`) is for the
legacy PyQt5 version and doesn't match this UI anymore - the sidebar here is
meant to be self-explanatory, but let me know if something isn't clear.

for a textured .obj, multi-select the .obj, its .mtl, and the texture image
together in the file picker. once something's loaded you get a wireframe
toggle, and (if it has a texture) a texture on/off toggle too, right under
the file picker.

### Preprocessing - landmarks
click 3 points on the mesh - nasion, left tragus, right tragus, in that order
- while holding **ctrl** (or **cmd** on mac). holding the modifier key is
required on purpose, so a plain click can still orbit the camera without
accidentally dropping a landmark. picked a point wrong? **alt + drag** it to
somewhere better instead of resetting and starting over.

there's no automatic landmark detection. I tried it (deforming a full head
template onto the scan and reading landmarks back off it) and pulled it out
again - it took several minutes with no feedback on what was happening, and
every attempt to speed it up made the results wrong. manual picking is fast
enough and you know exactly what you're getting.

### Registration
rigid, landmark-triangle alignment - that's all this does, no options to set.
this is all you actually need for craniometrics.

I did build and test a non-rigid mode too (rigid alignment, then deforming a
template onto the scan for matched topology across meshes) but pulled it out
entirely - not worth the runtime cost for what this app is actually used for.

### Comparing against a template
after running an analysis, "show template overlay" drops a semi-transparent
reference template over your (clipped) result, with X/Y/Z axes through the
origin and a marker at each mesh's center of gravity - a quick visual sanity
check that the registration actually landed where it should.

the "compare against" dropdown picks which template - any of the shipped
ones, or "custom..." to point it at your own. in the standalone app,
"browse..." opens a native file picker and remembers your pick per target
(cranial/facial) for next time, so you don't have to point it at the same
file over and over. running as a plain web app, there's no way to remember a
real file path across restarts (browser sandboxing), so it just asks again
each session.

### Clipping
pick **cranial** or **facial** for the usual clip through the landmark plane
or the landmark-triangle centroid, or **manual** to drag your own cutting
plane through the mesh in the viewer. the arrow on the plane points into the
half that gets kept.

the clipped edge is left open on purpose, not capped shut - repair runs
*before* clipping (fixing actual scan defects), not after, so it doesn't
accidentally weld the cut boundary closed. if you open the exported mesh in
another tool and the bottom looks "open," that's expected, not a bug.

### Automated measurement extraction
from a cranially-registered mesh you get:
- occipitofrontal diameter (OFD) / head depth
- biparietal diameter (BPD) / head breadth
- cephalic index (CI)
- occipitofrontal circumference (OFC) / head circumference
- mesh volume above the landmark plane (rough ICV proxy)

this is the validated part of the app - the slicing/measurement math hasn't
changed from the original. the viewer draws the actual head-circumference
slice as a red line so you can see what got measured, same idea as the figure
below.

![Hcvalidation](resources/hcvalidation.jpg)

note: this was built and validated for pediatric heads, so there are a few
hard-coded sanity bounds in the extraction algorithm (see
`src/craniumpy_core/craniometrics.py`). if it's not behaving for your use
case (adults, prematures, etc), reach out and we can figure something out.

### Facial asymmetry calculation
mirrors a facially-registered mesh across the midline, aligns the mirror back
onto the original, and measures the distance between each vertex and its
mirrored counterpart. gives you a heatmap (mm) plus a single mean facial
asymmetry index (MFAI) number.

heads up: there's a known quirk carried over from the original algorithm -
the heatmap and the MFAI number describe opposite halves of the face by
default (see the docstring in `src/craniumpy_core/asymmetry.py`). ported it
exactly as it was rather than silently changing the behavior, but you should
know about it.

### Mesh cleanup
after registration, the mesh gets repaired (fills holes, fixes face winding -
uncheck it if you want the raw registered mesh), clipped, then resampled down
to a target vertex count, 10000 by default - uncheck "resample" if you want
to keep the mesh's native vertex count instead. bump the target up or down
depending on what you need, just know the craniometrics algorithm was
validated at 10000, so results on a very different count haven't specifically
been checked.

### Saving your results
in the standalone desktop app, "save results" writes straight into a
`CP_{name}_results/` folder next to your original scan - the registered mesh,
the final (clipped/repaired/resampled) mesh, a json report, and the
measurement figure. no download dialog, no picking a destination.

running as a plain web app instead, there's no real file path to save next
to (browser sandboxing again), so the same folder comes down as a zip through
your browser's normal download flow.

either way, the results folder/zip name gets shortened a bit: if your
filename has a dotted segment in the middle (some scanners export things
like `1016510_20210730.000112_edited.ply`, date-plus-subversion), everything
from that dot onward within that segment gets dropped -
`CP_1016510_20210730_edited_results`, not
`CP_1016510_20210730.000112_edited_results`. the original filename is still
recorded as-is in the report itself, only the folder/file names get
shortened.


## Running it from source

no more conda + Cython + SuiteSparse + Visual Studio Build Tools dance - that
whole chain is gone. this only needs a normal Python (3.11+) virtual
environment.

```
git clone https://github.com/T-AbdelAlim/CraniumPy.git
cd CraniumPy
git checkout rewrite-craniumpy
python -m venv .venv
.venv\Scripts\Activate.ps1      # windows/powershell. bash: source .venv/Scripts/activate. mac/linux: source .venv/bin/activate
pip install -e .
```

**as a web app**, run the server and open it in a browser:
```
python -m uvicorn api.main:app --port 8734
```
then go to `http://127.0.0.1:8734`.

**as a standalone desktop app**, install the extra bit it needs for the
native window, then run it:
```
pip install -e ".[desktop]"
python -m desktop.app
```

same backend, same UI, either way you run it - this is also how the .exe on
the [releases page](https://github.com/T-AbdelAlim/CraniumPy/releases/latest)
gets built, via `desktop/craniumpy.spec` and PyInstaller, if you want to
build your own instead of running from source directly.


## Known issues

- mesh volume needs a watertight mesh to mean anything, and the final mesh is
  intentionally left open where it got clipped (see
  [Clipping](#clipping)) - so this number comes from a throwaway capped copy
  computed just for that measurement, not the mesh you actually get back. if
  it can't get that copy watertight either (repair unchecked, and real holes
  left over), it reports 0 rather than a made-up number.
- resampling uses quadric decimation, not true Voronoi/ACVD clustering - it's
  a different algorithm from what the original app used (see
  `DEPENDENCIES.md` if you want the full reasoning), close enough in practice
  but the vertex distribution won't look identical.
- no automatic landmark detection, on purpose - see
  [Preprocessing](#preprocessing---landmarks) above.
- the menu bar's "view" and "settings" entries (split screen, pre/post-op
  overlay, default templates & config) are placeholders for now - UI's there,
  nothing behind it yet.


## Citation
Kindly consider citing the software if it supports your research:

**Initial Publication:**

_Abdel-Alim et al. - Sagittal Craniosynostosis: Comparing Surgical Techniques using 3D Photogrammetry. Plastic and Reconstructive Surgery ():10.1097/PRS.0000000000010441, March 22, 2023. | DOI: [10.1097/PRS.0000000000010441](http://dx.doi.org/10.1097/PRS.0000000000010441)_

**Validation Study:**

_Abdel-Alim et al. - Reliability and Agreement of Automated Head Measurements From 3-Dimensional Photogrammetry in Young Children. The Journal of Craniofacial Surgery 34(6):p 1629-1634, September 2023. | DOI: [10.1097/SCS.0000000000009448](http://dx.doi.org/10.1097/SCS.0000000000009448)_

**Github Repository:**
```
Abdel-Alim, T. (2022). CraniumPy [Computer software]. https://doi.org/10.5281/zenodo.5634153
```


## Author
Tareq Abdel-Alim | Departments of Neurosurgery and Radiology, Erasmus MC, Rotterdam, the Netherlands

If you have any questions, suggestions, or problems do not hesitate to contact me:
t.abdelalim@erasmusmc.nl
