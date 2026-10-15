"""Package explicit delivery directories; never include private runtime profiles."""
from pathlib import Path
import hashlib
import shutil
import zipfile
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge import __version__ as VERSION
app = ROOT / "dist" / VERSION / "DeskBridge"
if not (app / "DeskBridge.exe").is_file():
    raise SystemExit("Build the Windows executable before packaging.")
for directory in ("docs", "third_party"):
    shutil.copytree(ROOT/directory, app/directory, dirs_exist_ok=True)
for name in ("README.md", "THIRD_PARTY_NOTICES.md", "LICENSE"):
    shutil.copy2(ROOT/name, app/name)


def archive(target, pairs):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path, member in pairs:
            if path.is_symlink() or path.suffix.lower() == ".pem":
                raise ValueError("Refusing a linked file or private runtime identity")
            stream.write(path, member)
    with zipfile.ZipFile(target) as stream:
        if stream.testzip() is not None:
            raise ValueError("Archive verification failed")
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(target.name, target.stat().st_size, digest)
    return f"{digest}  {target.name}\n"


native = ROOT/"dist"/f"DeskBridge-{VERSION}-windows-x64-portable.zip"
checksum = archive(native, [(p, Path("DeskBridge")/p.relative_to(app)) for p in app.rglob("*") if p.is_file()])
sources = [p for p in ROOT.iterdir() if p.is_file() and p.suffix in (".py", ".md", ".txt", ".lock", ".ps1")]
sources.append(ROOT/"LICENSE")
sources.append(ROOT/".gitignore")
sources.append(ROOT/".gitattributes")
sources.extend(p for directory in ("deskbridge", "tests", "tools", "docs", "third_party", "service", "assets", "packaging", ".github")
               if (ROOT/directory).is_dir()
               for p in (ROOT/directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
source = ROOT/"dist"/f"DeskBridge-{VERSION}-source.zip"
checksum += archive(source, [(p, Path("deskbridge")/p.relative_to(ROOT)) for p in sources])
(ROOT/"dist"/f"SHA256SUMS-{VERSION}.txt").write_text(checksum, encoding="ascii")
