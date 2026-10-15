import json
from pathlib import Path
import tempfile
import unittest
import os
from deskbridge.identity import Identity
from deskbridge.lock_service import current_owner_sid, export_receiver
from deskbridge.model import Workspace, Device
from deskbridge.storage import Profile


class LockServiceTests(unittest.TestCase):
    def test_private_ipc_change_is_one_byte_and_unknown_build_is_rejected(self):
        from tools.private_ipc import private_ipc, OPTION_OFFSET
        source = Path(__file__).resolve().parent.parent/"vendor/deskflow/deskflow-1.27.0-win-x64-portable/deskflow-core.exe"
        if not source.exists(): self.skipTest("Fixed Windows native fixture unavailable")
        data = source.read_bytes()
        changed = private_ipc(data)
        self.assertEqual([i for i, (a, b) in enumerate(zip(data, changed)) if a != b], [OPTION_OFFSET])
        self.assertEqual(changed[OPTION_OFFSET], 1)
        with self.assertRaises(ValueError): private_ipc(data+b"changed")

    def value(self):
        return Workspace("Receiver", [Device("Receiver", "Windows", 1, 1), Device("Shared", "Windows", 2, 1, "a"*64)],
                         mode="client", automatic_network=True, address="", server_name="")

    def test_export_keeps_identity_and_excludes_user_commands_or_addresses(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Profile(Path(folder)/"profile")
            identity = Identity(profile.tls)
            own = identity.ensure()
            before = identity.path.read_bytes()
            sid = current_owner_sid() if os.name == "nt" else "S-1-5-21-1"
            value = self.value()
            target = export_receiver(profile, value, identity, sid)
            data = json.loads((target/"service.json").read_text())
            self.assertEqual(set(data), {"schema", "owner_sid", "local_name", "server_name", "server_fp", "local_fp", "port"})
            self.assertEqual(data["server_name"], "Shared")
            self.assertEqual(data["local_fp"], own)
            self.assertEqual((target/"deskbridge.pem").read_bytes(), before)
            self.assertEqual(identity.path.read_bytes(), before)
            self.assertEqual(value.server_name, "")
            self.assertEqual(value.address, "")

    def test_server_mode_invalid_owner_and_reused_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Profile(Path(folder)/"profile")
            identity = Identity(profile.tls)
            value = self.value()
            value.mode = "server"
            with self.assertRaises(ValueError): export_receiver(profile, value, identity, "S-1-5-21-1")
            value.mode = "client"
            with self.assertRaises(ValueError): export_receiver(profile, value, identity, "S-1-5-18\n")
            value.devices[1].fingerprint = identity.ensure()
            with self.assertRaises(ValueError): export_receiver(profile, value, identity, "S-1-5-21-1")


if __name__ == "__main__": unittest.main()
