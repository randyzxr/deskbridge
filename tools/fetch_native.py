"""Download only fixed official release artifacts and verify their digest."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import os
import platform
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile

from installers import NATIVE, ROOT, verify


def build_directory(path):
    if not path.absolute().is_relative_to(ROOT):
        raise ValueError("Build directory must stay in this workspace")
    for part in (path, *path.parents):
        if part == ROOT.parent:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Linked build directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_windows(archive):
    destination = build_directory(ROOT / "vendor/deskflow")
    with zipfile.ZipFile(archive) as stream:
        members = stream.infolist()
        if len(members) > 5000 or sum(item.file_size for item in members) > 256 * 1024 * 1024:
            raise ValueError("Native archive exceeds the extraction limits")
        for item in members:
            member = PurePosixPath(item.filename.replace("\\", "/"))
            mode = item.external_attr >> 16
            if (member.is_absolute() or not member.parts or ".." in member.parts
                    or any(":" in part for part in member.parts)
                    or member.parts[0] != "deskflow-1.27.0-win-x64-portable"
                    or stat.S_ISLNK(mode) or item.file_size > 64 * 1024 * 1024):
                raise ValueError("Invalid native archive member")
            target = destination.joinpath(*member.parts)
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Linked extraction target")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                build_directory(target.parent)
                with stream.open(item) as source, target.open("wb") as output:
                    # The zip reader enforces the declared size and CRC.
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        output.write(block)


def main():
    architecture = platform.machine().lower()
    if sys.platform == "win32" and architecture in ("amd64", "x86_64"):
        name = "deskflow-1.27.0-win-x64-portable.zip"
    elif sys.platform == "darwin" and architecture in ("arm64", "x86_64"):
        name = f"deskflow-1.27.0-macos-{architecture}.dmg"
    elif sys.platform.startswith("linux") and architecture == "x86_64":
        name = "deskflow-1.27.0-ubuntu-resolute-x86_64.deb"
    else:
        raise SystemExit("Unsupported build platform/architecture")
    cache = build_directory(ROOT / "vendor/cache")
    target = cache / name
    if target.exists():
        verify(target)
    else:
        # No user-controlled URLs; name must be a member of the fixed manifest.
        assert name in NATIVE
        url = "https://github.com/deskflow/deskflow/releases/download/v1.27.0/" + name
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=cache, prefix="download-", delete=False) as output:
                temporary = Path(output.name)
                digest = hashlib.sha256()
                limit, started = 0, time.monotonic()
                with urllib.request.urlopen(url, timeout=30) as response:
                    while block := response.read(1024 * 1024):
                        limit += len(block)
                        if limit > 128 * 1024 * 1024 or time.monotonic() - started > 180:
                            raise ValueError("Native download exceeds size/time limit")
                        digest.update(block)
                        output.write(block)
            if digest.hexdigest() != NATIVE[name]:
                raise ValueError("Native download SHA-256 mismatch")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if sys.platform == "win32":
        extract_windows(target)
    print(target)


if __name__ == "__main__":
    main()
