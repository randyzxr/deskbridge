"""Create native installers on their target OS from verified upstream inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskbridge import __version__ as VERSION

NATIVE = {
    "deskflow-1.27.0-win-x64-portable.zip": "8d19004cc3625623489d96580c1b58fd13ee78185689907fd4478595f93fab9a",
    "deskflow-1.27.0-macos-arm64.dmg": "dd21e79e566314394214906d3338c505d337af536fc580c022ee3fadffad0c97",
    "deskflow-1.27.0-macos-x86_64.dmg": "8aca3c77a1b16b9a3d6b8a380e5e38a0e6abf6d241bb32dcf3cf8b67abbff5d8",
    "deskflow-1.27.0-ubuntu-resolute-x86_64.deb": "b8972871a0a1d9958968696bceafb28571ad50d17b2d35ae8149a95a28fd7fa3",
}


def verify(path):
    path = Path(path).resolve(strict=True)
    expected = NATIVE.get(path.name)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected is None or digest != expected:
        raise ValueError("Unknown or corrupt upstream package")
    return path


def docs(destination):
    for directory in ("docs", "third_party"):
        shutil.copytree(ROOT / directory, destination / directory, dirs_exist_ok=True)
    for name in ("README.md", "THIRD_PARTY_NOTICES.md", "LICENSE"):
        shutil.copy2(ROOT / name, destination / name)


def windows(compiler):
    app = ROOT / "dist" / VERSION / "DeskBridge"
    if not (app / "DeskBridge.exe").is_file():
        raise ValueError("Build the application first")
    docs(app)
    compiler = compiler or shutil.which("ISCC")
    if not compiler:
        raise ValueError("Install the verified official Inno Setup compiler, or pass --iscc")
    subprocess.run([str(compiler), "/Qp", f"/DAppVersion={VERSION}", f"/DProjectRoot={ROOT}",
                    str(ROOT / "packaging/windows.iss")], cwd=ROOT, check=True)


def macos(native):
    architecture = platform.machine()
    expected = f"deskflow-1.27.0-macos-{architecture}.dmg"
    native = verify(native)
    if native.name != expected:
        raise ValueError("The DMG architecture must match this build host")
    app = ROOT / "dist" / VERSION / "DeskBridge.app"
    if not app.is_dir():
        raise ValueError("Build the macOS .app on this Mac first")
    resources = app / "Contents/Resources"
    docs(resources)
    with tempfile.TemporaryDirectory(prefix="deskbridge-mount-", dir=ROOT / "build") as name:
        mount = Path(name)
        attached = False
        try:
            # The official image presents its GPL license before mounting. Keep
            # the upstream license in the distribution and provide the explicit
            # affirmative response for this authorized, read-only build mount.
            subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(native)],
                           input="Y\n", text=True, check=True)
            attached = True
            source = mount / "Deskflow.app"
            if not (source / "Contents/MacOS/deskflow-core").is_file():
                raise ValueError("Official DMG is missing deskflow-core")
            destination = resources / "engine/Deskflow.app"
            if destination.exists():
                raise ValueError("Rebuild a fresh .app before packaging again")
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Preserve framework symlinks and the upstream app's own layout.
            shutil.copytree(source, destination, symlinks=True)
            native_info = plistlib.loads((source / "Contents/Info.plist").read_bytes())
        finally:
            if attached:
                subprocess.run(["hdiutil", "detach", str(mount)], check=True)
    info = app / "Contents/Info.plist"
    data = plistlib.loads(info.read_bytes())
    data.update({"CFBundleIdentifier": "org.deskbridge.app", "CFBundleShortVersionString": VERSION,
                 "CFBundleVersion": VERSION,
                 "NSHighResolutionCapable": True,
                 "NSLocalNetworkUsageDescription": "Discover your paired computers for keyboard and mouse sharing."})
    minimum = native_info.get("LSMinimumSystemVersion", "")
    if isinstance(minimum, str) and minimum:
        data["LSMinimumSystemVersion"] = minimum
    info.write_bytes(plistlib.dumps(data))
    # Local development signing only. Public releases need Developer ID signing
    # and Apple notarization in the publishing environment.
    subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", "org.deskbridge.app", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
    with tempfile.TemporaryDirectory(prefix="deskbridge-dmg-", dir=ROOT / "build") as name:
        stage = Path(name)
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        shutil.copy2(ROOT / "docs/quick-start.md", stage / "使用说明.md")
        target = ROOT / "dist" / f"DeskBridge-{VERSION}-macos-{architecture}.dmg"
        subprocess.run(["hdiutil", "create", "-ov", "-format", "UDZO", "-volname", "DeskBridge",
                        "-srcfolder", str(stage), str(target)], check=True)


def ubuntu(native):
    native = verify(native)
    if native.name != "deskflow-1.27.0-ubuntu-resolute-x86_64.deb" or platform.machine() != "x86_64":
        raise ValueError("This installer targets Ubuntu 26.04 amd64")
    app = ROOT / "dist" / VERSION / "DeskBridge"
    if not (app / "DeskBridge").is_file():
        raise ValueError("Build on Ubuntu 26.04 first")
    def field(name):
        return subprocess.check_output(["dpkg-deb", "-f", str(native), name], text=True).strip()
    if field("Package") != "deskflow" or field("Architecture") != "amd64":
        raise ValueError("Unexpected official Debian package metadata")
    # Reuse the full official library requirements, including Qt/Wayland.
    dependencies = field("Depends")
    if not dependencies or any(c in dependencies for c in "\r\n"):
        raise ValueError("Invalid upstream dependency field")
    with tempfile.TemporaryDirectory(prefix="deskbridge-deb-", dir=ROOT / "build") as name:
        stage = Path(name)
        upstream = stage / "upstream"
        package = stage / "package"
        subprocess.run(["dpkg-deb", "--extract", str(native), str(upstream)], check=True)
        core = upstream / "usr/bin/deskflow-core"
        if not core.is_file() or core.is_symlink():
            raise ValueError("Official package is missing its native core")
        target = package / "opt/deskbridge"
        shutil.copytree(app, target, symlinks=True)
        docs(target)
        (target / "engine").mkdir()
        shutil.copy2(core, target / "engine/deskflow-core")
        share = package / "usr/share"
        (share / "applications").mkdir(parents=True)
        (share / "applications/deskbridge.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=DeskBridge\nComment=Share keyboard and mouse on your LAN\n"
            "Exec=/opt/deskbridge/DeskBridge\nIcon=deskbridge\nTerminal=false\nCategories=Utility;Network;\n", encoding="utf-8")
        icons = share / "icons/hicolor/256x256/apps"
        icons.mkdir(parents=True)
        shutil.copy2(ROOT / "assets/deskbridge.png", icons / "deskbridge.png")
        original_docs = upstream / "usr/share/doc/deskflow"
        if original_docs.is_dir():
            shutil.copytree(original_docs, share / "doc/deskbridge/upstream", symlinks=True)
        metadata = package / "DEBIAN"
        metadata.mkdir()
        (metadata / "control").write_text(
            f"Package: deskbridge\nVersion: {VERSION}\nSection: net\nPriority: optional\nArchitecture: amd64\n"
            "Maintainer: DeskBridge Contributors <deskbridge@users.noreply.github.com>\n"
            f"Depends: {dependencies}\nDescription: Local keyboard and mouse sharing controller\n"
            " Includes the pinned Deskflow 1.27.0 core. Built for Ubuntu 26.04.\n", encoding="utf-8")
        for directory, folders, files in os.walk(package):
            os.chmod(directory, 0o755)
            for file in files:
                path = Path(directory) / file
                if not path.is_symlink():
                    os.chmod(path, 0o755 if os.access(path, os.X_OK) else 0o644)
        output = ROOT / "dist" / f"DeskBridge-{VERSION}-ubuntu-26.04-amd64.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z9", "--build", str(package), str(output)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc")
    parser.add_argument("--native", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32":
        windows(args.iscc)
    elif args.native is None:
        parser.error("--native must specify the verified official platform package")
    elif sys.platform == "darwin":
        macos(args.native)
    elif sys.platform.startswith("linux"):
        ubuntu(args.native)
    else:
        parser.error("Unsupported host OS")


if __name__ == "__main__":
    main()
