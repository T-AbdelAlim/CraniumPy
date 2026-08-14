# Roadmap

## Implemented
* Rigid, landmark-based registration (3 landmarks, plus an optional 4th secondary frontal landmark for the displayed/saved mesh)
* Staged align / adjust-picks / run-pipeline workflow, with re-registration on landmark adjustment
* Mesh repair (PyMeshFix) and resampling to a target vertex count
* Center-of-mass correction (validated, optional)
* Automated cephalometrics: OFD, BPD, cephalic index, occipitofrontal circumference, mesh volume - validated for pediatric heads
* Mean facial asymmetry (MFA) scoring with a per-vertex heatmap
* Template overlay comparison (preinstalled templates + custom option) with center-of-gravity offset
* In-viewer visualization: metrics overlay (HC/BPD/OFD lines + numeric panel), asymmetry heatmap with colour scale, template alignment view
* Results saving: local folder (desktop app) or zip download (web app), with a JSON report and a 2D measurement/asymmetry figure
* Textured mesh support (.obj + .mtl + texture), with wireframe/texture toggles
* Cross-platform: web app + standalone desktop app (Windows .exe, macOS .app)

## Planned

### Per-patient / longitudinal
* Multi-image linking and comparison
* Follow-up heatmap visualization
* Objective shape severity score (FP score) - [details](https://doi.org/10.1111/joa.14061)

### Batch / cohort analysis
* Batch pipeline runner - process a folder of preprocessed meshes end-to-end without repeating the manual steps per file, with resumable progress and per-file logs
* Aggregate cohort statistics - mean/SD/median per metric (HC, BPD, OFD, CI, volume, MFA), import predefined excelsheet, exportable summary tables
* Stratified group comparisons - by treatment type, age bracket, sex, syndrome, etc., with standard group-comparison stats (t-test/ANOVA, effect sizes) based on predefined excelsheet
* Normative/percentile reference curves - age/sex-matched percentile or z-score comparison, similar to pediatric growth charts
* Automated QC flags - surface failed/suspect pipeline runs (bad repair, outlier asymmetry likely from a mis-pick) for manual review instead of checking every file by hand
* Bulk export to CSV/Excel for downstream analysis
* De-identification helper - strip patient identifiers from filenames/metadata before sharing a batch dataset

### Registration & landmarks
* Automated facial landmark detection for anthropometrics
* Non-rigid registration implementation (NICP)

### Subtype-specific metrics (literature-established, per craniosynostosis subtype)
* Frontal bossing index (scaphocephaly)
* Fronto-orbital angle (trigonocephaly)
* Cranial vault asymmetry index (CVAI) + oblique diagonal difference (plagiocephaly)
* Cranial index of symmetry (CIS)
* Vertical/height index (turricephaly)
* Per-measurement repeatability estimate
* Single-patient percentile/z-score vs. normative data

### Visualization & reporting
* Side-by-side comparison view
* Heatmap
* PDF report export

### Data & workflow
* Local analysis history
* Measurement protocol/version tagging

### Quality & collaboration
* Pre-analysis automated mesh quality control
