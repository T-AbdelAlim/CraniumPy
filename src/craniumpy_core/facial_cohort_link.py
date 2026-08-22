"""links the Facial Anthropometrics workspace's own batch measurement
export to an existing cohort study, by mesh filename.

mirrors api/results_bundle.py's own list_cohort_patients, which already
joins a cohort's id-mapping file (file_name/file_path -> cohort_id -
private identity fields, kept out of the shared cohort file itself) back to
cohort_id-keyed data - this is the same join, just keyed by filename
instead of patient_id, and reading the caller-supplied measurement
filenames instead of a fixed field. never reads the shared cohort file for
filenames - it never carries them (see api/results_bundle.py's
_COHORT_XLSX_EXCLUDED_COLUMNS), only cohort_id is common to both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FilenameMatchResult:
    matched: dict[str, str]  # measurement filename -> cohort_id
    unmatched: list[str] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # measurement filename -> candidate cohort_ids


def resolve_cohort_ids_by_filename(mapping_rows: list[dict[str, str]], measurement_filenames: list[str]) -> FilenameMatchResult:
    """joins a cohort's own id-mapping rows (api/results_bundle.py's
    _id_mapping_path/_upsert_cohort_xlsx - {cohort_id, patient_id, file_name,
    file_path, ...}) to a batch of measurement export filenames, by
    basename. a filename with no matching row is reported as unmatched, not
    silently dropped; a filename matching more than one row (two different
    patients' meshes that happen to share a basename, from different
    folders) is reported as ambiguous rather than guessing which one is
    right - the caller decides whether to proceed with the unambiguous
    rows anyway, same "never silently assign" requirement this exists for."""
    candidates_by_basename: dict[str, list[str]] = {}
    for row in mapping_rows:
        cohort_id = row.get("cohort_id", "")
        if not cohort_id:
            continue
        file_path = row.get("file_path", "")
        basename = Path(file_path).name if file_path else row.get("file_name", "")
        if not basename:
            continue
        candidates_by_basename.setdefault(basename, []).append(cohort_id)

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    for filename in measurement_filenames:
        unique_candidates = sorted(set(candidates_by_basename.get(filename, [])))
        if not unique_candidates:
            unmatched.append(filename)
        elif len(unique_candidates) == 1:
            matched[filename] = unique_candidates[0]
        else:
            ambiguous[filename] = unique_candidates

    return FilenameMatchResult(matched=matched, unmatched=unmatched, ambiguous=ambiguous)
