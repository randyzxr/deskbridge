# Third-party software

The independently implemented DeskBridge Python controller is MIT licensed.
The ordinary desktop controller executes an unmodified, separately distributed Deskflow core; it does not contain
Synergy's commercial UI, account service or license mechanisms.

The optional 0.3.0 Windows receiver service uses a modified copy of deskflow-core.exe: QLocalServer socket permission changes from WorldAccessOption to UserAccessOption before listen(). The distribution includes the corresponding `service/private-ipc-source.patch`, fixed artifact preconditions in `tools/private_ipc.py`, and digests in `service/private-ipc-evidence.json`. Base corresponding source is `third_party/deskflow-1.27.0-source.tar.gz`; apply the supplied source patch for the changed IPC behavior. This service engine is not an official unmodified Deskflow binary. The Deskflow license and exception continue to apply.

- Deskflow 1.27.0: https://github.com/deskflow/deskflow/tree/v1.27.0
  Source commit: 081f6478e654a112168879e67a41ce7d7e4ae3af.
  GPL-2.0-only with OpenSSL exception; retain the original LICENSE,
  LICENSE_EXCEPTION and all resources required by the selected core. Corresponding core source is also
  supplied in third_party/deskflow-1.27.0-source.tar.gz in the Windows delivery.
- The original portable engine includes Qt 6 and OpenSSL libraries and Microsoft
  runtime components under their respective licenses. See the upstream source's
  REUSE.toml, LICENSES/ and packaging/build configuration. Do not remove the core's
  notices or substitute binary dependencies without updating the source and licenses.
  Qt source: https://download.qt.io/official_releases/qt/
  OpenSSL source: https://www.openssl.org/source/
- Python 3.12: https://www.python.org/downloads/source/ (PSF license).
- Tcl/Tk: BSD-style terms included in vendor/tcl/*/license.terms and the frozen bundle.
- cryptography 50.0.2: Apache-2.0 OR BSD-3-Clause.
  https://github.com/pyca/cryptography
- zeroconf 0.151.5: LGPL-2.1-or-later, https://github.com/python-zeroconf/python-zeroconf
- ifaddr 0.2.0: MIT, https://github.com/pydron/ifaddr
- PyInstaller 6.22.3 (build tool): GPL-2.0-or-later with its bootloader exception.
  https://pyinstaller.org/en/stable/license.html

This is an internal development MVP, not a legal determination of redistribution
compliance. Before public/commercial release, review the exact bundled dependency
versions and ensure all required notices and corresponding-source obligations are met.

0.3.1 Windows repackaging omits the separate upstream deskflow.exe GUI, GUI
translations, Qt6Svg and unused image/icon/style/generic plugins. Ordinary
deskflow-core.exe and every retained native library are byte-for-byte copies of
the verified upstream release. Engine inventory and omitted paths are recorded in
engine-inventory.json. Platform, network and TLS plugins and license files remain.
Only the already documented service-specific core has the private IPC patch.
