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


def _run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


class Api:
    """exposed to the frontend as window.pywebview.api.* - the only thing in
    here right now is a native file dialog for picking a custom template
    mesh, since a plain browser <input type=file> can't hand back a real
    filesystem path (browser sandboxing, same reason "pick a folder" never
    could either) and the frontend needs a real path to remember across
    restarts. see frontend/app.js's custom template picker.

    the window reference has to be stored as _window (underscore), not
    window - pywebview auto-exposes every *public* non-callable attribute
    on this object too, recursing into it looking for more functions to
    expose (see webview/util.py's get_functions). a real webview.Window
    has native COM/WebView2 handles underneath with circular references
    (ActiveControl.Font.FontFamily... chains back on itself), so exposing
    it as a public attribute sent that recursion straight into a
    "maximum recursion depth exceeded" crash on startup - found out by
    actually launching the built exe, not just by it compiling."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None

    def pick_template_file(self) -> str | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Mesh files (*.ply;*.obj;*.stl)", "All files (*.*)"),
        )
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


if __name__ == "__main__":
    main()
