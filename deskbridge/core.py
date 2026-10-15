from __future__ import annotations

import os
import copy
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

from .identity import Identity
from .model import Workspace
from .storage import Profile, atomic_write
from .mailbox import EventMailbox
from .process_env import run_external, spawn_external, external_environment

ENGINE_VERSION = "1.27.0"
PROJECT = Path(__file__).resolve().parent.parent


def os_name() -> str:
    return "Windows" if sys.platform == "win32" else "macOS" if sys.platform == "darwin" else "Ubuntu"


def find_engine() -> str:
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            candidates = sorted((Path(sys.executable).parent / "engine").glob("*/deskflow-core.exe"))
            if candidates:
                return str(candidates[0])
        candidates = list((PROJECT / "vendor" / "deskflow").glob("*/deskflow-core.exe"))
        if candidates:
            return str(sorted(candidates)[0])
    if sys.platform == "darwin":
        if getattr(sys, "frozen", False):
            bundled = Path(sys.executable).parent.parent / "Resources/engine/Deskflow.app/Contents/MacOS/deskflow-core"
            if bundled.is_file():
                return str(bundled)
        for path in (Path("/Applications/Deskflow.app/Contents/MacOS/deskflow-core"),
                     Path.home()/"Applications/Deskflow.app/Contents/MacOS/deskflow-core",
                     Path("/opt/homebrew/bin/deskflow-core"), Path("/usr/local/bin/deskflow-core")):
            if path.is_file():
                return str(path)
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "engine/deskflow-core"
        if bundled.is_file():
            return str(bundled)
    return shutil.which("deskflow-core") or ""


def check_engine(value: str) -> Path:
    if not value:
        hint = "请先将官方 Deskflow 1.27.0 安装到 Applications，再选择 Deskflow.app 内的 deskflow-core。" if sys.platform == "darwin" else "请选择官方 Deskflow 1.27.0 的 deskflow-core 程序。"
        raise ValueError("尚未找到输入核心。" + hint)
    if sys.platform == "darwin" and Path(value).suffix.lower() == ".app":
        value = str(Path(value)/"Contents/MacOS/deskflow-core")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or path.name.lower() not in ("deskflow-core", "deskflow-core.exe"):
        raise ValueError("请选择 deskflow-core 程序本身。")
    if sys.platform == "win32" and not (path.parent / "settings" / "Deskflow.conf").is_file():
        raise ValueError("Windows 必须使用官方 portable 包，以保证信任库留在本应用配置目录。")
    env = external_environment()
    # The version probe must work without requesting input permissions.
    if sys.platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        env["QT_QPA_PLATFORM"] = "offscreen"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = run_external([str(path), "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                              env=env, cwd=str(path.parent), creationflags=flags, check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"输入核心无法加载（退出码 0x{exc.returncode & 0xFFFFFFFF:08X}）。请使用完整的新便携包，不要混拷旧版 DLL。") from None
    except subprocess.TimeoutExpired:
        raise ValueError("输入核心版本检查超时；请使用完整便携包并检查核心运行库。") from None
    text = result.stdout.decode("utf-8", errors="replace")
    if not re.search(r"\bv1\.27\.0(?:,|\s|$)", text):
        raise ValueError(f"仅支持已检查配置契约的 Deskflow {ENGINE_VERSION}；请勿混用其他版本。")
    return path


def qvalue(value: str) -> str:
    if any(ord(c) < 32 for c in value):
        raise ValueError("配置值不能包含控制字符。")
    # QSettings uses UTF-8 quoted values. Forward slashes avoid Windows escapes.
    return '"' + value.replace("\\", "/").replace('"', '\\"') + '"'


def prepare(profile: Profile, workspace: Workspace, identity: Identity) -> Path:
    workspace.validate(ready=True)
    local_fingerprint = identity.ensure()
    if any(d.name != workspace.local_name and d.fingerprint == local_fingerprint for d in workspace.devices):
        raise ValueError("其他电脑不能使用本机身份。请只复制公开指纹，不能复制私钥或整个配置目录。")
    server = workspace.local_name if workspace.mode == "server" else workspace.server_name
    peers = [d for d in workspace.devices if d.name != workspace.local_name]
    servers = [d for d in peers if d.name == server]
    for filename, trusted in (("trusted-clients", peers if workspace.mode == "server" else []),
                              ("trusted-servers", servers)):
        content = "".join(f"v2:sha256:{d.fingerprint}\n" for d in trusted)
        atomic_write(profile.tls / filename, content.encode("ascii"))
    config_file = profile.root / "server.conf"
    atomic_write(config_file, workspace.server_config().encode("utf-8"))
    settings = (
        f"[core]\ncomputerName={qvalue(workspace.local_name)}\nport={workspace.port}\n"
        f"interface={qvalue(workspace.address if workspace.mode == 'server' else '')}\n"
        "processMode=1\nuseHooks=true\nenableEnterCommand=false\nenableExitCommand=false\n"
        f"[client]\nremoteHost={qvalue(workspace.address)}\nlanguageSync=true\n"
        "[security]\ntlsEnabled=true\ncheckPeerFingerprints=true\nkeySize=3072\n"
        f"certificate={qvalue(identity.path.as_posix())}\n"
        f"[server]\nexternalConfig=true\nexternalConfigFile={qvalue(config_file.as_posix())}\n"
        f"protocol=barrier\nenableClipboard={'true' if workspace.clipboard else 'false'}\nclipboardSize=1024\n"
        "enableHeartbeat=true\nheartbeat=5000\nenableSwitchDelay=true\nswitchDelay=150\n"
        "[log]\nlevel=INFO\ntoFile=false\n[gui]\nenableUpdateCheck=false\n"
    )
    settings += "".join(f"[computer_{d.name}]\nname={qvalue(d.name)}\n" for d in workspace.devices)
    settings_file = profile.root / "engine.ini"
    atomic_write(settings_file, settings.encode("utf-8"))
    return settings_file


class CoreProcess:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.events = EventMailbox()
        self._thread: threading.Thread | None = None
        self._guard = threading.RLock()
        self._job = None
        self._network_stop = threading.Event()
        self._network_thread = None
        self._discovery = None
        self._owns_discovery = False
        self._reconnecting = False
        self._restarting_pid = None

    @staticmethod
    def runtime_workspace(workspace, discovery, timeout=0):
        runtime = copy.deepcopy(workspace)
        if workspace.automatic_network:
            runtime.automatic_network = False
            if workspace.mode == "server":
                runtime.address = "0.0.0.0"
            else:
                peer = next(d for d in workspace.devices if d.name == workspace.server_name)
                endpoint = discovery.resolve(peer.fingerprint, peer.name, timeout=timeout)
                if not endpoint:
                    reason = discovery.explain_missing(peer.fingerprint, peer.name)
                    raise ValueError(reason if isinstance(reason, str) else f"无法自动寻址已配对的 {peer.name}。请检查对端共享状态和电脑名解析。")
                runtime.address, runtime.port = endpoint
        runtime.validate(ready=True)
        return runtime

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def emit(self, kind: str, message: str) -> None:
        self.events.put_nowait((kind, message[:4096]))

    def start(self, profile: Profile, workspace: Workspace, identity: Identity, discovery=None) -> None:
        workspace = copy.deepcopy(workspace)
        workspace.select_single_server()
        if not self.running and self._network_thread and self._network_thread.is_alive():
            self._network_stop.set()
            self._network_thread.join(timeout=2)
        with self._guard:
            if self.running:
                raise ValueError("共享已经运行，请先停止再修改设置。")
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
                if self._thread.is_alive():
                    raise ValueError("上一个输入核心仍在退出，请稍后再试。")
            workspace.validate(ready=True)
            engine = check_engine(workspace.engine)
            identity.ensure()
            self._network_stop.clear()
            self._discovery, self._owns_discovery = discovery, False
            if workspace.automatic_network and self._discovery is None:
                from .discovery import LanDiscovery
                self._discovery = LanDiscovery(workspace.local_name, os_name(), identity.fingerprint(), workspace.port, workspace.mode)
                self._owns_discovery = True
            try:
                runtime = self.runtime_workspace(workspace, self._discovery, timeout=8)
                self._spawn(profile, runtime, identity, engine)
            except Exception:
                if self._owns_discovery:
                    self._discovery.close()
                    self._owns_discovery = False
                raise
            if workspace.automatic_network and workspace.mode == "client":
                endpoint = (runtime.address, runtime.port)
                self._network_thread = threading.Thread(target=self._follow_address,
                                                       args=(profile, copy.deepcopy(workspace), identity, engine, endpoint), daemon=True)
                self._network_thread.start()

    def _spawn(self, profile, workspace, identity, engine):
        settings = prepare(profile, workspace, identity)
        # Default single-instance protection remains enabled in the engine.
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = spawn_external([str(engine), workspace.mode, "--settings", str(settings)],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        cwd=str(engine.parent), creationflags=flags)
        if os.name == "nt":
            from .windows_job import ChildJob
            try:
                self._job = ChildJob(self.process)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=2)
                self.process.stdout.close()
                raise
        self.emit("status", "输入核心已启动；正在等待已配对的设备。")
        self._thread = threading.Thread(target=self._read, args=(self.process,), daemon=True)
        self._thread.start()

    def _follow_address(self, profile, workspace, identity, engine, endpoint):
        while not self._network_stop.wait(3):
            try:
                runtime = self.runtime_workspace(workspace, self._discovery)
            except ValueError:
                continue
            updated = (runtime.address, runtime.port)
            if updated == endpoint:
                continue
            with self._guard:
                if self._network_stop.is_set() or not self.running:
                    return
                self._reconnecting = True
                self._restarting_pid = self.process.pid
                try:
                    self.emit("status", "网络地址已更新，正在重新连接已配对电脑…")
                    self._stop_child()
                    self._spawn(profile, runtime, identity, engine)
                    endpoint = updated
                except Exception as exc:
                    self._network_stop.set()
                    self.emit("exit", f"自动重连失败：{exc}")
                    return
                finally:
                    self._reconnecting = False
                    self._restarting_pid = None

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            while line := proc.stdout.readline(4096):
                text = line.decode("utf-8", errors="replace").strip()
                self.emit("log", text)
                lower = text.lower()
                if "connected to server" in lower or "client" in lower and "has connected" in lower:
                    self.emit("status", "设备已连接；可以移动鼠标跨越布局边缘。")
                elif "started server" in lower:
                    self.emit("status", "共享端正在监听；等待已配对设备连接。")
                elif "disconnected" in lower or "connection failed" in lower or "failed to connect" in lower:
                    self.emit("status", "连接断开或失败，请检查双方指纹、权限和网络。")
                elif "failed" in lower or "error" in lower or "critical" in lower:
                    self.emit("status", "核心报告问题，请查看运行日志。")
        finally:
            code = proc.wait()
            proc.stdout.close()
            if self._job:
                self._job.close()
                self._job = None
            if proc.pid != self._restarting_pid:
                self._network_stop.set()
                self.emit("exit", f"输入核心已退出（代码 {code}）。")

    def stop(self) -> None:
        self._network_stop.set()
        with self._guard:
            self._stop_child()
        if self._network_thread and self._network_thread is not threading.current_thread():
            self._network_thread.join(timeout=2)
        if self._owns_discovery and self._discovery:
            self._discovery.close()
            self._owns_discovery = False

    def _stop_child(self):
        proc = self.process
        if proc is None or proc.poll() is not None:
            return
        # POSIX SIGTERM follows the core's signal handler. Windows termination
        # is a bounded fallback; peers detect the closed socket and leave.
        if os.name != "nt" or not self._graceful_windows_stop(proc):
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    @staticmethod
    def _graceful_windows_stop(proc) -> bool:
        """Address upstream IPC only after checking its OS server PID is ours."""
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        api.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateFileW(r"\\.\pipe\Deskflow-core", 0x40000000, 0, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            return False
        try:
            pid = wintypes.ULONG()
            if not api.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)) or pid.value != proc.pid:
                return False
            written = wintypes.DWORD()
            return bool(api.WriteFile(handle, b"stop\n", 5, ctypes.byref(written), None)) and written.value == 5
        finally:
            api.CloseHandle(handle)


def environment_description() -> str:
    if sys.platform == "darwin":
        return "macOS：请在系统设置授予 Deskflow Core 辅助功能和输入监控权限。"
    if sys.platform.startswith("linux"):
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            return "Ubuntu / Wayland：须由 GNOME 或 KDE 的 portal 授权；支持取决于 libei/libportal，剪贴板可能不可用。"
        return "Ubuntu / Xorg：在本机图形桌面运行；需要可用的 DISPLAY 与 XTest。"
    return "Windows：普通用户运行；UAC 安全桌面及更高权限窗口不在首版支持范围。"
