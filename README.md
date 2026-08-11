# CraniumPy

  * [Description](#description)
  * [Download](#download)
  * [Usage](#usage)
    * [Getting started](#getting-started)
    * [Preprocessing - landmarks](#preprocessing---landmarks)
    * [Registration](#registration)
    * [Visualization](#visualization)
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

CraniumPy registers and analyzes craniofacial 3D scans (.ply, .obj, .stl): landmark picking, registration, clipping, repair, and resampling, followed by cephalometric measurements or a facial asymmetry score.

Runs as a local web app or a standalone desktop app. The legacy PyQt5 version is on the `legacy-craniumpy` branch.

Current capabilities (rigid registration and manual landmarking only - see [Registration](#registration)):
- Rigid, landmark-based registration, with an optional secondary frontal landmark (e.g. subnasale) for the displayed/saved mesh.
- Template overlay comparison with center-of-gravity offset.
- Mesh repair ([PyMeshFix](https://pymeshfix.pyvista.org/)) and optional resampling to a target vertex count.
- [Validated](http://dx.doi.org/10.1097/SCS.0000000000009448) automated head measurements.
- Facial asymmetry scoring, with an in-viewer colour scale.

![Reconstruction](resources/CraniumPy_info.png)


## Download

The standalone Windows and macOS apps need no Python or dependencies. Get the latest build from the [releases page](https://github.com/T-AbdelAlim/CraniumPy/releases/latest).

- The Windows .exe is unsigned, so SmartScreen or your antivirus may flag it on first run. Click "More info" then "Run anyway".
- The macOS .app is unsigned/unnotarized, so Gatekeeper will refuse to open it normally. Right-click (or Ctrl-click) the app, choose "Open", then confirm in the dialog that appears - only needed the first time. There are separate builds for Apple Silicon and Intel Macs; pick the one matching your Mac.
- In the desktop app, "Save results" writes directly next to your original file via a native file picker (see [Saving your results](#saving-your-results)).

For other platforms, or to run from source, see [Running it from source](#running-it-from-source).


## Usage

### Getting started
Upload a mesh, pick 3 landmarks, register, clip, and run the analysis. `resources/test_mesh/test_mesh.ply` is included for testing.

For a textured .obj, select the .obj, its .mtl, and the texture image together. Once a mesh is loaded, a wireframe toggle appears, and a texture toggle if it has a texture.

### Preprocessing - landmarks
Click 3 points on the mesh - sellion, left tragus, right tragus, in that order - while holding **Ctrl** (**Cmd** on Mac). Alt+drag a landmark to reposition it.

The sellion is the soft-tissue landmark at the deepest point of the nasal root depression, between the eyes - it approximates the skeletal landmark nasion, which sits underneath it and isn't directly visible on a surface scan. In the 3D photogrammetry literature the two are often used interchangeably, since only sellion is actually clickable on this kind of data.

There is no automatic landmark detection; landmarks are always picked manually.

For cranial analysis, a checkbox unlocks a 4th, optional landmark (e.g. subnasale). It takes over the registration/clip/display frame for the mesh you see and save, while the actual measurements and the saved 2D figure always stay anchored on sellion.

### Registration
Rigid, landmark-triangle alignment only. A non-rigid mode exists in the codebase but is not exposed in the UI.

"Center-of-mass correction" nudges the head forward/back to compensate for imprecise landmark clicking. It only ever moves the head along its depth axis - never sideways or vertically - and, when the optional 4th landmark is used, the same correction is always derived from the sellion plane so both the sellion measurements and the displayed mesh stay consistent with each other. Recommended for most use-cases.

- **Off**: registration is just the landmark-triangle alignment - the mesh is translated so the centroid of the 3 clicked landmarks lands on the reference frame's origin, nothing more.
- **On** (default): same alignment, plus a single depth-only translation on top, from that initial anchor to the centroid of the head-circumference slice - so the final position reflects the whole head's shape, not just 3 clicked points, giving more consistent comparisons across scans/raters. See [the validation paper](https://journals.lww.com/jcraniofacialsurgery/fulltext/10.1097/scs.0000000000009448~reliability-and-agreement-of-automated-head-measurements) for the full method and reliability data.

### Visualization
After analysis, "Visualization" lets you show either the measurement lines or a template comparison over the result mesh - never both at once, since they'd occupy the same space on the viewer.

**Measurements** (cranial only, default when available): draws the HC circumference ring (red), BPD span (blue), and OFD span (green) on the mesh, the same colours as the saved 2D figure. The mesh goes semi-transparent while these are showing so a line running along the far side stays visible, and a panel over the viewer shows the numeric values.

**Template alignment**: displays a semi-transparent reference template over the result, with axes and center-of-gravity markers for both meshes.

The "Compare against" dropdown selects a shipped template or a custom file, always shown exactly as stored on disk (no live clipping to match your own mesh). Shipped templates: a clipped cranium reference (with and without center-of-mass correction), a subnasale-landmark full-head reference (with and without center-of-mass correction), and a face reference. The default selection matches your own settings automatically - the subnasale full-head reference if you used the secondary frontal landmark, the clipped cranium reference otherwise, both picking the center-of-mass variant to match your own "center-of-mass correction" checkbox. In the desktop app, custom template paths are remembered per target (cranial/facial). In the web app, they are not.

### Clipping
Choose **cranial**, **facial**, or **manual** clipping. The clip boundary is left open, not capped - repair runs before clipping, so exported meshes may appear open at the cut.

### Automated measurement extraction
From a cranially-registered mesh:
- Occipitofrontal diameter (OFD)
- Biparietal diameter (BPD)
- Cephalic index (CI)
- Occipitofrontal circumference (OFC)
- Mesh volume above the landmark plane

![Hcvalidation](resources/hcvalidation.jpg)

Validated for pediatric heads only; hard-coded sanity bounds apply (see `src/craniumpy_core/craniometrics.py`).

### Facial asymmetry calculation
Mirrors a facially-registered mesh across the midline and measures per-vertex distance to the mirrored surface, producing a heatmap (mm) and a mean facial asymmetry index (MFAI). The viewer shows a colour scale bar alongside the heatmap; the saved figure has its own.

The heatmap and MFAI describe opposite halves of the face by default - a quirk carried over from the original algorithm (see `src/craniumpy_core/asymmetry.py`).

### Mesh cleanup
After registration: repair (always on - a real scan can be thousands of disconnected pieces, and repair is what makes it one usable surface), clip, then resample to a target vertex count (optional, default 10000). The measurement algorithm was validated at 10000 vertices.

### Saving your results
Desktop app: "Save results" writes a `CP_{name}_{C|F}_{3|4}[_CoM]/` folder next to the original file, containing the registered mesh, the final mesh, a JSON report, and the measurement figure. `C`/`F` is cranial/facial, `3`/`4` is how many landmarks were used, and `_CoM` is only appended if center-of-mass correction was on - so two runs with different settings on the same file land in different folders instead of overwriting each other.

Web app: the same folder is downloaded as a zip.

Filenames are shortened: a dotted sub-segment (e.g. `1016510_20210730.000112_edited`) is truncated at the first dot (`1016510_20210730_edited`). The original filename is preserved in the report.


## Running it from source

Requires Python 3.11+.

```
git clone https://github.com/T-AbdelAlim/CraniumPy.git
cd CraniumPy
python -m venv .venv
.venv\Scripts\Activate.ps1      # windows/powershell. bash: source .venv/Scripts/activate. mac/linux: source .venv/bin/activate
pip install -e .
```

Web app:
```
python -m uvicorn api.main:app --port 8734
```
Open `http://127.0.0.1:8734`.

Desktop app:
```
pip install -e ".[desktop]"
python -m desktop.app
```

The standalone Windows .exe is built from this same code via `desktop/craniumpy.spec` and PyInstaller; the macOS .app via `desktop/craniumpy_mac.spec`, same command, run on an actual Mac (PyInstaller can't cross-compile - see `.github/workflows/build-macos.yml` for the CI build).


## Known issues

- Mesh volume requires a watertight mesh. Since the final mesh is intentionally left open at the clip boundary, volume is computed from a temporary capped copy; it reports 0 if that copy cannot be made watertight.
- Resampling uses quadric decimation, not Voronoi/ACVD clustering (see `DEPENDENCIES.md`). Vertex distribution differs from the original app.
- No automatic landmark detection.


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
