"""Owned core only: restricted-token IPC access and real TLS regression."""
from pathlib import Path
import ctypes
from ctypes import wintypes as W
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import integration_core
from deskbridge.core import CoreProcess


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", W.DWORD)]


def restricted_access(pid):
    kernel, adv = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.GetNamedPipeServerProcessId.argtypes = [W.HANDLE,ctypes.POINTER(W.DWORD)]
    adv.OpenProcessToken.argtypes = [W.HANDLE,W.DWORD,ctypes.POINTER(W.HANDLE)]
    adv.ConvertStringSidToSidW.argtypes = [W.LPCWSTR,ctypes.POINTER(ctypes.c_void_p)]
    adv.CreateRestrictedToken.argtypes = [W.HANDLE,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.POINTER(SID_AND_ATTRIBUTES),ctypes.POINTER(W.HANDLE)]
    adv.ImpersonateLoggedOnUser.argtypes = [W.HANDLE]
    pipe_name = r"\\.\pipe\Deskflow-core"
    invalid = ctypes.c_void_p(-1).value
    deadline = time.monotonic()+8
    while True:
        handle = kernel.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
        if handle != invalid:
            try:
                server = W.DWORD()
                assert kernel.GetNamedPipeServerProcessId(handle,ctypes.byref(server)) and server.value == pid, "Foreign core pipe; test refused"
            finally: kernel.CloseHandle(handle)
            break
        if time.monotonic() >= deadline: raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(.1)
    token, restricted, everyone = W.HANDLE(), W.HANDLE(), ctypes.c_void_p()
    impersonated = False
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008|0x0002, ctypes.byref(token)): raise ctypes.WinError(ctypes.get_last_error())
        if not adv.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(everyone)): raise ctypes.WinError(ctypes.get_last_error())
        entry = SID_AND_ATTRIBUTES(everyone,4)
        if not adv.CreateRestrictedToken(token,0,0,None,0,None,1,ctypes.byref(entry),ctypes.byref(restricted)): raise ctypes.WinError(ctypes.get_last_error())
        if not adv.ImpersonateLoggedOnUser(restricted): raise ctypes.WinError(ctypes.get_last_error())
        impersonated = True
        handle = kernel.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
        code = ctypes.get_last_error()
        if handle != invalid:
            try:
                server = W.DWORD()
                assert kernel.GetNamedPipeServerProcessId(handle,ctypes.byref(server)) and server.value == pid, "Foreign core pipe; test refused"
            finally: kernel.CloseHandle(handle)
            return True
        assert code == 5, f"Expected access denied, got {code}"
        return False
    finally:
        if impersonated and not adv.RevertToSelf(): raise ctypes.WinError(ctypes.get_last_error())
        if restricted: kernel.CloseHandle(restricted)
        if token: kernel.CloseHandle(token)
        if everyone: kernel.LocalFree(everyone)


def run(app):
    app = Path(app).resolve(strict=True)
    original = CoreProcess._spawn
    # Preserve single-instance protection and any existing user's input session.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateFileW(r"\\.\pipe\Deskflow-core",0xC0000000,0,None,3,0,None)
    if handle != ctypes.c_void_p(-1).value:
        kernel.CloseHandle(handle)
        print("SKIP: existing core is running; stop ordinary sharing before IPC/TLS regression")
        return
    def probe(expected):
        def spawn(self, *args):
            original(self,*args)
            assert restricted_access(self.process.pid) == expected
        return spawn
    with tempfile.TemporaryDirectory(prefix="private-ipc-",dir=Path(__file__).resolve().parent.parent/"build") as folder:
        engine = Path(folder)/"engine"
        shutil.copytree(app/"engine/deskflow-1.27.0-win-x64-portable",engine)
        for source, expected in ((app/"engine/deskflow-1.27.0-win-x64-portable/deskflow-core.exe", True), (app/"service/deskflow-core.exe", False)):
            data = source.read_bytes()
            (engine/"deskflow-core.exe").write_bytes(data)
            with patch.object(CoreProcess,"_spawn",probe(expected)), patch.object(integration_core,"find_engine",return_value=str(engine/"deskflow-core.exe")):
                integration_core.run()
    print("PASS: original IPC permits restricted Everyone token; private service core denies it; owner access and TLS allow/reject/revoke preserved")


if __name__ == "__main__": run(sys.argv[1])
