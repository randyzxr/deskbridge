from pathlib import Path
import os
import subprocess
import socket
import sys
import time
import unittest
from unittest.mock import patch

from deskbridge.core import CoreProcess, check_engine, find_engine
from deskbridge.discovery import decode_peer, hostname_addresses, LanDiscovery, SERVICE_TYPE
from deskbridge.model import Device, Workspace
from deskbridge.process_env import external_environment


class Info:
    name = "test."+SERVICE_TYPE
    port = 24800
    def __init__(self, addresses=None, **properties):
        self.properties = {b"protocol": b"1", b"name": b"Mac", b"os": b"macOS",
                           b"role": b"server", b"fingerprint": b"a"*64}
        self.properties.update({k.encode(): v.encode() for k, v in properties.items()})
        self.addresses = addresses or ["192.168.10.4"]
    def parsed_addresses(self):
        return self.addresses


class NetworkTests(unittest.TestCase):
    def quiet_discovery(self, **kwargs):
        return LanDiscovery("PC", "Windows", "b"*64, 24800, "client", **kwargs)

    def test_hostname_fallback_works_without_any_mdns_record(self):
        with patch.object(LanDiscovery, "_work", lambda obj: obj._stop.wait()), \
             patch("deskbridge.discovery.hostname_addresses", return_value=("10.5.154.94",)):
            discovery = self.quiet_discovery()
            try:
                self.assertEqual(discovery.resolve("a"*64, "Mac", timeout=1), ("10.5.154.94", 24800))
                self.assertEqual(discovery.snapshot(), [])
                self.assertEqual(discovery._settings[2], "b"*64)
            finally:
                discovery.close()

    def test_slow_dns_does_not_extend_discovery_deadline(self):
        import threading
        release = threading.Event()
        def slow(*args):
            release.wait(2)
            return ("10.5.154.94",)
        with patch.object(LanDiscovery, "_work", lambda obj: obj._stop.wait()), \
             patch("deskbridge.discovery.hostname_addresses", slow):
            discovery = self.quiet_discovery()
            try:
                started = time.monotonic()
                self.assertIsNone(discovery.resolve("a"*64, "Mac", timeout=.1))
                self.assertLess(time.monotonic()-started, .5)
            finally:
                release.set()
                discovery.close()

    def test_hostname_results_reject_any_non_lan_or_loopback_address(self):
        for addresses in (("8.8.8.8",), ("10.5.154.94", "169.254.169.254"), ("127.0.0.1",)):
            records = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (a, 24800)) for a in addresses]
            with patch("socket.getaddrinfo", return_value=records), self.assertRaises(ValueError):
                hostname_addresses("Mac", 24800)

    def test_role_or_identity_conflict_is_not_hidden_by_dns_fallback(self):
        with patch.object(LanDiscovery, "_work", lambda obj: obj._stop.wait()), \
             patch("deskbridge.discovery.hostname_addresses", return_value=("10.5.154.94",)):
            discovery = self.quiet_discovery()
            try:
                discovery._peers["role"] = decode_peer(Info(role="client"))
                self.assertIsNone(discovery.resolve("a"*64, "Mac", timeout=.1))
                self.assertIn("接收模式", discovery.explain_missing("a"*64, "Mac"))
                discovery._peers.clear()
                discovery._peers["identity"] = decode_peer(Info(fingerprint="c"*64))
                self.assertIsNone(discovery.resolve("a"*64, "Mac", timeout=.1))
                self.assertIn("指纹", discovery.explain_missing("a"*64, "Mac"))
            finally:
                discovery.close()

    def test_first_mdns_timeout_is_retried_and_target_is_queried(self):
        from unittest.mock import Mock
        calls = []
        service = f"deskbridge-{'a'*16}.{SERVICE_TYPE}"
        class FakeZeroconf:
            def __init__(self, **kwargs): pass
            def register_service(self, info): pass
            def update_service(self, info): pass
            def unregister_service(self, info): pass
            def close(self): pass
            def get_service_info(self, type_, name, timeout):
                calls.append(name)
                if calls.count(name) == 1: return None
                info = Info()
                info.name = name
                return info
        with patch("zeroconf.Zeroconf", FakeZeroconf), patch("zeroconf.ServiceBrowser", Mock()), \
             patch("deskbridge.discovery.local_addresses", return_value=("192.168.10.2",)), \
             patch("deskbridge.discovery.hostname_addresses", side_effect=socket.gaierror), \
             patch.object(LanDiscovery, "REFRESH_SECONDS", .05):
            discovery = self.quiet_discovery()
            try:
                discovery.add_service(None, SERVICE_TYPE, "delayed."+SERVICE_TYPE)
                self.assertEqual(discovery.resolve("a"*64, "Mac", timeout=2), ("192.168.10.4", 24800))
                self.assertIn(service, calls)
                deadline = time.monotonic()+1
                while calls.count("delayed."+SERVICE_TYPE) < 2 and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertGreaterEqual(calls.count("delayed."+SERVICE_TYPE), 2)
            finally:
                discovery.close()

    def workspace(self):
        return Workspace("PC", [Device("PC", "Windows", 1, 1), Device("Mac", "macOS", 2, 1, "a"*64)],
                         mode="client", server_name="Mac", automatic_network=True, address="")

    def test_automatic_config_does_not_persist_a_dhcp_address(self):
        workspace = self.workspace()
        workspace.validate(ready=True)
        self.assertEqual(workspace.to_dict()["address"], "")
        self.assertEqual(Workspace.from_dict(workspace.to_dict()).address, "")

    def test_address_is_re_resolved_by_paired_identity(self):
        from unittest.mock import Mock
        discovery = Mock()
        discovery.resolve.side_effect = [("192.168.10.4", 24800), ("192.168.10.25", 24800)]
        desired = self.workspace()
        first = CoreProcess.runtime_workspace(desired, discovery)
        second = CoreProcess.runtime_workspace(desired, discovery)
        self.assertNotEqual(first.address, second.address)
        self.assertEqual(desired.address, "")
        self.assertEqual(second.devices[1].fingerprint, "a"*64)
        self.assertEqual(discovery.resolve.call_args.args, ("a"*64, "Mac"))

    def test_absent_or_invalid_discovered_peer_cannot_launch(self):
        from unittest.mock import Mock
        discovery = Mock()
        for endpoint in (None, ("8.8.8.8", 24800), ("169.254.169.254", 24800), ("192.168.1.2", 80)):
            discovery.resolve.return_value = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                CoreProcess.runtime_workspace(self.workspace(), discovery)

    def test_discovery_metadata_is_not_a_trust_grant(self):
        peer = decode_peer(Info(["8.8.8.8", "192.168.10.4", "169.254.169.254"]))
        self.assertEqual(peer.addresses, ("192.168.10.4",))
        self.assertEqual(peer.fingerprint, "a"*64)
        for info in (Info(name="PC\nend"), Info(fingerprint="bad"), Info(role="admin"), Info(protocol="99"), Info(["8.8.8.8"])):
            with self.assertRaises(ValueError):
                decode_peer(info)

    def test_discovered_endpoint_prefers_the_shared_subnet(self):
        from types import SimpleNamespace
        from deskbridge.discovery import preferred_address
        adapter = SimpleNamespace(ips=[SimpleNamespace(ip="192.168.10.100", network_prefix=24)])
        with patch("ifaddr.get_adapters", return_value=[adapter]):
            self.assertEqual(preferred_address(("10.8.0.1", "192.168.10.4")), "192.168.10.4")

    def test_child_environment_keeps_parent_environment_unchanged(self):
        root = str(Path.cwd()/"fake-bundle")
        original = {"PATH": root+os.pathsep+str(Path(root)/"plugins")+os.pathsep+str(Path.cwd()/"system-tools"),
                    "OPENSSL_MODULES": str(Path(root)/"providers")}
        with patch.object(sys, "_MEIPASS", root, create=True), patch.dict(os.environ, original):
            clean = external_environment()
            self.assertNotIn(root, clean["PATH"])
            self.assertNotIn("OPENSSL_MODULES", clean)
            self.assertEqual(os.environ["PATH"], original["PATH"])

    def test_dhcp_change_reopens_mdns_interfaces_with_same_identity(self):
        from deskbridge.discovery import LanDiscovery
        registrations, opened, closed = [], [], []
        class FakeZeroconf:
            def __init__(self, **kwargs):
                opened.append(tuple(kwargs["interfaces"]))
            def register_service(self, info): registrations.append(info)
            def update_service(self, info): registrations.append(info)
            def unregister_service(self, info): pass
            def close(self): closed.append(True)
        calls = 0
        def addresses():
            nonlocal calls
            calls += 1
            return ("192.168.10.4",) if calls == 1 else ("192.168.10.25",)
        with patch("zeroconf.Zeroconf", FakeZeroconf), patch("zeroconf.ServiceBrowser"), \
             patch("deskbridge.discovery.local_addresses", addresses), patch.object(LanDiscovery, "REFRESH_SECONDS", .05):
            discovery = LanDiscovery("PC", "Windows", "a"*64, 24800, "server")
            try:
                deadline = time.monotonic()+2
                while len(registrations)<2 and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertEqual(opened[:2], [("192.168.10.4",), ("192.168.10.25",)])
                self.assertEqual(registrations[0].properties[b"fingerprint"], registrations[1].properties[b"fingerprint"])
                self.assertEqual(registrations[1].parsed_addresses(), ["192.168.10.25"])
            finally:
                discovery.close()
            self.assertEqual(len(closed), len(opened))

    @unittest.skipUnless(os.name == "nt", "Windows loader")
    def test_windows_child_dll_search_is_restored_after_native_probe(self):
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
        api.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
        buffer = ctypes.create_unicode_buffer(32768)
        api.GetDllDirectoryW(len(buffer), buffer)
        original = buffer.value or None
        old_bundle = Path(__file__).resolve().parent.parent/"dist/DeskBridge/_internal"
        if not (old_bundle/"icuuc.dll").is_file():
            self.skipTest("Original failing ICU fixture unavailable")
        try:
            self.assertTrue(api.SetDllDirectoryW(str(old_bundle)))
            self.assertTrue(check_engine(find_engine()).is_file())
            api.GetDllDirectoryW(len(buffer), buffer)
            self.assertEqual(buffer.value, str(old_bundle))
        finally:
            api.SetDllDirectoryW(original)


if __name__ == "__main__":
    unittest.main()
