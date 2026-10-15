"""Windows notification icon using OS APIs; no additional runtime dependency.

The message thread never calls Tk. Fixed actions are coalesced and consumed by
the application's existing Tk poll. Other desktops retain normal minimization.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading


class TrayIcon:
    def __init__(self):
        self.ready = False
        self._pending = set()
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.hwnd = None
        self.failure = ""

    def _action(self, action):
        with self._lock:
            self._pending.add(action)

    def actions(self):
        with self._lock:
            result = self._pending
            self._pending = set()
        return result

    def start(self):
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="DeskBridge tray", daemon=True)
        self._thread.start()
        self._started.wait(2)
        return self.ready

    def close(self):
        self._stop.set()
        if self.hwnd:
            import ctypes
            from ctypes import wintypes as w
            post = ctypes.WinDLL("user32", use_last_error=True).PostMessageW
            post.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
            post.restype = w.BOOL
            post(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _run(self):
        import ctypes as c
        from ctypes import wintypes as w
        user = c.WinDLL("user32", use_last_error=True)
        shell = c.WinDLL("shell32", use_last_error=True)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        result_type = c.c_ssize_t
        callback = c.WINFUNCTYPE(result_type, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WindowClass(c.Structure):
            _fields_ = [("style", w.UINT), ("proc", callback), ("class_extra", c.c_int),
                        ("window_extra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                        ("cursor", w.HANDLE), ("background", w.HBRUSH),
                        ("menu_name", w.LPCWSTR), ("class_name", w.LPCWSTR)]

        class Guid(c.Structure):
            _fields_ = [("a", w.DWORD), ("b", w.WORD), ("c", w.WORD), ("d", c.c_byte * 8)]

        class IconData(c.Structure):
            _fields_ = [("size", w.DWORD), ("window", w.HWND), ("identifier", w.UINT),
                        ("flags", w.UINT), ("message", w.UINT), ("icon", w.HICON),
                        ("tip", w.WCHAR * 128), ("state", w.DWORD), ("state_mask", w.DWORD),
                        ("info", w.WCHAR * 256), ("timeout_or_version", w.UINT),
                        ("info_title", w.WCHAR * 64), ("info_flags", w.DWORD),
                        ("guid", Guid), ("balloon_icon", w.HICON)]

        signatures = {
            "DefWindowProcW": ([w.HWND, w.UINT, w.WPARAM, w.LPARAM], result_type),
            "RegisterClassW": ([c.POINTER(WindowClass)], w.ATOM),
            "UnregisterClassW": ([w.LPCWSTR, w.HINSTANCE], w.BOOL),
            "CreateWindowExW": ([w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int,
                                 c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID], w.HWND),
            "DestroyWindow": ([w.HWND], w.BOOL),
            "GetMessageW": ([c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], c.c_int),
            "TranslateMessage": ([c.POINTER(w.MSG)], w.BOOL),
            "DispatchMessageW": ([c.POINTER(w.MSG)], result_type),
            "PostQuitMessage": ([c.c_int], None),
            "RegisterWindowMessageW": ([w.LPCWSTR], w.UINT),
            "CreatePopupMenu": ([], w.HMENU),
            "AppendMenuW": ([w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR], w.BOOL),
            "DestroyMenu": ([w.HMENU], w.BOOL),
            "GetCursorPos": ([c.POINTER(w.POINT)], w.BOOL),
            "SetForegroundWindow": ([w.HWND], w.BOOL),
            "TrackPopupMenu": ([w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int, w.HWND, w.LPVOID], w.UINT),
            "PostMessageW": ([w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            "LoadIconW": ([w.HINSTANCE, w.LPCWSTR], w.HICON),
            "LoadImageW": ([w.HINSTANCE, w.LPCWSTR, w.UINT, c.c_int, c.c_int, w.UINT], w.HANDLE),
            "DestroyIcon": ([w.HICON], w.BOOL),
        }
        for name, (args, ret) in signatures.items():
            function = getattr(user, name)
            function.argtypes, function.restype = args, ret
        shell.Shell_NotifyIconW.argtypes = [w.DWORD, c.POINTER(IconData)]
        shell.Shell_NotifyIconW.restype = w.BOOL
        kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        kernel.GetModuleHandleW.restype = w.HMODULE
        instance = kernel.GetModuleHandleW(None)
        class_name = f"DeskBridgeTray-{os.getpid()}-{id(self)}"
        tray_message, taskbar_created = 0x8001, user.RegisterWindowMessageW("TaskbarCreated")
        data, icon, registered = IconData(), None, False
        own_icon = False

        def menu(window):
            value = user.CreatePopupMenu()
            try:
                if not value:
                    return
                user.AppendMenuW(value, 0, 1, "显示 DeskBridge")
                user.AppendMenuW(value, 0, 2, "退出并停止共享")
                point = w.POINT()
                if not user.GetCursorPos(c.byref(point)):
                    return
                user.SetForegroundWindow(window)
                selected = user.TrackPopupMenu(value, 0x0100 | 0x0002, point.x, point.y, 0, window, None)
                if selected in (1, 2):
                    self._action("show" if selected == 1 else "exit")
                user.PostMessageW(window, 0, 0, 0)
            finally:
                if value:
                    user.DestroyMenu(value)

        @callback
        def proc(window, message, wp, lp):
            try:
                if taskbar_created and message == taskbar_created:
                    self.ready = bool(shell.Shell_NotifyIconW(0, c.byref(data)))
                    if not self.ready:
                        self._action("unavailable")
                    return 0
                if message == tray_message:
                    if lp == 0x0203:  # WM_LBUTTONDBLCLK
                        self._action("show")
                    elif lp in (0x0205, 0x007B):  # right button / context menu
                        menu(window)
                    return 0
                if message == 0x0010:
                    user.DestroyWindow(window)
                    return 0
                if message == 0x0002:
                    user.PostQuitMessage(0)
                    return 0
            except Exception:
                self._action("unavailable")
            return user.DefWindowProcW(window, message, wp, lp)

        try:
            window_class = WindowClass(proc=proc, instance=instance, class_name=class_name)
            if not user.RegisterClassW(c.byref(window_class)):
                raise c.WinError(c.get_last_error())
            registered = True
            self.hwnd = user.CreateWindowExW(0, class_name, "DeskBridge tray", 0,
                                            0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise c.WinError(c.get_last_error())
            asset = Path(__file__).resolve().parent.parent / "assets" / "deskbridge.ico"
            if asset.is_file():
                icon = user.LoadImageW(None, str(asset), 1, 32, 32, 0x0010)
                own_icon = bool(icon)
            if not icon:
                icon = user.LoadIconW(None, c.cast(c.c_void_p(32512), w.LPCWSTR))
            data.size, data.window, data.identifier = c.sizeof(data), self.hwnd, 1
            data.flags, data.message, data.icon, data.tip = 7, tray_message, icon, "DeskBridge · 键鼠共享"
            if not shell.Shell_NotifyIconW(0, c.byref(data)):
                raise OSError("Notification area unavailable")
            self.ready = True
            self._started.set()
            if self._stop.is_set():
                return
            message = w.MSG()
            while True:
                value = user.GetMessageW(c.byref(message), None, 0, 0)
                if value == 0:
                    break
                if value < 0:
                    raise c.WinError(c.get_last_error())
                user.TranslateMessage(c.byref(message))
                user.DispatchMessageW(c.byref(message))
        except Exception as exc:
            self.failure = type(exc).__name__ + ":" + str(getattr(exc, "winerror", None))
            self._action("unavailable")
        finally:
            self.ready = False
            self._started.set()
            if self.hwnd:
                shell.Shell_NotifyIconW(2, c.byref(data))
                user.DestroyWindow(self.hwnd)
                self.hwnd = None
            if registered:
                user.UnregisterClassW(class_name, instance)
            if own_icon:
                user.DestroyIcon(icon)
