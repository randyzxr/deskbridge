from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import sys

from .core import CoreProcess, check_engine, environment_description, find_engine, os_name, prepare
from .identity import Identity
from .storage import Profile


def default_profile() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DeskBridge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DeskBridge"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "deskbridge"


def main() -> None:
    parser = argparse.ArgumentParser(description="DeskBridge：局域网跨平台键鼠共享")
    parser.add_argument("--profile", type=Path, default=default_profile(), help="独立配置目录；每台电脑必须自行生成身份")
    parser.add_argument("--engine", help="官方 Deskflow 1.27.0 核心路径")
    parser.add_argument("--doctor", action="store_true", help="检查核心与运行环境，不捕获输入")
    parser.add_argument("--fingerprint", action="store_true", help="生成/显示本机公开指纹")
    parser.add_argument("--prepare", action="store_true", help="验证并生成核心设置，不启动输入共享")
    parser.add_argument("--run", action="store_true", help="使用已保存配置启动核心；Ctrl+C 停止")
    parser.add_argument("--export-lock-service", action="store_true", help="导出 Windows 接收端锁屏服务私有配置；安装须由管理员执行")
    args = parser.parse_args()
    profile = None
    core = None
    try:
        if args.doctor:
            print(environment_description())
            print("输入核心:", check_engine(args.engine or find_engine()))
            print("版本与便携目录检查通过；系统输入权限需在启动时授权。")
            return
        profile = Profile(args.profile)
        profile.acquire()
        workspace = profile.load(os_name())
        if args.engine:
            workspace.engine = args.engine
        elif not workspace.engine:
            workspace.engine = find_engine()
        identity = Identity(profile.tls)
        if args.fingerprint:
            print(identity.ensure())
        elif args.prepare:
            check_engine(workspace.engine)
            print(prepare(profile, workspace, identity))
        elif args.export_lock_service:
            from .lock_service import current_owner_sid, export_receiver
            print(export_receiver(profile, workspace, identity, current_owner_sid()))
        elif args.run:
            from .lock_service import receiver_service_installed
            if receiver_service_installed():
                raise ValueError("锁屏服务已安装；请通过 SCM 控制该服务，不能同时运行普通接收核心。")
            core = CoreProcess()
            core.start(profile, workspace, identity)
            while core.running or not core.events.empty():
                try:
                    _, text = core.events.get(timeout=.2)
                    print(text)
                except queue.Empty:
                    pass
            if core.process and core.process.returncode:
                raise SystemExit(core.process.returncode)
        else:
            from .gui import run_gui
            run_gui(profile, workspace)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if not any((args.doctor, args.fingerprint, args.prepare, args.run, args.export_lock_service)):
            try:
                # A frozen windowed executable has no console for startup errors.
                from .gui import tk, messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("DeskBridge 无法启动", str(exc), parent=root)
                root.destroy()
            except Exception:
                pass
        if sys.stderr is not None:
            print(f"DeskBridge: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if core:
            core.stop()
        if profile:
            profile.close()
