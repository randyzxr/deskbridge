"""Check a frozen release's identity persistence and native loader, no input."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge.identity import Identity
from deskbridge.process_env import run_external

executable = Path(sys.argv[1]).resolve(strict=True)
with tempfile.TemporaryDirectory(prefix="frozen-check-", dir=ROOT / "build") as folder:
    profile = Path(folder) / "profile"
    def run(*args):
        result = run_external([str(executable), "--profile", str(profile), *args],
                              timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            if args == ("--doctor",) and sys.platform == "win32":
                from deskbridge.core import check_engine
                native = next((executable.parent / "engine").glob("*/deskflow-core.exe"))
                # This fixed version-only probe has no private input or config.
                diagnostic = run_external([str(native), "--version"], cwd=str(native.parent),
                    timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                print("Native version-only diagnostic:", diagnostic.returncode,
                      diagnostic.stdout.decode(errors="replace")[:1024],
                      diagnostic.stderr.decode(errors="replace")[:2048])
            raise AssertionError(f"Frozen {args[0]} failed with exit code {result.returncode}")
    run("--fingerprint")
    first = Identity(profile / "tls").fingerprint()
    run("--fingerprint")
    assert Identity(profile / "tls").fingerprint() == first
    run("--doctor")
print("PASS: frozen identity creation/persistence and native version/loader probe; no sharing started")
