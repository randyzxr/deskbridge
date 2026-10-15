from __future__ import annotations

from dataclasses import dataclass, field, asdict
import ipaddress
import re
import socket

MAX_DEVICES = 8
GRID_WIDTH, GRID_HEIGHT = 5, 3
OS_NAMES = ("Windows", "macOS", "Ubuntu")


def computer_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", value):
        raise ValueError("电脑名称须以英文字母开头，仅含字母、数字、短横线或下划线，最多 48 字符。")
    return value


def fingerprint(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("证书指纹必须是文字。")
    raw = value.strip().lower()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    raw = raw.replace(":", "").replace(" ", "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw):
        raise ValueError("请输入对端显示的完整 SHA-256 指纹（64 个十六进制字符）。")
    return raw


def lan_address(value: str) -> str:
    try:
        addr = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError):
        raise ValueError("首版使用明确的局域网 IPv4 地址，例如 192.168.1.20。") from None
    private_lan = any(addr in net for net in (
        ipaddress.IPv4Network("10.0.0.0/8"), ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"), ipaddress.IPv4Network("127.0.0.0/8"),
    ))
    if not private_lan or addr == ipaddress.IPv4Address("127.0.0.0"):
        raise ValueError("仅允许 RFC1918 局域网或回环地址；请填写具体地址，不使用公网或全网监听。")
    return str(addr)


def default_name() -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]", "-", socket.gethostname())[:40]
    return raw if re.match(r"[A-Za-z]", raw) else "Desktop-" + raw


@dataclass
class Device:
    name: str
    os: str
    x: int
    y: int
    fingerprint: str = ""

    def validate(self) -> None:
        computer_name(self.name)
        if self.os not in OS_NAMES:
            raise ValueError("设备系统只能选择 Windows、macOS 或 Ubuntu。")
        if type(self.x) is not int or type(self.y) is not int or not (0 <= self.x < GRID_WIDTH and 0 <= self.y < GRID_HEIGHT):
            raise ValueError("设备位置超出布局范围。")
        if self.fingerprint:
            self.fingerprint = fingerprint(self.fingerprint)


@dataclass
class Workspace:
    local_name: str
    devices: list[Device] = field(default_factory=list)
    mode: str = "server"
    address: str = "127.0.0.1"
    port: int = 24800
    server_name: str = ""
    clipboard: bool = False
    engine: str = ""
    schema: int = 1
    automatic_network: bool = False

    @classmethod
    def new(cls, os_name: str) -> Workspace:
        name = default_name()
        return cls(name, [Device(name, os_name, 2, 1)], address="", automatic_network=True)

    @classmethod
    def from_dict(cls, data: dict) -> Workspace:
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("配置格式或字段不受支持。")
        if data.get("schema", 1) != 1:
            raise ValueError("不支持此配置版本。")
        device_data = data.get("devices", [])
        if not isinstance(device_data, list) or len(device_data) > MAX_DEVICES:
            raise ValueError("设备数量超出上限。")
        try:
            result = cls(**{**data, "devices": [Device(**d) for d in device_data]})
        except (TypeError, KeyError):
            raise ValueError("配置字段类型不正确。") from None
        result.validate()
        return result

    def to_dict(self) -> dict:
        return asdict(self)

    def select_single_server(self) -> None:
        """An existing sole paired peer is an unambiguous client default."""
        if self.mode == "client" and not self.server_name:
            peers = [d for d in self.devices if d.name != self.local_name and d.fingerprint]
            if len(peers) == 1:
                self.server_name = peers[0].name

    def validate(self, ready: bool = False) -> None:
        computer_name(self.local_name)
        if self.mode not in ("server", "client"):
            raise ValueError("请选择共享端或接收端。")
        if type(self.automatic_network) is not bool:
            raise ValueError("网络模式配置类型不正确。")
        if self.automatic_network:
            if self.address != "":
                raise ValueError("自动发现模式不保存固定地址。")
        elif not (self.mode == "server" and self.address == "0.0.0.0"):
            lan_address(self.address)
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("端口范围为 1024–65535。")
        if type(self.clipboard) is not bool or not isinstance(self.engine, str):
            raise ValueError("配置字段类型不正确。")
        if not 1 <= len(self.devices) <= MAX_DEVICES:
            raise ValueError("首版支持 1–8 台设备。")
        names, coords, fingerprints = set(), set(), set()
        for d in self.devices:
            d.validate()
            if d.name.casefold() in names or (d.x, d.y) in coords:
                raise ValueError("电脑名称或网格位置不能重复。")
            names.add(d.name.casefold())
            coords.add((d.x, d.y))
            if d.fingerprint:
                if d.fingerprint in fingerprints:
                    raise ValueError("不同设备不能复用同一证书指纹。")
                fingerprints.add(d.fingerprint)
            if ready and d.name != self.local_name and not d.fingerprint:
                raise ValueError(f"请先核对并添加 {d.name} 的证书指纹。")
        if sum(d.name == self.local_name for d in self.devices) != 1:
            raise ValueError("布局必须且只能包含一台本机。")
        if self.server_name and self.server_name not in [d.name for d in self.devices]:
            raise ValueError("共享端电脑不在设备列表中。")
        if ready:
            if len(self.devices) < 2:
                raise ValueError("请至少添加一台已配对的电脑。")
            if self.mode == "client" and (not self.server_name or self.server_name == self.local_name):
                raise ValueError("请在左侧“共享端电脑”选择已配对的共享端；多台设备时需要明确选择。")
            visited = {next(iter(coords))}
            while True:
                extra = {p for p in coords if any(abs(p[0]-q[0]) + abs(p[1]-q[1]) == 1 for q in visited)}
                if extra <= visited:
                    break
                visited |= extra
            if visited != coords:
                raise ValueError("布局中的电脑须边缘相邻，不能有空格隔断或仅对角相接。")

    def server_config(self) -> str:
        self.validate()
        lookup = {(d.x, d.y): d.name for d in self.devices}
        # In 1.27 computers are registered in engine.ini, not a screens section.
        lines = ["section: links"]
        for d in self.devices:
            lines.append(f"    {d.name}:")
            for direction, dx, dy in (("left", -1, 0), ("right", 1, 0), ("up", 0, -1), ("down", 0, 1)):
                if target := lookup.get((d.x+dx, d.y+dy)):
                    lines.append(f"        {direction} = {target}")
        primary = self.local_name if self.mode == "server" else self.server_name
        computer_name(primary or self.local_name)
        lines.extend(["end", "", "section: options",
                      f"    keystroke(Control+Alt+F12) = switchToScreen({primary or self.local_name})", "end", ""])
        return "\n".join(lines)
