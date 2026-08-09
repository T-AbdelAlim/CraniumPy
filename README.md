# CraniumPy

  * [Description](#description)
  * [Usage](#usage)
    * [Getting started](#getting-started)
    * [Preprocessing - landmarks](#preprocessing---landmarks)
    * [Registration](#registration)
    * [Clipping](#clipping)
    * [Automated measurement extraction](#automated-measurement-extraction)
    * [Facial asymmetry calculation](#facial-asymmetry-calculation)
    * [Mesh cleanup](#mesh-cleanup)
  * [Running it](#running-it)
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
desktop app (same codebase either way, see [Running it](#running-it)). the old
PyQt5 version is still there on the `legacy-craniumpy` branch if you need it.

what it does right now (rigid registration + manual landmarking only for the
moment - see [Registration](#registration) for why):
- rigid, landmark-based registration.
- mesh repair via [PyMeshFix](https://pymeshfix.pyvista.org/) and resampling
  to a target vertex count you set.
- a [validated algorithm](http://dx.doi.org/10.1097/SCS.0000000000009448) for
  extracting the usual head measurements automatically.
- facial asymmetry scoring.

![Reconstruction](resources/CraniumPy_info.png)


## Usage

### Getting started
upload a mesh, pick 3 landmarks, register, clip, and run the analysis. the
sidebar walks you through it in order. `resources/test_mesh/test_mesh.ply` is
in the repo if you want something to try it on first.

the old step-by-step PDF guide (`resources/documentation.pdf`) is for the
legacy PyQt5 version and doesn't match this UI anymore - the sidebar here is
meant to be self-explanatory, but let me know if something isn't clear.

### Preprocessing - landmarks
click 3 points on the mesh - nasion, left tragus, right tragus, in that order
- while holding **ctrl** (or **cmd** on mac). holding the modifier key is
required on purpose, so a plain click can still orbit the camera without
accidentally dropping a landmark.

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

### Clipping
pick **cranial** or **facial** for the usual clip through the nasion-tragus
plane or the landmark-triangle centroid, or **manual** to drag your own
cutting plane through the mesh in the viewer. the arrow on the plane points
into the half that gets kept.

### Automated measurement extraction
from a cranially-registered mesh you get:
- occipitofrontal diameter (OFD) / head depth
- biparietal diameter (BPD) / head breadth
- cephalic index (CI)
- occipitofrontal circumference (OFC) / head circumference
- mesh volume above the nasion-tragus plane (rough ICV proxy)

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
after clipping, the mesh gets repaired (fills holes, fixes face winding -
uncheck it if you want the raw clipped mesh) and resampled down to a target
vertex count, 10000 by default. bump it up or down depending on what you
need - just know the craniometrics algorithm was validated at 10000, so
results on a very different count haven't specifically been checked.


## Running it

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

same backend, same UI, either way you run it.


## Known issues

- mesh volume can come out noisier than the other measurements on a raw,
  unrepaired scan - it's not well defined on a mesh that isn't watertight,
  which a raw scan usually isn't until it's gone through the repair step.
- resampling uses quadric decimation, not true Voronoi/ACVD clustering - it's
  a different algorithm from what the original app used (see
  `DEPENDENCIES.md` if you want the full reasoning), close enough in practice
  but the vertex distribution won't look identical.
- no automatic landmark detection, on purpose - see
  [Preprocessing](#preprocessing---landmarks) above.


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
