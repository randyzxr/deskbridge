from __future__ import annotations

import copy
from pathlib import Path
import queue
import os
import sys
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass

# The desktop bundle's Tcl scripts are relocated for self-contained execution.
# A normal Python installation uses its own Tcl if this directory is absent.
_tcl_root = Path(__file__).resolve().parent.parent / "vendor" / "tcl"
if sys.platform == "win32" and not getattr(sys, "frozen", False) and (_tcl_root / "tcl8.6" / "init.tcl").is_file():
    os.environ["TCL_LIBRARY"] = str(_tcl_root / "tcl8.6")
    os.environ["TK_LIBRARY"] = str(_tcl_root / "tk8.6")
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import CoreProcess, environment_description, find_engine
from .identity import Identity
from .model import Device, GRID_WIDTH, GRID_HEIGHT, MAX_DEVICES, OS_NAMES, Workspace
from .storage import Profile
from . import __version__

BG, PANEL, INK, MUTED = "#0b1220", "#142033", "#edf2fb", "#94a7bf"
ACCENT, LINE = "#4fe0bb", "#293a52"
FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "Helvetica"
COLORS = {"Windows": "#73aaff", "macOS": "#be9cff", "Ubuntu": "#ffaa72"}


class App:
    def __init__(self, root: tk.Tk, profile: Profile, workspace: Workspace, discovery=None):
        self.root, self.profile, self.workspace = root, profile, workspace
        self.identity, self.core = Identity(profile.tls), CoreProcess()
        self.local_fp = self.identity.ensure()
        workspace.automatic_network, workspace.address = True, ""
        if not workspace.engine or not Path(workspace.engine).exists() or getattr(sys, "frozen", False) and "_internal" in Path(workspace.engine).parts:
            workspace.engine = find_engine()
        from .discovery import LanDiscovery
        self.discovery = discovery or LanDiscovery(workspace.local_name, next(d.os for d in workspace.devices if d.name == workspace.local_name),
                                                   self.local_fp, workspace.port, workspace.mode)
        root.title("DeskBridge · 一套键鼠，多台电脑")
        width = min(1200, root.winfo_screenwidth() - 60)
        height = min(850, root.winfo_screenheight() - 110)
        root.geometry(f"{width}x{height}+20+20")
        root.minsize(min(1060, width), min(700, height))
        root.configure(bg=BG)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.hide_or_close)
        self._closing = False
        self._quit_requested = False
        from .tray import TrayIcon
        self.tray = TrayIcon()
        self.tray.start()
        root.bind("<Unmap>", self.on_minimize, add="+")
        self._drag = None
        self.busy = False
        self._style()
        self.name = tk.StringVar(value=workspace.local_name)
        self.mode = tk.StringVar(value=workspace.mode)
        self.port = tk.StringVar(value=str(workspace.port))
        self.server = tk.StringVar(value=workspace.server_name)
        self.engine = tk.StringVar(value=workspace.engine)
        self.clipboard = tk.BooleanVar(value=workspace.clipboard)
        self.status = tk.StringVar(value="尚未启动 · 所有连接均需双向核对证书指纹")
        self.network_status = tk.StringVar(value="自动发现局域网电脑；无需填写 IP。")
        self._polls = 0
        self._build()
        self.refresh()
        from .lock_service import receiver_service_installed
        self._service_installed = receiver_service_installed()
        if self._service_installed:
            self.set_controls(True)
            self.status.set("锁屏服务已安装，请通过系统服务启停；修改配对前先卸载服务。关闭此窗口不会停止后台服务。")
        self.root.after(100, self.poll)

    def _style(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=INK, font=(FONT, 9))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("TButton", background=LINE, foreground=INK, borderwidth=0, padding=(12, 7))
        s.map("TButton", background=[("active", "#35506e")], foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background=ACCENT, foreground=BG, font=(FONT, 10, "bold"))
        s.map("Accent.TButton", background=[("active", "#78edcc"), ("disabled", LINE)])
        s.configure("TEntry", fieldbackground=PANEL, foreground=INK, insertcolor=INK, padding=7)
        s.configure("TCombobox", fieldbackground=PANEL, foreground=INK, padding=6)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", INK)])
        s.configure("TRadiobutton", background=BG, foreground=INK, padding=7)
        s.configure("TCheckbutton", background=BG, foreground=INK, padding=4)
        s.map("TRadiobutton", background=[("active", BG)])
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=26, borderwidth=0)
        s.configure("Treeview.Heading", background=LINE, foreground=INK, padding=7)
        s.map("Treeview", background=[("selected", "#2b5764")])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(28, 12, 28, 10))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="DESKBRIDGE", font=(FONT, 22, "bold"), foreground=ACCENT).pack(side="left")
        ttk.Label(header, text="一套键鼠，多台电脑\nWindows  /  macOS  /  Ubuntu", style="Muted.TLabel", justify="right").pack(side="right")
        if self.tray.ready:
            ttk.Button(header, text="隐藏到托盘", command=self.hide_window).pack(side="right", padx=16)
        body = ttk.Frame(self.root, padding=(28, 0, 28, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=290)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left_holder = ttk.Frame(body, padding=(0, 0, 20, 0))
        left_holder.grid(row=0, column=0, sticky="nsew")
        self.left_canvas = tk.Canvas(left_holder, width=280, height=1, bg=BG, highlightthickness=0)
        self.left_canvas.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(left_holder, orient="vertical", command=self.left_canvas.yview)
        scroll.pack(side="right", fill="y")
        self.left_canvas.configure(yscrollcommand=scroll.set)
        left = ttk.Frame(self.left_canvas)
        left_id = self.left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self.left_canvas.bind("<Configure>", lambda event: self.left_canvas.itemconfigure(left_id, width=event.width))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(left, text="01  本机与连接", font=(FONT, 13, "bold")).pack(anchor="w", pady=(0, 10))
        self._field(left, "本机名称（其他电脑添加时须一致）", self.name)
        role = ttk.Frame(left)
        role.pack(fill="x", pady=(10, 6))
        ttk.Radiobutton(role, text="共享键鼠", variable=self.mode, value="server", command=self.role_changed).pack(side="left")
        ttk.Radiobutton(role, text="接收键鼠", variable=self.mode, value="client", command=self.role_changed).pack(side="left")
        ttk.Label(left, text="网络连接：自动发现 / DHCP", foreground=ACCENT).pack(anchor="w", pady=(8, 5))
        ttk.Label(left, textvariable=self.network_status, style="Muted.TLabel", wraplength=260).pack(anchor="w", pady=5)
        self._field(left, "共享服务端口（接收端自动获取）", self.port)
        ttk.Label(left, text="共享端电脑（接收模式）", style="Muted.TLabel").pack(anchor="w", pady=(8, 5))
        self.server_combo = ttk.Combobox(left, textvariable=self.server, state="readonly")
        self.server_combo.pack(fill="x")
        ttk.Separator(left).pack(fill="x", pady=16)
        ttk.Label(left, text="02  身份配对", font=(FONT, 13, "bold")).pack(anchor="w")
        ttk.Label(left, text="本机证书的 SHA-256 指纹", style="Muted.TLabel").pack(anchor="w", pady=(10, 5))
        self.fp_text = tk.Text(left, width=28, height=4, bg=PANEL, fg=ACCENT, relief="flat", wrap="char", font=("Consolas", 10), padx=9, pady=9)
        self.fp_text.insert("1.0", self.local_fp)
        self.fp_text.configure(state="disabled")
        self.fp_text.pack(fill="x")
        ttk.Button(left, text="复制本机指纹", command=self.copy_fp).pack(fill="x", pady=(7, 5))
        ttk.Label(left, text="在对端屏幕核对完整指纹。双方都要添加；每台电脑使用自己的私钥。", style="Muted.TLabel", wraplength=270).pack(anchor="w", pady=5)
        ttk.Separator(left).pack(fill="x", pady=13)
        ttk.Label(left, text="03  输入核心", font=(FONT, 13, "bold")).pack(anchor="w")
        ttk.Entry(left, textvariable=self.engine).pack(fill="x", pady=(10, 7))
        ttk.Button(left, text="选择 Deskflow 1.27.0 核心…", command=self.choose_engine).pack(fill="x")
        ttk.Label(left, text=environment_description(), style="Muted.TLabel", wraplength=275).pack(anchor="w", pady=12)
        ttk.Label(right, text="桌面布局", font=(FONT, 16, "bold")).pack(anchor="w")
        ttk.Label(right, text="拖动电脑卡片，按真实摆放排列；设备须边缘相邻。", style="Muted.TLabel").pack(anchor="w", pady=(5, 10))
        self.board = tk.Canvas(right, bg=PANEL, height=180, highlightthickness=1, highlightbackground=LINE)
        self.board.pack(fill="x")
        self.board.bind("<Configure>", lambda _: self.draw())
        self.board.bind("<ButtonPress-1>", self.drag_start)
        self.board.bind("<ButtonRelease-1>", self.drag_end)
        self.board.bind("<Double-Button-1>", lambda _: self.edit_device())
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(5, 7))
        self.add_button = ttk.Button(bar, text="＋ 添加并信任电脑", command=self.add_device)
        self.add_button.pack(side="left")
        self.edit_button = ttk.Button(bar, text="编辑", command=self.edit_device)
        self.edit_button.pack(side="left", padx=7)
        self.remove_button = ttk.Button(bar, text="移除信任", command=self.remove_device)
        self.remove_button.pack(side="left")
        self.table = ttk.Treeview(right, columns=("os", "trust"), show="tree headings", height=3, selectmode="browse")
        self.table.heading("#0", text="电脑名称")
        self.table.heading("os", text="系统")
        self.table.heading("trust", text="配对指纹")
        self.table.column("#0", width=180)
        self.table.column("os", width=85)
        self.table.column("trust", width=270)
        self.table.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", lambda _: self.draw())
        options = ttk.Frame(right)
        options.pack(fill="x", pady=5)
        ttk.Checkbutton(options, text="启用剪贴板共享（上限 1 MiB，默认关闭）", variable=self.clipboard).pack(anchor="w")
        ttk.Label(right, text="所有已配对设备属于同一信任域，可共享本工作区输入和启用后的剪贴板。", style="Muted.TLabel", wraplength=750).pack(anchor="w", pady=(0, 8))
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(2, 5))
        self.start_button = ttk.Button(actions, text="启动共享", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.save_button = ttk.Button(actions, text="保存配置", command=self.save)
        self.save_button.pack(side="left")
        self.service_button = None
        if sys.platform == "win32":
            self.service_button = ttk.Button(actions, text="生成锁屏服务配置", command=self.export_lock_service)
            self.service_button.pack(side="left", padx=8)
        help_text = "Ctrl + Alt + F12 返回共享端 · 关闭窗口隐藏到托盘；托盘菜单退出停止共享" if self.tray.ready else "Ctrl + Alt + F12 返回共享端 · 关闭应用停止共享"
        ttk.Label(right, text=help_text, style="Muted.TLabel", wraplength=750).pack(anchor="w", pady=(5, 8))
        ttk.Label(right, textvariable=self.status, foreground=ACCENT, wraplength=750).pack(anchor="w", pady=(4, 8))
        self.log = tk.Text(right, height=7, bg="#080e18", fg=MUTED, insertbackground=INK, relief="flat", font=("Consolas", 9), wrap="word", padx=10, pady=8, state="disabled")
        self.log.pack(fill="both", expand=True)
        footer = ttk.Frame(self.root, padding=(28, 7))
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Label(footer, text="LOCAL NETWORK  ·  TLS + SHA-256 双向指纹认证  ·  无云端中转", foreground=MUTED, font=(FONT, 9)).pack(side="left")
        ttk.Label(footer, text=f"MVP {__version__} / Core 1.27.0", foreground=MUTED, font=(FONT, 9)).pack(side="right")
        self.role_changed()

    @staticmethod
    def _field(parent, label, variable) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel", wraplength=250).pack(anchor="w", pady=(8, 5))
        ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def role_changed(self) -> None:
        self.sync_server_choice()
        if hasattr(self, "start_button"):
            self.start_button.configure(text="启动共享" if self.mode.get() == "server" else "连接共享端")
        if not self.core.running:
            self.discovery.update(self.workspace.local_name,
                                  next(d.os for d in self.workspace.devices if d.name == self.workspace.local_name),
                                  self.local_fp, self.workspace.port, self.mode.get())

    def sync_server_choice(self) -> None:
        peers = [d.name for d in self.workspace.devices if d.name != self.workspace.local_name and d.fingerprint]
        if hasattr(self, "server_combo"):
            self.server_combo.configure(values=peers)
        if self.server.get() and self.server.get() not in peers:
            self.server.set("")
        if self.mode.get() == "client" and not self.server.get() and len(peers) == 1:
            self.server.set(peers[0])

    def collect(self) -> Workspace:
        self.sync_server_choice()
        value = copy.deepcopy(self.workspace)
        old_name = value.local_name
        value.local_name = self.name.get().strip()
        for device in value.devices:
            if device.name == old_name:
                device.name = value.local_name
        if value.server_name == old_name:
            value.server_name = value.local_name
        value.mode, value.address, value.automatic_network = self.mode.get(), "", True
        try:
            value.port = int(self.port.get())
        except ValueError:
            raise ValueError("端口必须是整数。") from None
        value.server_name, value.clipboard, value.engine = self.server.get(), self.clipboard.get(), self.engine.get().strip()
        value.select_single_server()
        value.validate()
        return value

    def save(self) -> bool:
        try:
            from .lock_service import receiver_service_installed
            if receiver_service_installed():
                raise ValueError("请先卸载锁屏服务，再修改配对或启动普通共享；服务使用管理员批准的独立快照。")
            if self.core.running:
                raise ValueError("请先停止共享，再保存或修改配置。")
            value = self.collect()
            self.profile.save(value)
            self.workspace = value
            self.discovery.update(value.local_name, next(d.os for d in value.devices if d.name == value.local_name),
                                  self.local_fp, value.port, value.mode)
            self.refresh()
            self.status.set("配置已保存；尚未启动共享。")
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法保存", str(exc), parent=self.root)
            return False

    def refresh(self) -> None:
        selection = self.table.selection()
        self.table.delete(*self.table.get_children())
        for d in self.workspace.devices:
            local = d.name == self.workspace.local_name
            self.table.insert("", "end", iid=d.name, text=d.name + (" · 本机" if local else ""),
                              values=(d.os, "本机身份" if local else (d.fingerprint[:16] + "…" if d.fingerprint else "未配对")))
        if selection and selection[0] in self.table.get_children():
            self.table.selection_set(selection[0])
        self.sync_server_choice()
        self.draw()

    def draw(self) -> None:
        c = self.board
        c.delete("all")
        w, h = max(c.winfo_width(), 650), max(c.winfo_height(), 180)
        cw, ch = w/GRID_WIDTH, h/GRID_HEIGHT
        for x in range(GRID_WIDTH):
            for y in range(GRID_HEIGHT):
                c.create_rectangle(x*cw+5, y*ch+5, (x+1)*cw-5, (y+1)*ch-5, outline=LINE, dash=(2, 5))
        selection = self.table.selection() if hasattr(self, "table") else ()
        positions = {(d.x, d.y): d for d in self.workspace.devices}
        for d in self.workspace.devices:
            for dx, dy in ((1, 0), (0, 1)):
                if (d.x+dx, d.y+dy) in positions:
                    c.create_line((d.x+.5)*cw, (d.y+.5)*ch, (d.x+dx+.5)*cw, (d.y+dy+.5)*ch, fill=ACCENT, width=2)
        for d in self.workspace.devices:
            left, top = d.x*cw+10, d.y*ch+10
            color = ACCENT if d.name == self.workspace.local_name else COLORS[d.os]
            selected = selection and selection[0] == d.name
            c.create_rectangle(left, top, left+cw-20, top+ch-20, fill="#20314a", outline=color, width=3 if selected else 1)
            short = d.name if len(d.name) <= 16 else d.name[:14] + "…"
            c.create_text(left+10, top+14, text=short, fill=INK, anchor="w", font=(FONT, 9, "bold"))
            c.create_text(left+10, top+31, text=d.os + (" · 本机" if d.name == self.workspace.local_name else ""), fill=color, anchor="w", font=(FONT, 8))

    def cell(self, event) -> tuple[int, int]:
        return int(event.x / (max(self.board.winfo_width(), 650)/GRID_WIDTH)), int(event.y / (max(self.board.winfo_height(), 180)/GRID_HEIGHT))

    def drag_start(self, event) -> None:
        self._drag = next((d.name for d in self.workspace.devices if (d.x, d.y) == self.cell(event)), None)
        if self._drag:
            self.table.selection_set(self._drag)
            self.draw()

    def drag_end(self, event) -> None:
        if self.core.running or self.busy or not self._drag:
            self._drag = None
            return
        x, y = self.cell(event)
        if 0 <= x < GRID_WIDTH and 0 <= y < GRID_HEIGHT:
            d = next(d for d in self.workspace.devices if d.name == self._drag)
            target = next((t for t in self.workspace.devices if (t.x, t.y) == (x, y)), None)
            if target:
                target.x, target.y = d.x, d.y
            d.x, d.y = x, y
            self.status.set("布局已修改；保存并重启后生效。")
            self.refresh()
        self._drag = None

    def selected(self):
        ids = self.table.selection()
        return next((d for d in self.workspace.devices if ids and d.name == ids[0]), None)

    def add_device(self) -> None:
        if self.core.running or self.busy:
            return
        if len(self.workspace.devices) >= MAX_DEVICES:
            messagebox.showinfo("设备数量", "首版最多支持 8 台电脑。", parent=self.root)
            return
        self.device_dialog()

    def edit_device(self) -> None:
        if self.core.running or self.busy:
            return
        d = self.selected()
        if d and d.name != self.workspace.local_name:
            self.device_dialog(d)
        elif d:
            messagebox.showinfo("本机", "请在左侧修改本机名称；本机指纹由证书生成。", parent=self.root)

    def device_dialog(self, existing=None) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("核对并信任电脑")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        box = ttk.Frame(dialog, padding=24)
        box.pack(fill="both")
        ttk.Label(box, text="在对端屏幕核对身份", font=(FONT, 15, "bold")).pack(anchor="w")
        name = tk.StringVar(value=existing.name if existing else "")
        operating_system = tk.StringVar(value=existing.os if existing else "Windows")
        fp = tk.StringVar(value=existing.fingerprint if existing else "")
        if not existing:
            peers = self.discovery.snapshot()
            found = tk.StringVar()
            ttk.Label(box, text="发现的电脑（仍须在对端核对完整指纹）", style="Muted.TLabel").pack(anchor="w", pady=(8, 5))
            chooser = ttk.Combobox(box, textvariable=found, state="readonly", width=54,
                                   values=[f"{p.name} · {p.os} · {p.fingerprint[:12]}" for p in peers])
            chooser.pack(fill="x")
            def select_peer(_):
                index = chooser.current()
                if 0 <= index < len(peers):
                    peer = peers[index]
                    name.set(peer.name)
                    operating_system.set(peer.os)
                    fp.set(peer.fingerprint)
            chooser.bind("<<ComboboxSelected>>", select_peer)
        self._field(box, "对端本机名称（必须一致）", name)
        ttk.Label(box, text="操作系统", style="Muted.TLabel").pack(anchor="w", pady=(8, 5))
        ttk.Combobox(box, textvariable=operating_system, values=OS_NAMES, state="readonly", width=54).pack(fill="x")
        self._field(box, "对端完整 SHA-256 指纹", fp)
        ttk.Label(box, text="请从对端 DeskBridge 复制公开指纹并核对。添加后授予本工作区键鼠访问；剪贴板仅在开启时共享。", style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=14)

        def apply():
            try:
                from .model import fingerprint
                value = self.collect()
                old = next((d for d in value.devices if existing and d.name == existing.name), None)
                if old:
                    x, y = old.x, old.y
                    value.devices.remove(old)
                else:
                    used = {(d.x, d.y) for d in value.devices}
                    empty = [(x, y) for y in range(GRID_HEIGHT) for x in range(GRID_WIDTH) if (x, y) not in used]
                    local = next(d for d in value.devices if d.name == value.local_name)
                    x, y = min(empty, key=lambda p: abs(p[0]-local.x)+abs(p[1]-local.y))
                value.devices.append(Device(name.get().strip(), operating_system.get(), x, y, fingerprint(fp.get())))
                if old and value.server_name == old.name:
                    value.server_name = name.get().strip()
                value.validate()
                if fp.get().replace(":", "").strip().lower() == self.local_fp:
                    raise ValueError("请输入其他电脑的指纹，不能使用本机指纹。")
                self.workspace = value
                self.server.set(value.server_name)
                self.refresh()
                self.status.set("设备已加入；双方都要完成配对，然后保存并启动。")
                dialog.destroy()
            except (ValueError, OSError) as exc:
                messagebox.showerror("无法添加", str(exc), parent=dialog)

        ttk.Button(box, text="已核对，添加信任", style="Accent.TButton", command=apply).pack(fill="x")
        ttk.Button(box, text="取消", command=dialog.destroy).pack(fill="x", pady=(7, 0))

    def remove_device(self) -> None:
        if self.core.running or self.busy:
            return
        d = self.selected()
        if not d or d.name == self.workspace.local_name:
            return
        if messagebox.askyesno("移除信任", f"移除 {d.name} 的布局和配对权限？保存后下次启动生效。", parent=self.root):
            self.workspace.devices.remove(d)
            if self.server.get() == d.name:
                self.server.set("")
                self.workspace.server_name = ""
            self.refresh()

    def copy_fp(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.local_fp)
        self.status.set("本机公开指纹已复制。请在对端核对完整指纹。")

    def choose_engine(self) -> None:
        if self.core.running or self.busy:
            return
        path = filedialog.askopenfilename(title="选择官方 Deskflow 1.27.0 的 deskflow-core", parent=self.root)
        if path:
            self.engine.set(path)

    def export_lock_service(self) -> None:
        if self.busy or self.core.running or not self.save():
            return
        try:
            from .lock_service import current_owner_sid, export_receiver
            target = export_receiver(self.profile, self.workspace, self.identity, current_owner_sid())
            self.status.set("锁屏服务私有配置已生成；需在本机接收端由管理员安装。")
            messagebox.showinfo("Windows 接收端锁屏服务", f"已生成私有配置：\n{target}\n\n请按 docs/lock-screen.md 在 Windows 接收端以管理员身份运行 service/Install-LockReceiver.ps1。\n安装后使用后台服务接收键鼠；普通桌面接收核心保持停止。\n首次安装的安全桌面效果需实机验收。", parent=self.root)
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法生成服务配置", str(exc), parent=self.root)

    def start(self) -> None:
        if self.busy or self.core.running or not self.save():
            return
        self.busy = True
        self.set_controls(True)
        self.status.set("检查核心版本与配对信息…")
        # Permission prompts / process probes must never block the Tk event loop.
        import threading
        def task():
            try:
                self.core.start(self.profile, copy.deepcopy(self.workspace), self.identity, self.discovery)
            except Exception as exc:
                self.core.emit("start_error", f"无法启动：{exc}")
            finally:
                self.core.emit("ready", "")
        threading.Thread(target=task, daemon=True).start()

    def stop(self) -> None:
        if self.busy:
            return
        self.busy = True
        import threading
        def task():
            try:
                self.core.stop()
            except Exception as exc:
                self.core.emit("log", f"停止核心时发生问题：{exc}")
            finally:
                self.core.emit("ready", "")
        threading.Thread(target=task, daemon=True).start()

    def set_controls(self, locked: bool) -> None:
        for button in (self.start_button, self.save_button, self.add_button, self.edit_button, self.remove_button):
            button.configure(state="disabled" if locked else "normal")
        if self.service_button:
            self.service_button.configure(state="disabled" if locked else "normal")
        self.stop_button.configure(state="normal" if self.core.running and not self.busy else "disabled")
        def apply(parent):
            for child in parent.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Radiobutton, ttk.Checkbutton)):
                    child.state(["disabled"] if locked else ["!disabled"])
                apply(child)
        apply(self.root)

    def poll(self) -> None:
        if self._closing:
            return
        actions = self.tray.actions()
        if "unavailable" in actions:
            self.show_window()
        if "exit" in actions:
            self.close()
            if self._closing:
                return
        elif "show" in actions:
            self.show_window()
        self._polls += 1
        if self._polls % 10 == 0:
            peers = self.discovery.snapshot()
            self.network_status.set(self.discovery.status + f" · 已发现 {len(peers)} 台")
        for _ in range(100):
            try:
                kind, text = self.core.events.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.busy = False
                self.set_controls(self.core.running)
            elif kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", text + "\n")
                if int(self.log.index("end-1c").split(".")[0]) > 300:
                    self.log.delete("1.0", "50.0")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind in ("status", "exit", "start_error"):
                self.status.set(text)
                if kind == "exit":
                    self.set_controls(False)
                elif kind == "start_error":
                    messagebox.showerror("无法启动", text, parent=self.root)
        if self._quit_requested and not self.busy:
            self.close()
            return
        self.root.after(100, self.poll)

    def hide_window(self) -> None:
        if self.tray.ready and not self._closing:
            self.root.withdraw()
        elif not self._closing:
            self.root.iconify()

    def on_minimize(self, event) -> None:
        if event.widget is self.root and self.root.state() == "iconic" and self.tray.ready:
            self.root.after_idle(self.hide_window)

    def show_window(self) -> None:
        if not self._closing:
            self.root.deiconify()
            self.root.lift()

    def hide_or_close(self) -> None:
        if self.tray.ready:
            self.hide_window()
        else:
            self.close()

    def close(self) -> None:
        if self.busy:
            self._quit_requested = True
            self.show_window()
            self.status.set("正在完成启停操作，请稍候再关闭。")
            return
        self._closing = True
        self.tray.close()
        self.core.stop()
        self.discovery.close()
        self.profile.close()
        self.root.destroy()


def run_gui(profile: Profile, workspace: Workspace) -> None:
    root = tk.Tk()
    application = None
    try:
        application = App(root, profile, workspace)
        root.mainloop()
    finally:
        if application:
            application.tray.close()
            application.core.stop()
            application.discovery.close()
        profile.close()
