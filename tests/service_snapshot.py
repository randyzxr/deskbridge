"""Compiled .NET validation; does not install a service or enter a secure desktop."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.identity import Identity
from deskbridge.lock_service import export_receiver, current_owner_sid
from deskbridge.model import Device, Workspace
from deskbridge.storage import Profile


def run(app):
    app = Path(app).resolve(strict=True)
    service = app/"service/DeskBridgeLockReceiver.exe"
    with tempfile.TemporaryDirectory(prefix="service-verify-", dir=Path(__file__).resolve().parent.parent/"build") as folder:
        folder = Path(folder)
        profile = Profile(folder/"profile")
        identity = Identity(profile.tls)
        value = Workspace("Receiver", [Device("Receiver", "Windows", 1, 1), Device("Shared", "Windows", 2, 1, "a"*64)], mode="client")
        snapshot = export_receiver(profile, value, identity, current_owner_sid())
        binaries = folder/"binaries"
        shutil.copytree(app/"engine", binaries/"engine")
        shutil.copy2(app/"service/deskflow-core.exe", binaries/"engine/deskflow-1.27.0-win-x64-portable/deskflow-core.exe")
        shutil.copy2(app/"service/EngineManifest.json", binaries/"EngineManifest.json")
        command = [str(service), "--verify-snapshot", str(snapshot), str(binaries)]
        def check(expected):
            result = subprocess.run(command, capture_output=True, timeout=10)
            assert (result.returncode == 0) == expected, result.stderr.decode(errors="replace")
        check(True)
        metadata = json.loads((snapshot/"service.json").read_text())
        original = (snapshot/"service.json").read_bytes()
        for changes in ({"local_name": "Receiver\n[security]"}, {"local_fp": "b"*64}, {"server_fp": metadata["local_fp"]}, {"port": 80}, {"command": "arbitrary"}):
            (snapshot/"service.json").write_text(json.dumps({**metadata, **changes}))
            check(False)
        (snapshot/"service.json").write_bytes(original)
        (binaries/"EngineManifest.json").write_bytes(b"{}")
        check(False)
        shutil.copy2(app/"service/EngineManifest.json", binaries/"EngineManifest.json")
        (binaries/"engine/unexpected.dll").write_bytes(b"extra")
        check(False)
        profile.close()
        print("PASS: compiled service snapshot identity/schema/injection/port/engine integrity rejection; no elevation or input")


if __name__ == "__main__": run(sys.argv[1])
