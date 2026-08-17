"""entry point for the standalone exe.

runs the same FastAPI app as a local server and opens it in a native window
with pywebview. this file (plus a pyinstaller spec) is basically the entire
desktop-specific part of this project - everything else is shared with the
web version.
"""

import json
import os
import platform
import subprocess
import threading

import uvicorn
import webview

from api.main import app

HOST = "127.0.0.1"
PORT = 8734

_server: uvicorn.Server | None = None


def _run_server() -> None:
    global _server
    _server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
    _server.run()


class Api:
    """exposed to the frontend as window.pywebview.api.* - a native file
    dialog, since a plain browser <input type=file> can't hand back a real
    filesystem path (browser sandboxing). used two ways: picking a custom
    template to remember across restarts (frontend/app.js's template
    picker), and picking the main mesh (+ its .mtl/texture companions) so
    results can be saved straight back next to it instead of needing a
    browser download (see api/routers/mesh.py's open_mesh_from_paths/save).

    the window reference has to be stored as _window (underscore), not
    window - pywebview auto-exposes every *public* non-callable attribute
    on this object too, recursing into it looking for more functions to
    expose (see webview/util.py's get_functions). a real webview.Window
    has native COM/WebView2 handles underneath with circular references
    (ActiveControl.Font.FontFamily... chains back on itself), so exposing
    it as a public attribute sends that recursion straight into a
    "maximum recursion depth exceeded" crash on startup."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None

    def pick_file(self, allow_multiple: bool = False) -> list[str] | None:
        if self._window is None:
            return None
        # pywebview validates each file_types string against its own regex
        # (webview.util.parse_file_type: only word characters and spaces in
        # the description) before it'll even open the dialog - a "+" in the
        # description fails that check silently: create_file_dialog raises
        # before the dialog ever shows, and with no .catch() on the frontend
        # side, "choose file(s)" just does nothing with no visible error.
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=allow_multiple,
            file_types=(
                "Mesh and texture files (*.ply;*.obj;*.stl;*.mtl;*.jpg;*.jpeg;*.png)",
                "All files (*.*)",
            ),
        )
        return list(result) if result else None

    def pick_folder(self) -> str | None:
        """lets the user override where /save* writes, instead of always
        going next to the original mesh file (see api/schemas.py's
        SaveRequest.dest_dir) - the frontend's "change save folder..."
        control."""
        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_excel_file(self, save: bool = False) -> str | None:
        """the frontend's cohort-spreadsheet picker (see api/schemas.py's
        SaveRequest.cohort_xlsx_path) - save=True opens a native Save
        dialog (defaulting to cohort.xlsx, for "create a new cohort
        file"), False opens a native Open dialog (for "add to an existing
        one"). the backend side doesn't actually care which dialog
        produced the path - create-vs-append collapses to the same upsert
        operation either way, see results_bundle._upsert_cohort_xlsx."""
        if self._window is None:
            return None
        dialog_type = webview.FileDialog.SAVE if save else webview.FileDialog.OPEN
        result = self._window.create_file_dialog(
            dialog_type,
            save_filename="cohort.xlsx" if save else "",
            file_types=("Excel files (*.xlsx)", "All files (*.*)"),
        )
        return result[0] if result else None

    def open_folder(self, path: str) -> bool:
        """the frontend's "go to save folder" button (see
        components/SaveFolderControl.jsx) - opens `path` in the OS's own
        file browser (Explorer/Finder/whatever *nix desktop is running).
        path is always something the backend itself just reported back as
        a real "saved_to" location (see api/routers/mesh.py's save/export
        endpoints), never raw user text, so there's no path-injection
        surface here worth hardening against - the isdir check below is
        purely to keep the button a harmless no-op if that folder got
        moved/deleted after the fact, not a security boundary."""
        if not path or not os.path.isdir(path):
            return False
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: S606
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True


def _register_native_drop(window: webview.Window) -> None:
    """desktop-only: lets a drag-and-drop onto the viewer (see
    frontend/src/components/Viewer.jsx's onFilesDropped) resolve the
    dropped file's REAL filesystem path, the same way "choose file(s)..."
    already can via pick_file above - a plain browser drop only ever hands
    the frontend File objects (name/size/bytes), never a real path, same
    limitation pick_file's own docstring already calls out for a bare
    <input type=file>.

    pywebview's own DOM drag-and-drop bridge (webview.dom) is what makes
    this possible: registering a 'drop' listener through it (rather than
    plain JS) makes pywebview additionally resolve each dropped file
    against WebView2's own native access to it, attaching the real path as
    'pywebviewFullPath' on that file's entry before this callback runs (see
    site-packages/webview/util.py's js_bridge_call and
    site-packages/webview/js/api.js's edgechromium branch, which is what
    actually asks WebView2 for the path via postMessageWithAdditionalObjects).

    registered on <body> (once the page has actually loaded - dom access
    needs real DOM to query against) rather than any specific element,
    since every drop bubbles up to it regardless of where on the page it
    lands; this fires ALONGSIDE the frontend's own plain-JS drop handler on
    the viewer container (both are independent listeners on the same real
    browser event), not instead of it - that handler already prevents the
    browser's own default action (navigating to the file) and always
    completes the upload itself, this only supplies a real path for it to
    prefer when one resolves in time (see lib/desktop.js's
    waitForNativeDropPaths, which races this against a short timeout so a
    plain browser drop, or a drop this couldn't resolve, still uploads
    normally instead of hanging).
    """

    def on_drop(event: dict) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = {f["name"]: f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")}
        if not paths:
            return
        window.evaluate_js(
            f"window.__cranioSuiteNativeDrop && window.__cranioSuiteNativeDrop({json.dumps(paths)})"
        )

    window.dom.body.events.drop += on_drop


def main() -> None:
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # pywebview's WebView2 backend cancels every download silently unless
    # this is on - "download results" clicking through to nothing, no error,
    # was this. has to be set before webview.start() runs the event loop.
    webview.settings["ALLOW_DOWNLOADS"] = True

    api = Api()
    window = webview.create_window("CranioSuite", f"http://{HOST}:{PORT}", width=1280, height=800, js_api=api)
    api._window = window
    window.events.loaded += lambda: _register_native_drop(window)
    webview.start()

    # webview.start() returns once the window closes, but the server thread
    # was still running uvicorn's asyncio loop with open sockets/file handles
    # into the pyinstaller onefile temp extraction dir - shutting it down and
    # waiting for the thread to actually exit, instead of just letting it get
    # killed as a daemon thread when the interpreter tears down, gives those
    # handles a chance to close before the bootloader tries to delete that
    # temp dir.
    if _server is not None:
        _server.should_exit = True
    server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
