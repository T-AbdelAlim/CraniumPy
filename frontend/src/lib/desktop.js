// true once pywebview has finished injecting its bridge and attaching
// pick_file - checking the object's truthiness instead would report
// "desktop" during the gap right after injection starts but before
// pick_file actually exists, then fail calling something not there yet.
// ported from frontend_legacy/app.js's isDesktopApp().
export function isDesktopApp() {
  return typeof window.pywebview !== "undefined" && typeof window.pywebview.api?.pick_file === "function";
}

// wraps the native file dialog call (desktop/app.py's pick_file) so a
// failure - bad filter string, pywebview not ready yet - surfaces as a
// message the caller can show instead of the button silently doing
// nothing. resolves to null on cancel or error.
export async function pickFileNative(allowMultiple, onError) {
  try {
    return await window.pywebview.api.pick_file(allowMultiple);
  } catch (err) {
    onError?.(err && err.message ? err.message : String(err));
    return null;
  }
}

// same deal, for the native folder dialog (desktop/app.py's pick_folder) -
// backs the "change save folder..." override on save/export.
export async function pickFolderNative(onError) {
  try {
    return await window.pywebview.api.pick_folder();
  } catch (err) {
    onError?.(err && err.message ? err.message : String(err));
    return null;
  }
}

// same deal, for the native Excel file dialog (desktop/app.py's
// pick_excel_file) - backs the "create new cohort file..."/"add to
// existing cohort file..." controls on the metadata form. save=true opens
// a native Save dialog (create-new), save=false opens an Open dialog
// (append-existing) - the backend treats both the same either way (see
// api/results_bundle.py's _upsert_cohort_xlsx), this only changes which
// dialog the user sees.
export async function pickExcelFileNative(save, onError) {
  try {
    return await window.pywebview.api.pick_excel_file(save);
  } catch (err) {
    onError?.(err && err.message ? err.message : String(err));
    return null;
  }
}
