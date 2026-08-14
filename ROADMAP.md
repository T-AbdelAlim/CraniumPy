# Roadmap

## Implemented
* Rigid, landmark-based registration (3 landmarks, plus an optional 4th secondary frontal landmark for the displayed/saved mesh)
* Staged align / adjust-picks / run-pipeline workflow, with re-registration on landmark adjustment
* Mesh repair (PyMeshFix) and resampling to a target vertex count
* Center-of-mass correction (validated, optional)
* Automated cephalometrics: OFD, BPD, cephalic index, occipitofrontal circumference, mesh volume - validated for pediatric heads
* Mean facial asymmetry (MFA) scoring with a per-vertex heatmap
* Template overlay comparison (shipped + custom templates) with center-of-gravity offset
* In-viewer visualization: metrics overlay (HC/BPD/OFD lines + numeric panel), asymmetry heatmap with colour scale, template alignment view
* Results saving: local folder (desktop app) or zip download (web app), with a JSON report and a 2D measurement figure
* Textured mesh support (.obj + .mtl + texture), with wireframe/texture toggles
* Cross-platform: web app + standalone desktop app (Windows .exe, macOS .app for Apple Silicon and Intel)

## Planned

### Per-patient / longitudinal
* Multi-image linking and comparison
* Follow-up heatmap visualization
* Objective shape severity score (FP score) - [details](https://doi.org/10.1111/joa.14061)

### Batch / cohort analysis
* Batch pipeline runner - process a folder of meshes end-to-end without repeating the manual steps per file, with resumable progress and per-file logs
* Cohort manifest - link each processed mesh to patient ID, visit date, treatment group, and other metadata (CSV/JSON)
* Aggregate cohort statistics - mean/SD/median per metric (HC, BPD, OFD, CI, volume, MFA), exportable summary tables
* Stratified group comparisons - by treatment type, age bracket, sex, syndrome, etc., with standard group-comparison stats (t-test/ANOVA, effect sizes)
* Normative/percentile reference curves - age/sex-matched percentile or z-score comparison, similar to pediatric growth charts
* Automated QC flags - surface failed/suspect pipeline runs (bad repair, outlier asymmetry likely from a mis-pick) for manual review instead of checking every file by hand
* Bulk export to CSV/Excel for downstream analysis in R/SPSS/etc.
* De-identification helper - strip patient identifiers from filenames/metadata before sharing a batch dataset

### Registration & landmarks
* Automated facial landmark detection for anthropometrics (manual override kept)
* Non-rigid registration exposed in UI (algorithm already implemented, not yet in UI)
* Multi-step undo/redo for landmark picks
* Inter-rater reliability mode

### Subtype-specific metrics (literature-established, per craniosynostosis subtype)
* Frontal bossing index / fronto-orbital angle (trigonocephaly)
* Cranial vault asymmetry index (CVAI) + oblique diagonal difference (plagiocephaly)
* Cranial index of symmetry (CIS)
* Vertical/height index (turricephaly)
* Per-measurement repeatability estimate
* Single-patient percentile/z-score vs. normative data

### Visualization & reporting
* Side-by-side / slider comparison view
* PDF report export
* Rotating snapshot/video export

### Data & workflow
* Local analysis history
* Measurement protocol/version tagging

### Quality & collaboration
* Pre-analysis scan sanity check
* Second-rater sign-off workflow
