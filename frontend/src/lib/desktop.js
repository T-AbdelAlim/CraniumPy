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

// same deal, for opening a real folder in the OS's own file browser
// (desktop/app.py's open_folder) - the "go to save folder" button next to
// "change save folder...". resolves to false on cancel/error/missing
// folder, same as the others returning null - the caller (App.jsx's
// handleGoToSaveFolder) doesn't have anything more specific to do with a
// failure than a generic one anyway.
export async function openFolderNative(path, onError) {
  try {
    return await window.pywebview.api.open_folder(path);
  } catch (err) {
    onError?.(err && err.message ? err.message : String(err));
    return false;
  }
}

// desktop-only bridge for a dropped file's REAL filesystem path (see
// desktop/app.py's _register_native_drop, which is what actually resolves
// it and calls this) - a plain browser drop only ever exposes File
// objects, never a real path, same limitation pick_file's own docstring
// calls out for a bare <input type=file>. one pending call at a time is
// all this ever needs (drags are user-paced, not concurrent), so a single
// resolver slot is enough - no per-drop correlation id.
let pendingNativeDropResolve = null;

if (typeof window !== "undefined") {
  window.__cranioSuiteNativeDrop = (pathsByName) => {
    if (!pendingNativeDropResolve) return;
    const resolve = pendingNativeDropResolve;
    pendingNativeDropResolve = null;
    resolve(pathsByName);
  };
}

// races the native resolution above against a short timeout, so a plain
// browser drop (the web app always, or the rare case pywebview couldn't
// resolve a path) still uploads instead of hanging - resolves to
// {filename: fullPath} on a match within time, null otherwise (including
// immediately, in the web app, where there's no native bridge to wait on
// at all).
export function waitForNativeDropPaths(timeoutMs = 400) {
  if (!isDesktopApp()) return Promise.resolve(null);
  return new Promise((resolve) => {
    pendingNativeDropResolve = resolve;
    setTimeout(() => {
      if (pendingNativeDropResolve !== resolve) return;
      pendingNativeDropResolve = null;
      resolve(null);
    }, timeoutMs);
  });
}
