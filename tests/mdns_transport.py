"""Loopback-only multicast transport; advertises synthetic test endpoints."""
from pathlib import Path
import hashlib
import socket
import sys
import threading
import uuid
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.discovery import SERVICE_TYPE, decode_peer
from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf


def run():
    token = uuid.uuid4().hex
    identity = hashlib.sha256(token.encode()).hexdigest()
    service = f"test-{token}.{SERVICE_TYPE}"
    event, found = threading.Event(), []
    class Listener:
        def add_service(self, zc, type_, name): self.update_service(zc, type_, name)
        def update_service(self, zc, type_, name):
            if name != service:
                return
            info = zc.get_service_info(type_, name, timeout=1000)
            if info:
                found.append(decode_peer(info))
                event.set()
        def remove_service(self, zc, type_, name): pass
    publisher = Zeroconf(interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only)
    observer = Zeroconf(interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only)
    browser = ServiceBrowser(observer, SERVICE_TYPE, Listener())
    def info(address):
        return ServiceInfo(SERVICE_TYPE, service, addresses=[socket.inet_aton(address)], port=24800,
                           properties={"protocol": "1", "name": "TestPC", "os": "Windows", "role": "server", "fingerprint": identity},
                           server=f"test-{token}.local.", host_ttl=30, other_ttl=30)
    current = info("192.168.56.10")
    try:
        publisher.register_service(current)
        assert event.wait(8), "mDNS advertisement was not observed on loopback"
        assert found[-1].addresses == ("192.168.56.10",)
        event.clear()
        # Match the production DHCP path: retire the old interface/advertisement
        # before publishing the same device identity on the replacement address.
        publisher.unregister_service(current)
        publisher.close()
        publisher = Zeroconf(interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only)
        current = info("192.168.56.25")
        publisher.register_service(current)
        # A multicast cache-flush may briefly retain the previous A record.
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            observed = observer.get_service_info(SERVICE_TYPE, service, timeout=500)
            if observed:
                peer = decode_peer(observed)
                if peer.addresses == ("192.168.56.25",):
                    break
            time.sleep(.2)
        else:
            raise AssertionError("mDNS changed endpoint did not replace the previous address")
        assert peer.fingerprint == identity
        print("PASS: real loopback mDNS advertisement and address update preserve device identity")
    finally:
        browser.cancel()
        publisher.unregister_service(current)
        publisher.close()
        observer.close()


if __name__ == "__main__":
    run()
