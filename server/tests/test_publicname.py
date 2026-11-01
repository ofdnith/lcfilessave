"""Trusted HTTPS through DuckDNS + Let's Encrypt (acervo/publicname.py)."""

from __future__ import annotations

import datetime as dt
import io
import ssl
import stat
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from acervo import publicname as pn
from acervo.config import Config

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
TOKEN = "a7c4d0ad-114e-40ef-ba1d-d217904a50f2"


def write_cert(crt: Path, key: Path, name: str, not_after: dt.datetime) -> None:
    """Self-signed stand-in for a Let's Encrypt certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    k = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(k.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_after - dt.timedelta(days=90)).not_valid_after(not_after)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(k, hashes.SHA256()))
    crt.parent.mkdir(parents=True, exist_ok=True)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))


@pytest.fixture
def https_cfg(tmp_path: Path) -> Config:
    acme = tmp_path / "acme"
    acme.mkdir()
    (acme / "acme.sh").write_text("#!/bin/sh\n")
    return Config(data_dir=tmp_path / "dados", workers=False, web_dir=tmp_path / "sem-web", https=True,
                  acme_home=acme)


class FakeDuckDNS:
    def __init__(self, answer: str = "OK"):
        self.answer, self.calls = answer, []

    def __call__(self, url: str, timeout: float):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.calls.append((q["domains"][0], q["ip"][0], q["token"][0]))
        return io.BytesIO(self.answer.encode())


class FakeAcme:
    """Records acme.sh calls; `--issue` writes a certificate like acme.sh would."""

    def __init__(self, returncode: int = 0, write: bool = True):
        self.returncode, self.write, self.calls = returncode, write, []

    def __call__(self, cmd, env, capture_output, text, timeout):
        self.calls.append(cmd)
        assert env["DuckDNS_Token"] == TOKEN
        if "--issue" in cmd and self.write and self.returncode == 0:
            name = cmd[cmd.index("-d") + 1]
            write_cert(Path(cmd[cmd.index("--fullchain-file") + 1]), Path(cmd[cmd.index("--key-file") + 1]),
                       name, NOW + dt.timedelta(days=90))
        return subprocess.CompletedProcess(cmd, self.returncode, "", "")


def addrs(lan="192.168.1.104", tailscale="100.71.3.9"):
    return lambda: {"lan": lan, "tailscale": tailscale}


# --- names, token, settings -------------------------------------------------------------

@pytest.mark.parametrize("raw, name", [
    ("fulano-casa", "fulano-casa"),
    ("  Fulano-Casa.duckdns.org ", "fulano-casa"),
    ("https://fulano.duckdns.org:8765/#/acervo", "fulano"),
])
def test_names_are_normalized(raw, name):
    assert pn.normalize_name(raw) == name


@pytest.mark.parametrize("raw", ["", "-x", "a..b", "nome com espaço", "x_y", "a" * 64, "../etc"])
def test_bad_names_are_refused(raw):
    with pytest.raises(pn.PublicNameError):
        pn.normalize_name(raw)


def test_token_must_look_like_a_duckdns_token():
    assert pn.normalize_token(f" {TOKEN}\n") == TOKEN
    with pytest.raises(pn.PublicNameError):
        pn.normalize_token("minha senha")


def test_settings_are_private_to_the_owner(https_cfg):
    path = pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa", "fulano"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert pn.load(https_cfg) == pn.DuckDNS(TOKEN, "fulano-casa", "fulano")
    assert pn.remove(https_cfg) and pn.load(https_cfg) is None


# --- addresses ---------------------------------------------------------------------------

def test_addresses_are_found_from_the_routing_table():
    routes = {"8.8.8.8": "192.168.1.104", "100.100.100.100": "100.71.3.9"}
    assert pn.detect_addresses(routes.get) == {"lan": "192.168.1.104", "tailscale": "100.71.3.9"}


def test_tailscale_off_or_exit_node_does_not_fool_detection():
    # Tailscale off: 100.100.100.100 leaves through the Wi-Fi, so the source is the LAN address.
    routes = {"8.8.8.8": "192.168.1.104", "100.100.100.100": "192.168.1.104"}
    assert pn.detect_addresses(routes.get) == {"lan": "192.168.1.104", "tailscale": None}
    # Exit node on: the internet goes through Tailscale; the LAN address comes from the router.
    routes = {"8.8.8.8": "100.71.3.9", "1.1.1.1": "100.71.3.9", "192.168.0.1": "192.168.1.104",
              "100.100.100.100": "100.71.3.9"}
    assert pn.detect_addresses(routes.get) == {"lan": "192.168.1.104", "tailscale": "100.71.3.9"}


def test_duckdns_points_each_name_at_its_address_and_only_again_when_it_changes(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa", "fulano"))
    duck = FakeDuckDNS()
    acme = FakeAcme()
    pn.upkeep(https_cfg, now=NOW, run=acme, opener=duck, detect=addrs())
    assert sorted(duck.calls) == [("fulano", "100.71.3.9", TOKEN), ("fulano-casa", "192.168.1.104", TOKEN)]

    duck.calls.clear()
    pn.upkeep(https_cfg, now=NOW + dt.timedelta(minutes=10), run=acme, opener=duck, detect=addrs())
    assert duck.calls == []  # nothing changed

    pn.upkeep(https_cfg, now=NOW + dt.timedelta(minutes=20), run=acme, opener=duck,
              detect=addrs(lan="192.168.1.120", tailscale=None))
    assert duck.calls == [("fulano-casa", "192.168.1.120", TOKEN)]  # Tailscale off: away name untouched


def test_refused_update_is_tried_again(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa"))
    duck = FakeDuckDNS("KO")
    pn.upkeep(https_cfg, now=NOW, run=FakeAcme(), opener=duck, detect=addrs())
    pn.upkeep(https_cfg, now=NOW + dt.timedelta(minutes=10), run=FakeAcme(), opener=duck, detect=addrs())
    assert len(duck.calls) == 2


# --- certificates -------------------------------------------------------------------------

def test_one_certificate_per_name_through_dns(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa", "fulano"))
    acme = FakeAcme()
    report = pn.upkeep(https_cfg, now=NOW, run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert report["issued"] == ["fulano-casa.duckdns.org", "fulano.duckdns.org"]
    for cmd in acme.calls:
        assert cmd[cmd.index("--dns") + 1] == "dns_duckdns"
        assert cmd[cmd.index("--server") + 1] == "letsencrypt"
        assert cmd.count("-d") == 1  # DuckDNS keeps one TXT record per name
        assert TOKEN not in cmd  # the token goes in the environment, not in `ps`
    assert stat.S_IMODE(pn.cert_paths(https_cfg, "fulano.duckdns.org")[1].stat().st_mode) == 0o600
    assert pn.addresses(https_cfg) == {"home": "https://fulano-casa.duckdns.org:8765",
                                       "away": "https://fulano.duckdns.org:8765"}

    acme.calls.clear()
    pn.upkeep(https_cfg, now=NOW + dt.timedelta(days=1), run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert acme.calls == []  # valid for 89 more days: nothing to do


def test_failed_certificate_waits_hours_before_trying_again(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa"))
    acme = FakeAcme(returncode=1)
    pn.upkeep(https_cfg, now=NOW, run=acme, opener=FakeDuckDNS(), detect=addrs())
    pn.upkeep(https_cfg, now=NOW + dt.timedelta(hours=1), run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert len(acme.calls) == 1
    assert pn.addresses(https_cfg)["home"] is None  # no certificate, no address offered
    pn.upkeep(https_cfg, now=NOW + dt.timedelta(hours=7), run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert len(acme.calls) == 2


def test_certificate_close_to_expiry_is_renewed(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa", "fulano"))
    for name in ("fulano-casa.duckdns.org", "fulano.duckdns.org"):
        write_cert(*pn.cert_paths(https_cfg, name), name, NOW + dt.timedelta(days=20))
    acme = FakeAcme()
    report = pn.upkeep(https_cfg, now=NOW, run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert report["renewed"] and [c for c in acme.calls if "--cron" in c] == [acme.calls[0]]
    assert len(acme.calls) == 1  # one acme.sh run renews both


def test_already_issued_certificate_is_reinstalled(https_cfg):
    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa"))
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if "--install-cert" in cmd:
            name = cmd[cmd.index("-d") + 1]
            write_cert(Path(cmd[cmd.index("--fullchain-file") + 1]), Path(cmd[cmd.index("--key-file") + 1]),
                       name, NOW + dt.timedelta(days=60))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 2, "Domains not changed. Skipping.", "")  # RENEW_SKIP

    assert pn.issue(https_cfg, pn.load(https_cfg), "fulano-casa.duckdns.org", run=run)
    assert "--install-cert" in calls[1] and "--ecc" in calls[1]


def test_no_acme_no_certificate_attempts(https_cfg, tmp_path):
    cfg = Config(data_dir=https_cfg.data_dir, workers=False, https=True, acme_home=tmp_path / "nada")
    pn.save(cfg, pn.DuckDNS(TOKEN, "fulano-casa"))
    acme = FakeAcme()
    report = pn.upkeep(cfg, now=NOW, run=acme, opener=FakeDuckDNS(), detect=addrs())
    assert report["acme"] is False and acme.calls == []


def test_not_configured_does_nothing(https_cfg):
    assert pn.upkeep(https_cfg, now=NOW, run=FakeAcme(), opener=FakeDuckDNS(), detect=addrs()) == {"configured": False}
    assert pn.addresses(https_cfg) == {"home": None, "away": None}


# --- SNI ------------------------------------------------------------------------------------

def handshake(server_ctx: ssl.SSLContext, server_name: str | None, ca: Path | None) -> str:
    """TLS handshake in memory, the way asyncio does it (SSLObject). Returns the
    common name of the certificate the client got."""
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if ca is None:
        client_ctx.check_hostname = False
        client_ctx.verify_mode = ssl.CERT_NONE
    else:
        client_ctx.load_verify_locations(str(ca))
    c_in, c_out, s_in, s_out = ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_ctx.wrap_bio(c_in, c_out, server_hostname=server_name)
    server = server_ctx.wrap_bio(s_in, s_out, server_side=True)
    for _ in range(10):
        for side in (client, server):
            try:
                side.do_handshake()
            except ssl.SSLWantReadError:
                pass
        s_in.write(c_out.read())
        c_in.write(s_out.read())
    der = client.getpeercert(binary_form=True)
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    return x509.load_der_x509_certificate(der).subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


def test_browser_gets_the_certificate_for_the_name_it_asked_for(https_cfg, tmp_path):
    base_crt, base_key = tmp_path / "server.crt", tmp_path / "server.key"
    write_cert(base_crt, base_key, "acervo-proprio", NOW + dt.timedelta(days=800))
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(base_crt), str(base_key))
    pn.attach_sni(server_ctx, https_cfg)

    crt, key = pn.cert_paths(https_cfg, "fulano-casa.duckdns.org")
    write_cert(crt, key, "fulano-casa.duckdns.org", dt.datetime.now(UTC) + dt.timedelta(days=60))

    assert handshake(server_ctx, "fulano-casa.duckdns.org", ca=crt) == "fulano-casa.duckdns.org"
    assert handshake(server_ctx, "FULANO-CASA.duckdns.org", ca=crt) == "fulano-casa.duckdns.org"
    assert handshake(server_ctx, None, ca=None) == "acervo-proprio"  # by IP: the server's own
    assert handshake(server_ctx, "outro.duckdns.org", ca=None) == "acervo-proprio"
    picker = pn.SniCertificates(https_cfg)
    for evil in ("../server", "..", "a/b", "x" * 300):
        assert picker.context_for(evil) is None

    # acme.sh renews: the new file is used without restarting
    write_cert(crt, key, "fulano-casa.duckdns.org", dt.datetime.now(UTC) + dt.timedelta(days=90))
    import os
    os.utime(crt, (crt.stat().st_atime, crt.stat().st_mtime + 5))
    assert handshake(server_ctx, "fulano-casa.duckdns.org", ca=crt) == "fulano-casa.duckdns.org"


def test_health_reports_ready_addresses(https_cfg):
    from fastapi.testclient import TestClient
    from acervo.app import create_app

    pn.save(https_cfg, pn.DuckDNS(TOKEN, "fulano-casa", "fulano"))
    crt, key = pn.cert_paths(https_cfg, "fulano-casa.duckdns.org")
    write_cert(crt, key, "fulano-casa.duckdns.org", dt.datetime.now(UTC) + dt.timedelta(days=60))
    with TestClient(create_app(https_cfg)) as client:
        body = client.get("/api/health").json()
    assert body["service"] == "acervo"
    assert body["addresses"] == {"home": "https://fulano-casa.duckdns.org:8765", "away": None}
    assert TOKEN not in str(body)
