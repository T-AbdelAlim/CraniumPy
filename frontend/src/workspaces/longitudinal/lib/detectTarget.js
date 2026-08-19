// matches this app's own exported-mesh naming convention (see
// api/results_bundle.py's _build_mesh_files: "{stem}_rg_C.ply"/
// "{stem}_rg_F.ply" for a plain registered+clipped mesh, "..._CN.ply"/
// "..._FN.ply" for a NICP-fitted one) - shared by TimepointSlot's "already
// registered file" fast path and CorrespondenceTab's "import pre-NICP'd
// meshes" button, so a picked file's target doesn't have to be remembered/
// re-selected by hand in either place.
export function detectTargetFromFilename(name) {
  if (/_rg_fn?\.[a-z0-9]+$/i.test(name)) return "face";
  if (/_rg_cn?\.[a-z0-9]+$/i.test(name)) return "cranium";
  return null;
}

// same idea but requires the NICP suffix specifically (the trailing "n") -
// a plain _rg_c/_rg_f file (no "n") is only registered+clipped, NOT fit to
// a shared template, so it does NOT share vertex correspondence with
// anything else. only the "n" variant is safe to treat as already mutually
// corresponding with another timepoint - used by the "import pre-NICP'd
// meshes" button, which skips fitting entirely and trusts the files it's
// given already share a template.
export function detectNicpTargetFromFilename(name) {
  if (/_rg_fn\.[a-z0-9]+$/i.test(name)) return "face";
  if (/_rg_cn\.[a-z0-9]+$/i.test(name)) return "cranium";
  return null;
}
