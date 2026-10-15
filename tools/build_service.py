"""Compile the receiver service against a digest of the verified engine inventory."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
from private_ipc import private_ipc, ORIGINAL_SHA256, OPTION_OFFSET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge import __version__


def build(app):
    app = Path(app)
    target = app/"service"
    target.mkdir(exist_ok=True)
    native = app/"engine"
    inventory = {p.relative_to(native).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in native.rglob("*") if p.is_file()}
    core_member = "deskflow-1.27.0-win-x64-portable/deskflow-core.exe"
    hardened = private_ipc((native/core_member).read_bytes())
    (target/"deskflow-core.exe").write_bytes(hardened)
    inventory[core_member] = hashlib.sha256(hardened).hexdigest()
    (target/"private-ipc-evidence.json").write_text(json.dumps({"original_sha256": ORIGINAL_SHA256,
        "patched_sha256": inventory[core_member], "file_offset": OPTION_OFFSET,
        "virtual_address": "0x14002dd2e", "change": "setSocketOptions argument: WorldAccessOption(7) -> UserAccessOption(1)",
        "scope": "receiver service engine only; all other bytes unchanged"}, indent=2), encoding="utf-8")
    data = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("ascii")
    (target/"EngineManifest.json").write_bytes(data)
    code = (ROOT/"service/LockReceiver.cs").read_text(encoding="utf-8").replace("__ENGINE_MANIFEST_SHA256__", hashlib.sha256(data).hexdigest())
    generated = ROOT/"build/LockReceiver.generated.cs"
    generated.write_text(code, encoding="utf-8")
    compiler = Path(os.environ.get("SystemRoot", r"C:\Windows"))/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                    "/reference:System.ServiceProcess.dll", "/reference:System.Web.Extensions.dll",
                    f"/out:{target/'DeskBridgeLockReceiver.exe'}", str(generated)], check=True)
    for filename in ("Install-LockReceiver.ps1", "Uninstall-LockReceiver.ps1", "private-ipc-source.patch"):
        shutil.copy2(ROOT/"service"/filename, target/filename)
    print("Built receiver service with fixed engine manifest digest")


if __name__ == "__main__":
    build(ROOT/"dist"/__version__/"DeskBridge")
