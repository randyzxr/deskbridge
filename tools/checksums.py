"""Checksum complete, explicit release artifacts; never include runtime profiles."""
from pathlib import Path
import hashlib
import platform
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge import __version__ as VERSION

artifacts = sorted(path for path in (ROOT / "dist").glob(f"DeskBridge-{VERSION}-*")
                   if path.is_file() and path.suffix in (".exe", ".zip", ".dmg", ".deb"))
if not artifacts:
    raise SystemExit("No release artifacts")
lines = []
for path in artifacts:
    if path.is_symlink():
        raise ValueError("Linked artifact")
    with path.open("rb") as stream:
        lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
suffix = "windows-x64" if sys.platform == "win32" else f"macos-{platform.machine()}" if sys.platform == "darwin" else "ubuntu-26.04-amd64"
output = ROOT / "dist" / f"SHA256SUMS-{VERSION}-{suffix}.txt"
output.write_text("".join(lines), encoding="ascii")
print(output.name)
