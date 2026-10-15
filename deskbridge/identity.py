from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

from .storage import atomic_write, safe_file


class Identity:
    def __init__(self, tls: Path):
        self.path = tls / "deskbridge.pem"

    def ensure(self) -> str:
        safe_file(self.path)
        if not self.path.exists():
            now = datetime.now(timezone.utc)
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DeskBridge device")])
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
                    .sign(key, hashes.SHA256()))
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
            pem += cert.public_bytes(serialization.Encoding.PEM)
            atomic_write(self.path, pem)
        return self.fingerprint()

    def fingerprint(self) -> str:
        safe_file(self.path)
        if self.path.stat().st_size > 16384:
            raise ValueError("身份文件超过大小上限。")
        data = self.path.read_bytes()
        cert = x509.load_pem_x509_certificate(data)
        key = serialization.load_pem_private_key(data, password=None)
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise ValueError("本机证书与私钥不匹配。")
        now = datetime.now(timezone.utc)
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError("本机证书已过期或未生效。请停止共享后重新生成身份，并在其他设备重新配对。")
        return cert.fingerprint(hashes.SHA256()).hex()
