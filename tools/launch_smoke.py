"""Launch our packaged GUI with an isolated profile, then stop only that process."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
executable = Path(sys.argv[1]).resolve(strict=True)
with tempfile.TemporaryDirectory(prefix="installed-gui-", dir=ROOT / "build") as name:
    profile = Path(name) / "profile"
    process = subprocess.Popen([str(executable), "--profile", str(profile)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"Installed GUI exited during startup: {process.returncode}")
            time.sleep(0.1)
        if not (profile / "tls/deskbridge.pem").is_file():
            raise AssertionError("Installed GUI did not initialize its isolated identity")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.communicate(timeout=5)
print("PASS: installed GUI process starts and stays running with its own profile; no sharing or input injection")
