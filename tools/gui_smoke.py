from pathlib import Path
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.gui import App
from deskbridge.model import Device, Workspace
from deskbridge.storage import Profile


class DiscoveryStub:
    status = "自动发现已开启"
    updates = []
    def snapshot(self): return []
    def update(self, *args): self.updates.append(args)
    def close(self): pass

base = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="deskbridge-gui-", dir=base / "build") as folder:
    profile = Profile(Path(folder)/"profile")
    profile.acquire()
    root = tk.Tk()
    value = Workspace("Windows-PC", [Device("Mac-Studio", "macOS", 1, 1), Device("Windows-PC", "Windows", 2, 1), Device("Ubuntu", "Ubuntu", 3, 1)])
    app = App(root, profile, value, discovery=DiscoveryStub())
    root.update()
    assert app.collect().local_name == "Windows-PC"
    assert len(app.table.get_children()) == 3
    assert not hasattr(app, "address")
    app.mode.set("client")
    app.role_changed()
    assert app.discovery.updates[-1][-1] == "client"
    app.mode.set("server")
    app.role_changed()
    assert app.discovery.updates[-1][-1] == "server"
    app.workspace.devices = [Device("Windows-PC", "Windows", 1, 1), Device("Mac-Studio", "macOS", 2, 1, "a"*64)]
    app.mode.set("client")
    app.server.set("")
    app.refresh()
    assert app.server.get() == "Mac-Studio"
    assert app.collect().server_name == "Mac-Studio"
    app.set_controls(True)
    assert app.clipboard.get() is False
    app.set_controls(False)
    # Capture only this application's client area, with inactive unpaired demos.
    from PIL import ImageGrab
    def capture():
        try:
            root.update()
            root.lift()
            bounds = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())
            ImageGrab.grab(bbox=bounds).save(base / "docs" / "preview.png")
            print("PASS: Tk desktop UI, device table, form collection and preview")
        finally:
            app.close()
    root.after(700, capture)
    root.mainloop()
