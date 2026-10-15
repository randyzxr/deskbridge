"""Launch a separate native program without inheriting frozen Python libraries."""
from __future__ import annotations

import os
import subprocess
import sys
import threading

_launch_lock = threading.RLock()


def external_environment() -> dict[str, str]:
    env = os.environ.copy()
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))
        def outside(value):
            if not value:
                return False
            path = os.path.normcase(os.path.abspath(value))
            return path != root and not path.startswith(root + os.sep)
        for key in ("PATH", "DYLD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            if key in env:
                env[key] = os.pathsep.join(p for p in env[key].split(os.pathsep) if outside(p))
        if sys.platform.startswith("linux"):
            original = env.pop("LD_LIBRARY_PATH_ORIG", "")
            env["LD_LIBRARY_PATH"] = os.pathsep.join(p for p in original.split(os.pathsep) if outside(p))
        # Python/crypto runtime hooks must not select the native core's providers.
        for key in ("OPENSSL_MODULES", "OPENSSL_CONF"):
            if key in env and not outside(env[key]):
                env.pop(key)
    return env


def spawn_external(arguments, **kwargs) -> subprocess.Popen:
    kwargs.setdefault("env", external_environment())
    if os.name != "nt":
        return subprocess.Popen(arguments, **kwargs)
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    api.GetDllDirectoryW.restype = wintypes.DWORD
    api.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    api.GetErrorMode.restype = wintypes.UINT
    api.SetErrorMode.argtypes = [wintypes.UINT]
    api.SetErrorMode.restype = wintypes.UINT
    with _launch_lock:
        buffer = ctypes.create_unicode_buffer(32768)
        size = api.GetDllDirectoryW(len(buffer), buffer)
        if size >= len(buffer):
            raise OSError("DLL search directory exceeds the supported path length")
        previous_directory = buffer.value if size else None
        previous_errors = api.GetErrorMode()
        if not api.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        child = None
        try:
            # Inherited by this child only; loader failures return an exit code.
            api.SetErrorMode(previous_errors | 0x8003)
            child = subprocess.Popen(arguments, **kwargs)
            return child
        finally:
            api.SetErrorMode(previous_errors)
            if not api.SetDllDirectoryW(previous_directory):
                if child is not None:
                    child.kill()
                    child.wait(timeout=3)
                raise ctypes.WinError(ctypes.get_last_error())


def run_external(arguments, *, timeout, check=False, **kwargs):
    proc = spawn_external(arguments, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    result = subprocess.CompletedProcess(arguments, proc.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
