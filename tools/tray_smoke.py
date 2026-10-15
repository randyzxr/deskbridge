"""Check our own Tk/tray lifecycle, without clicking or injecting OS input."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge.gui import App, tk
from deskbridge.model import Workspace
from deskbridge.storage import Profile


class Discovery:
    status = "Test"
    def update(self, *args): pass
    def snapshot(self): return []
    def close(self): pass


with tempfile.TemporaryDirectory(prefix="tray-smoke-", dir=ROOT / "build") as folder:
    profile = Profile(Path(folder) / "profile")
    root = tk.Tk()
    app = None
    try:
        app = App(root, profile, profile.load("Windows"), discovery=Discovery())
        root.update()
        assert app.tray.ready, "Windows notification icon did not initialize: " + app.tray.failure
        with patch.object(app.core, "stop") as stop:
            app.hide_or_close()
            root.update()
            assert root.state() == "withdrawn"
            stop.assert_not_called()
            app.tray._action("show")
            app.poll()
            root.update()
            assert root.state() == "normal"
            app.tray._action("show")
            for _ in range(10000):
                app.tray._action("show")
            assert app.tray.actions() == {"show"}, "Unbounded tray callback buffer"
            app.hide_window()
            app.tray._action("unavailable")
            app.poll()
            root.update()
            assert root.state() == "normal", "Tray failure left window inaccessible"
        thread = app.tray._thread
        app.busy = True
        app.close()
        assert not app._closing and app._quit_requested
        app.busy = False
        app.poll()
        assert app._closing and not thread.is_alive()
        print("PASS: native tray creation, hide/restore without stopping, bounded actions, failure recovery, exit cleanup")
    finally:
        if app and not app._closing:
            app.close()
        profile.close()
