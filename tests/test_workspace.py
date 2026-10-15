import copy
from pathlib import Path
import tempfile
import unittest
import os
from deskbridge.mailbox import EventMailbox

from deskbridge.core import prepare, qvalue
from deskbridge.identity import Identity
from deskbridge.model import Device, Workspace, fingerprint, lan_address
from deskbridge.storage import Profile


class WorkspaceTests(unittest.TestCase):
    def test_single_paired_server_default_and_explicit_choice(self):
        value = Workspace("Mac", [Device("Mac", "macOS", 1, 1), Device("PC", "Windows", 2, 1, "a"*64)], mode="client", server_name="")
        value.select_single_server()
        self.assertEqual(value.server_name, "PC")
        value.validate(ready=True)
        value.devices.append(Device("Other", "Windows", 3, 1, "b"*64))
        value.server_name = "Other"
        value.select_single_server()
        self.assertEqual(value.server_name, "Other")
        value.server_name = ""
        value.select_single_server()
        self.assertEqual(value.server_name, "")
        with self.assertRaises(ValueError): value.validate(ready=True)
        value.devices[1].fingerprint = value.devices[2].fingerprint = ""
        value.select_single_server()
        self.assertEqual(value.server_name, "")
    def test_logs_cannot_evict_lifecycle_completion(self):
        events = EventMailbox(max_logs=16)
        events.put_nowait(("ready", ""))
        events.put_nowait(("exit", "finished"))
        for index in range(1000):
            events.put_nowait(("log", str(index)))
            events.put_nowait(("status", str(index)))
        self.assertEqual(len(events.logs), 16)
        result = {}
        while not events.empty():
            kind, text = events.get_nowait()
            result[kind] = text
        self.assertIn("ready", result)
        self.assertEqual(result["exit"], "finished")
        self.assertEqual(result["status"], "999")

    def workspace(self):
        return Workspace("WindowsPC", [Device("WindowsPC", "Windows", 1, 1),
                                       Device("Mac", "macOS", 2, 1, "a"*64),
                                       Device("Linux", "Ubuntu", 2, 2, "b"*64)])

    def test_reciprocal_links_and_return_hotkey(self):
        w = self.workspace()
        w.validate(ready=True)
        conf = w.server_config()
        self.assertIn("right = Mac", conf)
        self.assertIn("left = WindowsPC", conf)
        self.assertIn("down = Linux", conf)
        self.assertIn("up = Mac", conf)
        self.assertIn("switchToScreen(WindowsPC)", conf)

    def test_injection_in_names_is_rejected(self):
        for name in ("end\nsection: options", "PC;exec", "../../computer", "PC=other", "PC\r\n"):
            with self.subTest(name=name):
                w = self.workspace()
                w.devices[1].name = name
                with self.assertRaises(ValueError):
                    w.server_config()

    def test_disconnected_layout_cannot_start(self):
        w = self.workspace()
        w.devices[-1].x, w.devices[-1].y = 4, 2
        with self.assertRaises(ValueError):
            w.validate(ready=True)

    def test_casefold_duplicate_and_overlapping_cells(self):
        for field, value in (("name", "windowspc"), ("x", 1)):
            w = self.workspace()
            setattr(w.devices[1], field, value)
            with self.assertRaises(ValueError):
                w.validate()

    def test_empty_and_reused_peer_fingerprints(self):
        for value in ("", "b"*64):
            w = self.workspace()
            w.devices[1].fingerprint = value
            with self.assertRaises(ValueError):
                w.validate(ready=True)

    def test_client_must_choose_remote_server(self):
        w = self.workspace()
        w.mode, w.server_name = "client", "WindowsPC"
        with self.assertRaises(ValueError):
            w.validate(ready=True)
        w.server_name = "Mac"
        w.validate(ready=True)
        self.assertIn("switchToScreen(Mac)", w.server_config())

    def test_host_is_a_constrained_literal_not_a_url(self):
        for value in ("https://192.168.1.2", "metadata.google.internal", "169.254.169.254", "0.0.0.0", "8.8.8.8", "192.168.1.1,10.0.0.1", "192.168.1.1\nport=80"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lan_address(value)
        self.assertEqual(lan_address("192.168.1.20"), "192.168.1.20")

    def test_fingerprint_normalization_and_invalid_values(self):
        self.assertEqual(fingerprint(":".join(["AB"]*32)), "ab"*32)
        for value in ("ab"*20, "g"*64, "a"*64+"\nnext"):
            with self.assertRaises(ValueError):
                fingerprint(value)

    def test_schema_size_and_typed_fields(self):
        d = self.workspace().to_dict()
        for mutation in ({"schema": 2}, {"clipboard": "false"}, {"port": True}, {"unknown": 1}, {"devices": [{}]*9}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Workspace.from_dict({**d, **mutation})
        self.assertEqual(Workspace.from_dict(d).to_dict(), d)

    def test_qsettings_quotes_paths_and_rejects_controls(self):
        self.assertEqual(qvalue(r"D:\my folder\state.pem"), '"D:/my folder/state.pem"')
        with self.assertRaises(ValueError):
            qvalue("file\ncheckPeerFingerprints=false")


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="deskbridge-test-")
        self.root = Path(self.tmp.name) / "profile"
        self.profile = Profile(self.root)
        self.profile.acquire()

    def tearDown(self):
        self.profile.close()
        self.tmp.cleanup()

    def test_identity_is_stable_and_pair_files_are_scoped(self):
        identity = Identity(self.profile.tls)
        fp = identity.ensure()
        self.assertEqual(fp, identity.ensure())
        workspace = Workspace("PC", [Device("PC", "Windows", 1, 1), Device("Mac", "macOS", 2, 1, "a"*64)])
        path = prepare(self.profile, workspace, identity)
        text = path.read_text()
        self.assertIn("tlsEnabled=true", text)
        self.assertIn("checkPeerFingerprints=true", text)
        self.assertIn("enableClipboard=false", text)
        self.assertIn("clipboardSize=1024", text)
        self.assertIn("enableEnterCommand=false", text)
        self.assertIn("[computer_PC]\nname=\"PC\"", text)
        self.assertNotIn("section: screens", workspace.server_config())
        self.assertIn("v2:sha256:"+"a"*64, (self.profile.tls/"trusted-clients").read_text())
        self.assertEqual((self.profile.tls/"trusted-servers").read_text(), "")
        workspace.mode, workspace.server_name = "client", "Mac"
        prepare(self.profile, workspace, identity)
        self.assertIn('interface=""', (self.profile.root/"engine.ini").read_text())
        self.assertEqual((self.profile.tls/"trusted-clients").read_text(), "")
        self.assertIn("a"*64, (self.profile.tls/"trusted-servers").read_text())

    def test_own_identity_cannot_be_imported_as_peer(self):
        identity = Identity(self.profile.tls)
        workspace = Workspace("PC", [Device("PC", "Windows", 1, 1), Device("Mac", "macOS", 2, 1, identity.ensure())])
        with self.assertRaises(ValueError):
            prepare(self.profile, workspace, identity)

    def test_os_lock_and_config_roundtrip(self):
        other = Profile(self.root)
        try:
            with self.assertRaises(ValueError):
                other.acquire()
        finally:
            other.close()
        value = Workspace.new("Windows")
        self.profile.save(value)
        self.assertEqual(self.profile.load("Windows").to_dict(), value.to_dict())

    def test_reject_nonprofile_directory(self):
        folder = Path(self.tmp.name) / "unrelated"
        folder.mkdir()
        (folder / "other.txt").write_text("preserve this")
        with self.assertRaises(ValueError):
            Profile(folder)
        self.assertEqual((folder / "other.txt").read_text(), "preserve this")

    @unittest.skipUnless(os.name == "nt", "Windows DACL")
    def test_existing_explicit_world_read_is_removed(self):
        import ctypes
        import subprocess
        from ctypes import wintypes
        identity = Identity(self.profile.tls)
        identity.ensure()
        icacls = str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe")
        subprocess.run([icacls, str(identity.path), "/grant", "*S-1-1-0:R"], capture_output=True, check=True, timeout=5)
        other = Profile(self.root)
        other.close()
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_void_p)]
        adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                                            wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        descriptor, text = ctypes.c_void_p(), ctypes.c_void_p()
        self.assertEqual(adv.GetNamedSecurityInfoW(str(identity.path), 1, 4, None, None, None, None, ctypes.byref(descriptor)), 0)
        try:
            self.assertTrue(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(text), None))
            acl = ctypes.wstring_at(text.value)
            self.assertNotIn(";;;WD)", acl)
            self.assertNotIn("S-1-1-0", acl)
            self.assertEqual(acl.count("(A;"), 2)
        finally:
            kernel.LocalFree(text)
            kernel.LocalFree(descriptor)


if __name__ == "__main__":
    unittest.main()
