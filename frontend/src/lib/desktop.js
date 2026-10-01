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
// calls out for a bare <input type=file>.
//
// a LIST of waiters, not the single slot this used to keep. "drags are
// user-paced, not concurrent" turned out to be wrong in exactly the case
// that matters: building up a set of meshes by dropping several in quick
// succession (the Mean Shape workspace's whole workflow). a second waiter
// registering before the first one's paths came back overwrote the slot,
// and the first promise was then left to be garbage collected without
// ever settling - its `await` never returned, so that drop silently
// vanished with its handler stuck mid-flight and nothing on screen to say
// so. every waiter registered here settles, one way or the other.
let pendingNativeDropWaiters = [];
// paths that arrived before anything was waiting for them. pywebview's own
// drop listener round-trips through Python before calling back in
// (app.py's on_drop -> evaluate_js), so its timing against the plain-JS
// drop handler below isn't guaranteed either way - discarding them
// whenever the waiter hadn't registered yet meant the drop silently
// degraded to a pathless browser upload, and every later auto-save had
// nowhere to write (see App.jsx's autoSaveMeshes). held briefly instead,
// so a waiter starting a moment later still finds them.
let recentNativeDropPaths = null;
let recentNativeDropAt = 0;
const NATIVE_DROP_GRACE_MS = 2000;

if (typeof window !== "undefined") {
  window.__cranioSuiteNativeDrop = (pathsByName) => {
    // merged rather than replaced, within the grace window: several files
    // dropped as separate quick drags each arrive as their own call here,
    // and a waiter asking about one of them shouldn't have its answer
    // wiped by the next one landing.
    const stillFresh = Date.now() - recentNativeDropAt < NATIVE_DROP_GRACE_MS;
    recentNativeDropPaths = { ...(stillFresh && recentNativeDropPaths ? recentNativeDropPaths : {}), ...pathsByName };
    recentNativeDropAt = Date.now();
    // a waiter only takes the entries for the filenames IT was dropped, so
    // handing the whole accumulated map to everyone waiting is safe; one
    // still short of a name it needs keeps waiting for a later call.
    pendingNativeDropWaiters = pendingNativeDropWaiters.filter((waiter) => {
      if (!hasEveryName(recentNativeDropPaths, waiter.names)) return true;
      waiter.resolve(recentNativeDropPaths);
      return false;
    });
  };
}

function hasEveryName(paths, names) {
  if (!paths) return false;
  if (!names || names.length === 0) return true;
  return names.every((n) => paths[n]);
}

// races the native resolution above against a short timeout, so a plain
// browser drop (the web app always, or the rare case pywebview couldn't
// resolve a path) still uploads instead of hanging - resolves to
// {filename: fullPath} on a match within time, null otherwise (including
// immediately, in the web app, where there's no native bridge to wait on
// at all).
// names is what this particular drop actually carried, so an answer can
// be recognised as complete rather than merely present - without it a
// waiter would take whatever happened to be in the buffer from the drop
// BEFORE it and report its own files as unresolvable. callers that don't
// care (nothing does today) can leave it out and take the first answer.
export function waitForNativeDropPaths(names = null, timeoutMs = 1500) {
  if (!isDesktopApp()) return Promise.resolve(null);
  // already arrived (see the grace buffer above) - but only good enough if
  // it covers every file in THIS drop.
  if (Date.now() - recentNativeDropAt < NATIVE_DROP_GRACE_MS && hasEveryName(recentNativeDropPaths, names)) {
    return Promise.resolve(recentNativeDropPaths);
  }
  return new Promise((resolve) => {
    const waiter = { names, resolve };
    pendingNativeDropWaiters.push(waiter);
    setTimeout(() => {
      const i = pendingNativeDropWaiters.indexOf(waiter);
      if (i === -1) return; // already answered
      pendingNativeDropWaiters.splice(i, 1);
      // whatever did arrive, even if it's short of this drop's full set -
      // the caller decides what to do with a partial answer, and that's
      // strictly better than telling it nothing resolved at all.
      const partial = Date.now() - recentNativeDropAt < NATIVE_DROP_GRACE_MS ? recentNativeDropPaths : null;
      resolve(partial);
    }, timeoutMs);
  });
}
