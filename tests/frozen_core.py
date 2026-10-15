"""TLS regression from the packaged controller, not a source Python launch."""
from pathlib import Path
import hashlib
import socket
import ssl
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deskbridge.identity import Identity
from deskbridge.model import Device, Workspace
from deskbridge.storage import Profile, atomic_write


def run(executable):
    executable = Path(executable).resolve(strict=True)
    doctor = subprocess.run([str(executable), "--doctor"], timeout=10)
    assert doctor.returncode == 0, f"Frozen core version probe failed: {doctor.returncode}"
    with tempfile.TemporaryDirectory(prefix="frozen-tls-", dir=Path(__file__).resolve().parent.parent/"build") as folder:
        profiles = [Profile(Path(folder)/name) for name in ("primary", "allowed", "stranger")]
        identities = [Identity(p.tls) for p in profiles]
        local_fp, allowed_fp, _ = [i.ensure() for i in identities]
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        engine = next((executable.parent/"engine").glob("*/deskflow-core.exe"))
        primary = profiles[0]
        primary.save(Workspace("Primary", [Device("Primary", "Windows", 2, 1), Device("Peer", "macOS", 3, 1, allowed_fp)],
                               address="127.0.0.1", port=port, engine=str(engine)))
        proc = subprocess.Popen([str(executable), "--profile", str(primary.root), "--run"], stdin=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+10
            while True:
                assert proc.poll() is None, "Frozen controller exited before listening"
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    if time.monotonic()>deadline:
                        raise AssertionError("Frozen core never listened")
                    time.sleep(.1)
            def connect(identity):
                context = ssl.create_default_context(cafile=str(identities[0].path))
                context.load_cert_chain(str(identity.path))
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                raw = socket.create_connection(("127.0.0.1", port), timeout=3)
                try:
                    channel = context.wrap_socket(raw, server_hostname="DeskBridge device")
                    assert hashlib.sha256(channel.getpeercert(binary_form=True)).hexdigest() == local_fp
                    return channel
                except BaseException:
                    raw.close()
                    raise
            def reject(identity):
                try:
                    with connect(identity) as channel:
                        assert not channel.recv(128), "Untrusted/revoked peer received protocol data"
                except (ssl.SSLError, ConnectionResetError):
                    pass
            reject(identities[2])
            with connect(identities[1]) as channel:
                assert b"Barrier" in channel.recv(128)
            atomic_write(primary.tls/"trusted-clients", b"")
            reject(identities[1])
            print("PASS: packaged EXE version probe + actual core TLS trust/reject/revoke; no input events injected")
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
            for profile in profiles:
                profile.close()
        deadline = time.monotonic()+5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.3):
                    pass
            except OSError:
                break
            if time.monotonic()>deadline:
                raise AssertionError("Child core remained listening after packaged controller exit")
            time.sleep(.1)
        print("PASS: packaged parent exit closes its native child core")


if __name__ == "__main__":
    run(sys.argv[1])
