# Roadmap

## Implemented
* Rigid, landmark-based registration (3 landmarks, plus an optional 4th secondary frontal landmark for the displayed/saved mesh) - picking/clearing the 4th landmark auto-selects the matching shipped template
* Staged align / adjust-picks / run-pipeline workflow, with re-registration on landmark adjustment
* Mesh repair (PyMeshFix) and resampling to a target vertex count
* Center-of-mass correction (validated, optional)
* Non-rigid template registration (NICP), as an optional post-processing step - live fit preview, adjustable stiffness schedule, gives every processed patient the shipped template's own topology for downstream shape analysis
* Automated cephalometrics: OFD, BPD, cephalic index, occipitofrontal circumference, mesh volume - validated for pediatric heads
* Forehead morphology and frontal bossing: a frontal bossing angle (frame-consistent, carried across a secondary-landmark display frame rather than re-derived, anchored to the shared head-circumference slice height), a parabola-fitted forehead contour analysis (frontal angle, midline ridge protrusion/area (signed), per-side temporal hollowing/depth, parabolic deviation index) - see [Known issues](README.md#known-issues) for validation status and the self-referential-reference caveat
* Mean asymmetry (MFA) scoring with a per-vertex heatmap, for both cranial (top-down) and facial (frontal) targets, each with a side-on companion figure
* Target switching (Cranial Vault / Face & Forehead) preserves landmarks/alignment and instantly restores each target's already-built scene instead of re-running or losing it
* Template overlay comparison (preinstalled templates + custom option) with center-of-gravity offset
* In-viewer visualization: metrics overlay (HC/BPD/OFD + frontal bossing construction), asymmetry heatmap and forehead-morphology overlay with colour scale, template alignment view - every measurement/graph has a hover explainer, with shaded reference windows and an ideal-parabola comparison curve on the forehead-morphology profile graphs
* Patient/visit metadata form (patient ID, diagnosis with a craniosynostosis-subtype quick-pick, sex, imaging date, ages, treatment, free variable)
* Export selection: checkboxes choose whether measurements, asymmetry, and/or meshes are included in a given export
* Reporting: a JSON report (every measurement plus a settings block - target, landmark count, center-of-mass correction, NICP template), a vector PDF report (asymmetry section always last) pairing each measurement with a plain-language explanation, and a per-patient Excel summary (real numeric cells, formatted as an Excel table) - filenames tagged `_cranial`/`_frontal` by target
* Cohort export (desktop-only): accumulates rows across sessions into a shared Excel file, keyed on source file so a re-export updates rather than duplicates; each distinct file gets a sequential cohort ID, with the patient ID <-> cohort ID mapping kept in a separate, local-only file - a first step on "de-identification helper" below
* Cohort analysis workspace: a second top-level mode for exploring an accumulated cohort spreadsheet - filtering/stratifying, user-defined derived metrics, real statistical tests (Welch's/Mann-Whitney, ANOVA/Kruskal-Wallis, picked by group count) with explainers and doc links, plots, and a formatted Excel export of any comparison
* 3D mean shape across NICP-fitted patients sharing the same template: an inter-patient spread heatmap, a signed diff heatmap against a reference template, the same craniometrics/asymmetry/forehead-morphology suite run on the averaged shape, a +/-1 SD spread ribbon (HC ring, metopic contour, sagittal profile) shown live in the 3D viewer or shaded into a mean-shape PDF report, and a named mesh export
* Results saving: local folder (desktop app) or zip download (web app), with a JSON report and 2D measurement/asymmetry/forehead-morphology figures
* Textured mesh support (.obj + .mtl + texture), with wireframe/texture toggles
* Cross-platform: web app + standalone desktop app (Windows .exe, macOS .app)

## Planned

### Per-patient / longitudinal
* Multi-image linking and comparison
* Follow-up heatmap visualization
* Objective shape severity score (FP score) - [details](https://doi.org/10.1111/joa.14061)

### Batch / cohort analysis
* Batch pipeline runner - process a folder of raw scans end-to-end without repeating the manual steps per file, with resumable progress and per-file logs (the cohort workspace explores what's already been exported; it doesn't run the pipeline itself)
* Normative/percentile reference curves - age/sex-matched percentile or z-score comparison, similar to pediatric growth charts
* Automated QC flags - surface failed/suspect pipeline runs (bad repair, outlier asymmetry likely from a mis-pick) for manual review instead of checking every file by hand
* De-identification helper, beyond cohort export's own patient ID/cohort ID split above - e.g. stripping identifiers out of filenames/free-text fields too before a batch dataset is shared

### Registration & landmarks
* Automated facial landmark detection for anthropometrics

### Subtype-specific metrics (literature-established, per craniosynostosis subtype)
* Fronto-orbital angle (trigonocephaly)
* Cranial vault asymmetry index (CVAI) + oblique diagonal difference (plagiocephaly)
* Cranial index of symmetry (CIS)
* Vertical/height index (turricephaly)
* Per-measurement repeatability estimate
* Single-patient percentile/z-score vs. normative data
* Clinical validation of the forehead-morphology metrics above against a graded severity score

### Visualization & reporting
* Side-by-side comparison view

### Data & workflow
* Local analysis history
* Measurement protocol/version tagging

### Quality & collaboration
* Pre-analysis automated mesh quality control
