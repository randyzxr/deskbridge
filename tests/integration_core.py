"""Opt-in: real pinned Windows core + loopback TLS, no injected input events."""
from pathlib import Path
import hashlib
import queue
import socket
import ssl
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.core import CoreProcess, find_engine
from deskbridge.identity import Identity
from deskbridge.model import Device, Workspace
from deskbridge.storage import Profile, atomic_write


def collect(core, lines, until, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _, text = core.events.get(timeout=.1)
            lines.append(text)
            if until(text):
                return text
        except queue.Empty:
            pass
        if not core.running:
            raise AssertionError("core exited: " + "\n".join(lines))
    raise AssertionError("expected core status not seen: " + "\n".join(lines))


def run():
    core, logs = CoreProcess(), []
    with tempfile.TemporaryDirectory(prefix="deskbridge-integration-", dir=Path(__file__).resolve().parent.parent / "build") as folder:
        base = Path(folder)
        primary, allowed, stranger = [Profile(base/name) for name in ("primary", "allowed", "stranger")]
        identities = [Identity(p.tls) for p in (primary, allowed, stranger)]
        local_fp, allowed_fp, _ = [i.ensure() for i in identities]
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        workspace = Workspace("Primary", [Device("Primary", "Windows", 2, 1), Device("Peer", "macOS", 3, 1, allowed_fp)],
                              port=port, engine=find_engine())
        try:
            core.start(primary, workspace, identities[0])
            collect(core, logs, lambda text: "clipboard sharing is disabled" in text.lower())
            deadline = time.monotonic() + 8
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.3):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.1)

            def connect(identity):
                context = ssl.create_default_context(cafile=str(identities[0].path))
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(str(identity.path))
                raw = socket.create_connection(("127.0.0.1", port), timeout=3)
                try:
                    channel = context.wrap_socket(raw, server_hostname="DeskBridge device")
                    assert hashlib.sha256(channel.getpeercert(binary_form=True)).hexdigest() == local_fp
                    return channel
                except Exception:
                    raw.close()
                    raise

            try:
                with connect(identities[2]) as channel:
                    try:
                        data = channel.recv(128)
                        assert not data, "untrusted certificate received protocol bytes"
                    except (ssl.SSLError, ConnectionResetError):
                        pass
            except (ssl.SSLError, ConnectionResetError):
                pass
            collect(core, logs, lambda text: "fingerprint" in text.lower() and ("not trusted" in text.lower() or "not in" in text.lower() or "does not" in text.lower()))
            with connect(identities[1]) as channel:
                packet = channel.recv(128)
                assert b"Barrier" in packet, repr(packet)
                collect(core, logs, lambda text: "accepted secure socket" in text.lower())
            atomic_write(primary.tls / "trusted-clients", b"")
            try:
                with connect(identities[1]) as channel:
                    try:
                        assert not channel.recv(128), "removed peer still received protocol hello"
                    except (ssl.SSLError, ConnectionResetError):
                        pass
            except (ssl.SSLError, ConnectionResetError):
                pass
            match = collect(core, logs, lambda text: "failed to open trusted fingerprints file" in text.lower())
            assert str(primary.tls / "trusted-clients").replace("\\", "/") in match.replace("\\", "/"), "core did not use isolated trust database"
            print("PASS: real core started, isolated trust DB, untrusted peer rejected, trusted peer received TLS protocol hello")
            print("No keyboard/mouse input was injected. Cross-machine platform tests remain pending.")
        finally:
            core.stop()
            for profile in (primary, allowed, stranger):
                profile.close()


if __name__ == "__main__":
    run()
