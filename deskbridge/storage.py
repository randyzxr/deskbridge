from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import subprocess
import csv

from .model import Workspace


def private_directory(path: Path) -> Path:
    path = path.absolute()
    # Reject links/reparse points before resolving the selected profile root.
    for part in [path, *path.parents]:
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("配置目录不能位于符号链接或目录联接内。")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path, 0o700)
    return path.resolve()


def safe_file(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("配置文件不能是符号链接或目录联接。")
    if path.exists() and not path.is_file():
        raise ValueError("配置文件路径不是普通文件。")


def atomic_write(path: Path, data: bytes) -> None:
    private_directory(path.parent)
    safe_file(path)
    fd, name = tempfile.mkstemp(prefix=".deskbridge-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Profile:
    def __init__(self, root: Path):
        if root.exists() and any(root.iterdir()) and not (root / ".deskbridge-profile").is_file():
            raise ValueError("请选择空目录或已有的 DeskBridge 配置目录，不能把其他工作目录用作配置目录。")
        self.root = private_directory(root)
        if os.name == "nt":
            system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            # Fixed programs and separate arguments; no command interpreter.
            result = subprocess.run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
                                    capture_output=True, timeout=5, check=True)
            sid = next(csv.reader(result.stdout.decode(errors="replace").splitlines()))[-1].strip()
            if not sid.startswith("S-1-5-") or not all(c.isdigit() or c in "S-" for c in sid):
                raise ValueError("无法确认本机用户身份，未创建私钥。")
            from .windows_acl import secure_path
            secure_path(self.root, sid)
            for relative in (".deskbridge-profile", ".lock", "workspace.json", "engine.ini", "server.conf",
                             "tls", "tls/deskbridge.pem", "tls/trusted-clients", "tls/trusted-servers"):
                path = self.root / relative
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise ValueError("配置路径不能包含链接。")
                if path.exists():
                    secure_path(path, sid)
        atomic_write(self.root / ".deskbridge-profile", b"DeskBridge profile v1\n")
        self.tls = private_directory(self.root / "tls")
        self._lock = None

    def acquire(self) -> None:
        """An OS lock prevents simultaneous GUI/CLI writers to this profile."""
        path = self.root / ".lock"
        safe_file(path)
        stream = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise ValueError("该配置目录已被另一个 DeskBridge 实例使用。") from None
        self._lock = stream

    def close(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def load(self, os_name: str) -> Workspace:
        path = self.root / "workspace.json"
        safe_file(path)
        if not path.exists():
            return Workspace.new(os_name)
        if path.stat().st_size > 65536:
            raise ValueError("配置文件超过 64 KiB。")
        return Workspace.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, workspace: Workspace) -> None:
        workspace.validate()
        atomic_write(self.root / "workspace.json", json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2).encode())
