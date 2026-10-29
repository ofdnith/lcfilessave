"""Own HTTPS certificate authority, so the iPhone PWA works (Safari requires
HTTPS for service workers) both at home and through Tailscale.

`acervo certificado` creates:
  certificados/ca.crt      install this once on the iPhone and the Mac
  certificados/ca.key      stays on the server
  certificados/server.crt  for the names/IPs in tls_names (+ localhost)
  certificados/server.key

Needs the `cryptography` package (Termux: pkg install python-cryptography).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
from pathlib import Path


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Instale o pacote cryptography (Termux: pkg install python-cryptography)") from exc
    return x509, hashes, serialization, ec, NameOID, ExtendedKeyUsageOID


def _write_key(path: Path, key, serialization) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)


def generate(cert_dir: Path, names: list[str]) -> Path:
    x509, hashes, serialization, ec, NameOID, EKU = _crypto()
    cert_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)

    ca_key_path, ca_crt_path = cert_dir / "ca.key", cert_dir / "ca.crt"
    if ca_key_path.exists() and ca_crt_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(ca_crt_path.read_bytes())
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Acervo — autoridade local"),
                             x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acervo")])
        ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
                   .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                                content_commitment=False, key_encipherment=False,
                                                data_encipherment=False, key_agreement=False,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .sign(ca_key, hashes.SHA256()))
        _write_key(ca_key_path, ca_key, serialization)
        ca_crt_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    sans = []
    for name in dict.fromkeys(["localhost", "127.0.0.1", *names]):
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            sans.append(x509.DNSName(name))
    key = ec.generate_private_key(ec.SECP256R1())
    # Apple accepts at most 825 days for server certificates.
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if names else "localhost")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=800))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([EKU.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            # Strict TLS clients (Python 3.13+, recent Apple systems) require these identifiers.
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key(cert_dir / "server.key", key, serialization)
    (cert_dir / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return ca_crt_path
