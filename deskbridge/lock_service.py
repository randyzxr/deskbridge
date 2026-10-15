"""Export a private, receiver-only snapshot for an administrator-installed service."""
from __future__ import annotations
import json
import os
import re
import copy
import csv
import subprocess
from pathlib import Path
from .storage import private_directory, atomic_write


def receiver_service_installed():
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes as w
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.OpenSCManagerW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
    api.OpenSCManagerW.restype = w.HANDLE
    api.OpenServiceW.argtypes = [w.HANDLE, w.LPCWSTR, w.DWORD]
    api.OpenServiceW.restype = w.HANDLE
    api.CloseServiceHandle.argtypes = [w.HANDLE]
    manager = api.OpenSCManagerW(None, None, 1)
    if not manager:
        raise ValueError("无法查询锁屏服务，请由管理员检查服务权限。")
    try:
        service = api.OpenServiceW(manager, "DeskBridgeLockReceiver", 4)
        if not service:
            if ctypes.get_last_error() == 1060:
                return False
            raise ValueError("锁屏服务存在或无法读取；请管理员检查，不能同时运行普通接收核心。")
        api.CloseServiceHandle(service)
        return True
    finally:
        api.CloseServiceHandle(manager)


def current_owner_sid():
    if os.name != "nt":
        raise ValueError("锁屏服务安装配置仅适用于 Windows 接收端。")
    program = Path(os.environ.get("SystemRoot", r"C:\Windows"))/"System32/whoami.exe"
    result = subprocess.run([str(program), "/user", "/fo", "csv", "/nh"], capture_output=True, check=True, timeout=5)
    return next(csv.reader(result.stdout.decode(errors="replace").splitlines()))[-1].strip()


def export_receiver(profile, workspace, identity, owner_sid):
    value = copy.deepcopy(workspace)
    value.select_single_server()
    value.validate(ready=True)
    if value.mode != "client":
        raise ValueError("锁屏服务当前仅支持 Windows 接收端，请选择接收键鼠并指定已配对共享端。")
    if not re.fullmatch(r"S-1-5-(?:[0-9]+-)*[0-9]+", owner_sid):
        raise ValueError("无法确认服务所属用户。")
    peer = next(d for d in value.devices if d.name == value.server_name)
    own = identity.ensure()
    if peer.fingerprint == own:
        raise ValueError("共享端不能使用本机身份。")
    target = private_directory(profile.root/"lock-service")
    if os.name == "nt":
        from .windows_acl import secure_path
        secure_path(target, owner_sid)
    data = {"schema": 1, "owner_sid": owner_sid, "local_name": value.local_name,
            "server_name": peer.name, "server_fp": peer.fingerprint, "local_fp": own, "port": value.port}
    atomic_write(target/"service.json", json.dumps(data, ensure_ascii=True, indent=2).encode("ascii"))
    atomic_write(target/"deskbridge.pem", identity.path.read_bytes())
    return target
