"""Build with PyInstaller's dependency hooks; keep native libraries isolated."""
from pathlib import Path
import os
import subprocess
import sys
import shutil
import hashlib
import json
from importlib.util import spec_from_file_location, module_from_spec

root = Path(__file__).resolve().parent.parent
version_spec = spec_from_file_location("deskbridge_version", root/"deskbridge/__init__.py")
version_module = module_from_spec(version_spec)
version_spec.loader.exec_module(version_module)
version = version_module.__version__
subprocess.run([sys.executable, str(root / "tools/make_icons.py")], cwd=root, check=True)
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
           "--noupx", "--name", "DeskBridge", "--distpath", f"dist/{version}",
           "--specpath", "build/spec", "--collect-submodules", "zeroconf",
           "--copy-metadata", "zeroconf", "--copy-metadata", "ifaddr", "--add-data", f"{root/'LICENSE'}:.",
           "--add-data", f"{root/'THIRD_PARTY_NOTICES.md'}:.",
           "--add-data", f"{root/'assets'}:assets", str(root/"app.py")]
if sys.platform == "darwin":
    command.extend(["--osx-bundle-identifier", "org.deskbridge.app", "--icon", str(root / "assets/deskbridge.icns")])
if sys.platform == "win32":
    command.extend(["--icon", str(root / "assets/deskbridge.ico")])
    source = root/"vendor"/"deskflow"
    if not list(source.glob("*/deskflow-core.exe")):
        raise SystemExit("Place the verified official Windows portable core under vendor/deskflow first.")
    # Do not let bindepend mix the standalone Qt/ICU libraries into Python.
    tcl = root / "vendor" / "tcl"
    if (tcl / "tcl8.6" / "init.tcl").is_file():
        os.environ["TCL_LIBRARY"] = str(tcl / "tcl8.6")
        os.environ["TK_LIBRARY"] = str(tcl / "tk8.6")
        # PyInstaller's Tk hook already places the required scripts in
        # _tcl_data and _tk_data. A second vendor/tcl tree duplicates them.
subprocess.run(command, cwd=root, check=True)
if sys.platform == "win32":
    destination = root / "dist" / version / "DeskBridge" / "engine"
    # The controller never launches Deskflow's separate GUI, its translations,
    # SVG/image loaders or style plugins. Keep the native core, all non-SVG DLLs,
    # platform/network/TLS plugins, portable marker, documentation and licenses.
    inventory = {}
    omitted = []
    for original in sorted(source.rglob("*")):
        if not original.is_file():
            continue
        if original.is_symlink():
            raise SystemExit("Linked engine inputs are not allowed")
        relative = original.relative_to(source)
        member = relative.parts[1:]
        keep = (len(member) == 1 and original.name != "deskflow.exe" and original.name != "Qt6Svg.dll"
                or len(member) > 1 and member[0] in ("settings", "docs")
                or len(member) > 2 and member[0] == "plugins" and member[1] in ("platforms", "networkinformation", "tls"))
        if not keep:
            omitted.append(relative.as_posix())
            continue
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copied)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        if digest != hashlib.sha256(copied.read_bytes()).hexdigest():
            raise SystemExit(f"Standalone engine copy mismatch: {original.name}")
        inventory[relative.as_posix()] = digest
    # Record exactly what was selected; no existing vendor binary is changed.
    (destination.parent / "engine-inventory.json").write_text(
        json.dumps({"files": inventory, "omitted": omitted}, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, str(root/"tools/build_service.py")], cwd=root, check=True)
