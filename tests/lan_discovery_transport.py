"""Real LanDiscovery on loopback multicast, with system DNS disabled."""
from pathlib import Path
import hashlib
import socket
import sys
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.discovery import LanDiscovery, SERVICE_TYPE
from zeroconf import IPVersion, ServiceInfo, Zeroconf


def run():
    identity = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    local = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    instance = f"deskbridge-{identity[:16]}.{SERVICE_TYPE}"
    publisher = Zeroconf(interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only)
    def info(role):
        return ServiceInfo(SERVICE_TYPE, instance, addresses=[socket.inet_aton("192.168.56.10")],
                           port=24800, properties={"protocol": "1", "name": "TestPeer", "os": "Windows",
                                                  "role": role, "fingerprint": identity},
                           server=f"deskbridge-{identity[:16]}.local.", host_ttl=30, other_ttl=30)
    current = info("server")
    registered = False
    with patch("deskbridge.discovery.local_addresses", return_value=("127.0.0.1",)), \
         patch("deskbridge.discovery.hostname_addresses", side_effect=socket.gaierror):
        discovery = LanDiscovery("Observer", "Windows", local, 24800, "client")
        try:
            publisher.register_service(current)
            registered = True
            assert discovery.resolve(identity, "TestPeer", timeout=8) == ("192.168.56.10", 24800)
            current = info("client")
            publisher.update_service(current)
            deadline = time.monotonic()+8
            while time.monotonic()<deadline:
                peers = discovery.snapshot()
                if any(p.fingerprint == identity and p.role == "client" for p in peers):
                    break
                time.sleep(.1)
            else:
                raise AssertionError("Updated role was not observed")
            assert discovery.resolve(identity, "TestPeer", timeout=.1) is None
            assert "接收模式" in discovery.explain_missing(identity, "TestPeer")
            print("PASS: production mDNS discovery resolves pinned metadata and observes role updates on loopback")
        finally:
            discovery.close()
            if registered:
                publisher.unregister_service(current)
            publisher.close()


if __name__ == "__main__":
    run()
