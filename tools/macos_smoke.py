"""Mount the final DMG and verify a separate installation copy, no input."""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge import __version__ as VERSION

if sys.platform != "darwin":
    raise SystemExit("This check requires macOS")
image = ROOT / "dist" / f"DeskBridge-{VERSION}-macos-{platform.machine()}.dmg"
subprocess.run(["hdiutil", "verify", str(image)], check=True)
with tempfile.TemporaryDirectory(prefix="dmg-install-check-", dir=ROOT / "build") as name:
    folder = Path(name)
    mount = folder / "mounted"
    mount.mkdir()
    attached = False
    try:
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image)], check=True)
        attached = True
        installed = folder / "Applications/DeskBridge.app"
        installed.parent.mkdir()
        shutil.copytree(mount / "DeskBridge.app", installed, symlinks=True)
        if not (installed / "Contents/Resources/engine/Deskflow.app/Contents/MacOS/deskflow-core").is_file():
            raise AssertionError("Missing bundled input core")
        if not (installed / "Contents/Resources/docs/quick-start.md").is_file():
            raise AssertionError("Missing bundled quick start")
        subprocess.run(["codesign", "--verify", "--strict", str(installed)], check=True)
        subprocess.run([sys.executable, str(ROOT / "tools/frozen_checks.py"),
                        str(installed / "Contents/MacOS/DeskBridge")], check=True)
    finally:
        if attached:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)
print("PASS: final DMG integrity, mount/copy installation, bundle signature, identity persistence and native core loading")
