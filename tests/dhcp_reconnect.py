"""Simulate a DHCP endpoint move using two loopback TLS listeners; no input."""
from pathlib import Path
import hashlib
import socket
import ssl
import sys
import tempfile
import threading
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.core import CoreProcess, find_engine
from deskbridge.identity import Identity
from deskbridge.model import Device, Workspace
from deskbridge.storage import Profile
from deskbridge.discovery import LanDiscovery


class TLSListener:
    def __init__(self, address, port, identity, client):
        self.socket = socket.socket()
        self.socket.bind((address, port))
        self.socket.listen(2)
        self.socket.settimeout(.2)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(identity.path))
        self.context.load_verify_locations(cafile=str(client.path))
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.expected = client.fingerprint()
        self.connected, self.stop = threading.Event(), threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            raw.settimeout(3)
            try:
                with self.context.wrap_socket(raw, server_side=True) as channel:
                    assert hashlib.sha256(channel.getpeercert(binary_form=True)).hexdigest() == self.expected
                    self.connected.set()
                    # No protocol hello, CINN, key, mouse or clipboard events.
                    self.stop.wait(15)
            except Exception as exc:
                self.error = exc

    def close(self):
        self.stop.set()
        self.socket.close()
        self.thread.join(timeout=4)


def run():
    core = CoreProcess()
    with tempfile.TemporaryDirectory(prefix="dhcp-reconnect-", dir=Path(__file__).resolve().parent.parent/"build") as folder:
        client_profile, server_profile = [Profile(Path(folder)/name) for name in ("client", "server")]
        client, server = Identity(client_profile.tls), Identity(server_profile.tls)
        client.ensure()
        server_fp = server.ensure()
        first = TLSListener("127.0.0.1", 0, server, client)
        port = first.socket.getsockname()[1]
        second = TLSListener("127.0.0.2", port, server, client)
        class DNSRoute:
            address = "127.0.0.1"
            def lookup(self, name, requested_port):
                assert name == "Peer" and requested_port == port
                return (self.address,)
        route = DNSRoute()
        stack = ExitStack()
        # Isolate transport to loopback; exercise the production DNS worker,
        # resolver and core restart path without changing actual DHCP or input.
        stack.enter_context(patch.object(LanDiscovery, "_work", lambda obj: obj._stop.wait()))
        stack.enter_context(patch("deskbridge.discovery.hostname_addresses", route.lookup))
        discovery = LanDiscovery("Client", "Windows", client.fingerprint(), port, "client")
        value = Workspace("Client", [Device("Client", "Windows", 1, 1), Device("Peer", "Windows", 2, 1, server_fp)],
                          mode="client", server_name="Peer", port=port, engine=find_engine(), automatic_network=True, address="")
        try:
            core.start(client_profile, value, client, discovery)
            assert first.connected.wait(8), f"Initial native client TLS connection failed: {first.error}"
            old_pid = core.process.pid
            route.address = "127.0.0.2"
            assert second.connected.wait(10), f"Native client did not follow the replacement endpoint: {second.error}"
            assert core.process.pid != old_pid
            assert value.address == ""
            assert (client_profile.tls/"trusted-servers").read_text().strip() == "v2:sha256:"+server_fp
            print("PASS: production hostname fallback and actual native client follow changed address with same pinned identity; no input events")
        finally:
            core.stop()
            discovery.close()
            stack.close()
            first.close()
            second.close()
            client_profile.close()
            server_profile.close()


if __name__ == "__main__":
    run()
