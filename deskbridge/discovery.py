"""LAN mDNS is an address hint. Only certificate pinning grants trust."""
from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
import time
import ipaddress

from .model import MAX_DEVICES, OS_NAMES, computer_name, fingerprint, lan_address

SERVICE_TYPE = "_deskbridge._tcp.local."
MAX_PEERS = 32


def hostname_addresses(name, port):
    """System DNS is only an endpoint hint; the core still verifies the pin."""
    computer_name(name)
    records = socket.getaddrinfo(name, port, socket.AF_INET, socket.SOCK_STREAM)
    if not records or len(records) > 16:
        raise ValueError("Invalid hostname endpoints")
    addresses = {lan_address(record[4][0]) for record in records}
    if any(a.startswith("127.") for a in addresses):
        raise ValueError("Remote hostname resolved to loopback")
    return tuple(sorted(addresses))


@dataclass(frozen=True)
class Peer:
    service: str
    name: str
    os: str
    fingerprint: str
    role: str
    addresses: tuple[str, ...]
    port: int
    seen: float


def decode_peer(info) -> Peer:
    if not info.name.endswith(SERVICE_TYPE) or len(info.name) > 180:
        raise ValueError("Invalid discovery service")
    props = info.properties
    if len(props) > 10 or sum(len(k) + len(v or b"") for k, v in props.items()) > 1024:
        raise ValueError("Discovery metadata too large")
    def field(key):
        value = props.get(key.encode(), b"")
        if not isinstance(value, bytes) or len(value) > 128:
            raise ValueError("Invalid discovery metadata")
        return value.decode("ascii")
    if field("protocol") != "1":
        raise ValueError("Unsupported discovery protocol")
    name, operating_system, role = computer_name(field("name")), field("os"), field("role")
    identity = fingerprint(field("fingerprint"))
    if operating_system not in OS_NAMES or role not in ("server", "client"):
        raise ValueError("Invalid advertised device")
    if not 1024 <= info.port <= 65535:
        raise ValueError("Invalid advertised port")
    addresses = []
    for address in info.parsed_addresses()[:16]:
        try:
            valid = lan_address(address)
            if not valid.startswith("127.") and valid not in addresses:
                addresses.append(valid)
        except ValueError:
            continue
    if not addresses:
        raise ValueError("No eligible LAN endpoint")
    return Peer(info.name, name, operating_system, identity, role, tuple(sorted(addresses)), info.port, time.monotonic())


def local_addresses() -> tuple[str, ...]:
    import ifaddr
    addresses = set()
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                try:
                    address = lan_address(ip.ip)
                    if not address.startswith("127."):
                        addresses.add(address)
                except ValueError:
                    pass
    return tuple(sorted(addresses))[:16]


def preferred_address(addresses):
    import ifaddr
    networks = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                try:
                    networks.append(ipaddress.IPv4Network(f"{lan_address(ip.ip)}/{ip.network_prefix}", strict=False))
                except ValueError:
                    pass
    def score(address):
        parsed = ipaddress.IPv4Address(address)
        prefix = max((network.prefixlen for network in networks if parsed in network), default=-1)
        return -prefix, int(parsed)
    return min(addresses, key=score)


class LanDiscovery:
    REFRESH_SECONDS = 3
    def __init__(self, name, operating_system, identity, port, role):
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._dns_wake = threading.Event()
        self._peers: dict[str, Peer] = {}
        self._services: dict[str, float] = {}
        self._targets: dict[str, float] = {}
        self._host_requests: dict[str, tuple[int, float]] = {}
        self._hosts: dict[str, tuple[tuple[str, ...], int, float]] = {}
        self._settings = (computer_name(name), operating_system, fingerprint(identity), port, role)
        self.status = "正在发现局域网电脑…"
        self._zc = self._browser = self._info = None
        # A single daemon resolver bounds concurrency. Slow system DNS never
        # blocks the UI or the caller's discovery deadline.
        self._dns_thread = threading.Thread(target=self._dns_work, daemon=True, name="deskbridge-dns")
        self._dns_thread.start()
        self._thread = threading.Thread(target=self._work, daemon=True, name="deskbridge-mdns")
        self._thread.start()

    def update(self, name, operating_system, identity, port, role):
        with self._condition:
            self._settings = (computer_name(name), operating_system, fingerprint(identity), port, role)
        self._wake.set()

    def snapshot(self):
        with self._condition:
            now = time.monotonic()
            return sorted((p for p in self._peers.values() if now-p.seen < 60 and p.fingerprint != self._settings[2]),
                          key=lambda p: (p.name, p.service))

    def resolve(self, expected_fingerprint, expected_name, timeout=0):
        expected = fingerprint(expected_fingerprint)
        expected_name = computer_name(expected_name)
        deadline = time.monotonic() + timeout
        with self._condition:
            service = f"deskbridge-{expected[:16]}.{SERVICE_TYPE}"
            if service in self._targets or len(self._targets) < MAX_DEVICES:
                self._targets[service] = time.monotonic()
            if expected_name in self._host_requests or len(self._host_requests) < MAX_DEVICES:
                self._host_requests[expected_name] = (self._settings[3], time.monotonic())
            self._wake.set()
            self._dns_wake.set()
            while not self._stop.is_set():
                matches = [p for p in self._peers.values() if p.fingerprint == expected and p.name == expected_name
                           and p.role == "server" and time.monotonic()-p.seen < 60]
                if matches:
                    peer = max(matches, key=lambda p: p.seen)
                    return preferred_address(peer.addresses), peer.port
                # Explicit contrary discovery data is actionable; do not mask
                # an incorrect role, renamed device, or replaced identity.
                conflict = any(time.monotonic()-p.seen < 60 and
                               (p.fingerprint == expected or p.name == expected_name)
                               for p in self._peers.values())
                host = self._hosts.get(expected_name)
                if not conflict and host and time.monotonic()-host[2] < 10 and host[1] == self._settings[3]:
                    self.status = "使用已配对电脑名自动寻址 · 连接仍须验证证书指纹"
                    return preferred_address(host[0]), host[1]
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(min(remaining, .5))
        return None

    def explain_missing(self, expected_fingerprint, expected_name):
        with self._condition:
            peers = [p for p in self._peers.values() if time.monotonic()-p.seen < 60]
            same = next((p for p in peers if p.fingerprint == expected_fingerprint), None)
            if same and same.name != expected_name:
                return f"已配对电脑当前名为 {same.name}，与配置中的 {expected_name} 不同。请核对名称。"
            if same and same.role != "server":
                return f"{expected_name} 当前处于接收模式。请在对端选择“共享键鼠”并启动共享。"
            if any(p.name == expected_name and p.fingerprint != expected_fingerprint for p in peers):
                return f"发现 {expected_name}，但证书指纹与配对记录不同。请在双方屏幕核对完整指纹；不会自动更换信任。"
        return (f"无法自动寻址 {expected_name}。请确认对端已启动共享；跨网段时电脑名须能由系统解析，"
                "备用连接端口须与共享端一致。也可检查组播 UDP 5353。" + f" 发现状态：{self.status}")

    def _dns_work(self):
        while not self._stop.is_set():
            with self._condition:
                requests = [(name, port) for name, (port, seen) in self._host_requests.items()
                            if time.monotonic()-seen < 60]
            for name, port in requests:
                if self._stop.is_set():
                    return
                try:
                    addresses = hostname_addresses(name, port)
                except (OSError, ValueError):
                    addresses = ()
                with self._condition:
                    if self._stop.is_set():
                        return
                    if addresses:
                        self._hosts[name] = (addresses, port, time.monotonic())
                    else:
                        self._hosts.pop(name, None)
                    self._condition.notify_all()
            self._dns_wake.wait(self.REFRESH_SECONDS)
            self._dns_wake.clear()

    def _refresh(self, zc, service):
        try:
            info = zc.get_service_info(SERVICE_TYPE, service, timeout=500)
            if not info:
                return
            peer = decode_peer(info)
        except (ValueError, UnicodeError, OSError, RuntimeError):
            return
        with self._condition:
            if peer.service not in self._peers and len(self._peers) >= MAX_PEERS:
                oldest = min(self._peers, key=lambda s: self._peers[s].seen)
                self._peers.pop(oldest)
            self._peers[peer.service] = peer
            self._condition.notify_all()

    def add_service(self, zc, type_, name):
        if not isinstance(name, str) or len(name) > 180 or not name.endswith(SERVICE_TYPE):
            return
        with self._condition:
            if name in self._services or len(self._services) < MAX_PEERS:
                self._services[name] = time.monotonic()
        self._wake.set()

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)

    def remove_service(self, zc, type_, name):
        with self._condition:
            self._peers.pop(name, None)
            self._services.pop(name, None)
            self._condition.notify_all()

    def _release_network(self):
        if self._browser:
            self._browser.cancel()
            self._browser = None
        if self._zc:
            try:
                if self._info:
                    self._zc.unregister_service(self._info)
            finally:
                self._zc.close()
                self._zc = self._info = None

    def _work(self):
        active_addresses, published, cursor = (), None, 0
        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf
            while not self._stop.is_set():
                try:
                    addresses = local_addresses()
                    if addresses != active_addresses:
                        self._release_network()
                        active_addresses, published = addresses, None
                    if not addresses:
                        self.status = "等待局域网网络；无需填写 IP。"
                    else:
                        if not self._zc:
                            self._zc = Zeroconf(interfaces=list(addresses), ip_version=IPVersion.V4Only)
                            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE, self)
                        with self._condition:
                            settings = self._settings
                        if published != settings:
                            name, operating_system, identity, port, role = settings
                            instance = f"deskbridge-{identity[:16]}.{SERVICE_TYPE}"
                            info = ServiceInfo(SERVICE_TYPE, instance,
                                               addresses=[socket.inet_aton(a) for a in addresses], port=port,
                                               properties={"protocol": "1", "name": name, "os": operating_system,
                                                           "fingerprint": identity, "role": role},
                                               server=f"deskbridge-{identity[:16]}.local.", host_ttl=30, other_ttl=30)
                            if self._info:
                                self._zc.update_service(info)
                            else:
                                self._zc.register_service(info)
                            self._info, published = info, settings
                        self.status = "自动发现已开启 · DHCP 地址变化会自动更新"
                        with self._condition:
                            now = time.monotonic()
                            self._targets = {s: seen for s, seen in self._targets.items() if now-seen < 60}
                            self._services = {s: seen for s, seen in self._services.items()
                                              if now-max(seen, self._peers[s].seen if s in self._peers else 0) < 60}
                            targets = sorted(self._targets, key=self._targets.get, reverse=True)[:2]
                            names = [s for s in self._services if s not in targets]
                        # Refresh a bounded batch; a stale service does not live forever.
                        # A connect request must not wait behind a busy browse
                        # cache: reserve two of the four slots for paired targets.
                        count = 4-len(targets)
                        for service in [*targets, *(names[cursor:cursor+count] if names else [])]:
                            self._refresh(self._zc, service)
                        cursor = (cursor+count) % max(1, len(names))
                except Exception as exc:
                    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
                    self.status = f"组播发现暂不可用（{type(exc).__name__}{' '+str(code) if code else ''}）；可尝试电脑名自动寻址。"
                    self._release_network()
                    active_addresses, published = (), None
                self._wake.wait(self.REFRESH_SECONDS)
                self._wake.clear()
                # Coalesce event storms to bounded work even with cached answers.
                self._stop.wait(.1)
        except ImportError:
            self.status = "缺少组播发现组件；可尝试电脑名自动寻址。"
        finally:
            self._release_network()

    def close(self):
        self._stop.set()
        self._wake.set()
        self._dns_wake.set()
        with self._condition:
            self._condition.notify_all()
        self._thread.join(timeout=4)
        self._dns_thread.join(timeout=.1)
