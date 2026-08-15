"""entry point for the standalone exe.

runs the same FastAPI app as a local server and opens it in a native window
with pywebview. this file (plus a pyinstaller spec) is basically the entire
desktop-specific part of this project - everything else is shared with the
web version.
"""

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


def main() -> None:
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # pywebview's WebView2 backend cancels every download silently unless
    # this is on - "download results" clicking through to nothing, no error,
    # was this. has to be set before webview.start() runs the event loop.
    webview.settings["ALLOW_DOWNLOADS"] = True

    api = Api()
    window = webview.create_window("CraniumPy", f"http://{HOST}:{PORT}", width=1280, height=800, js_api=api)
    api._window = window
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
