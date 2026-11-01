"""Trusted HTTPS without installing anything on the devices: DuckDNS + Let's Encrypt.

The server keeps two DuckDNS names pointing at its own private addresses:

  home  ->  the phone's Wi-Fi address (192.168.x.x): full mode
  away  ->  the phone's Tailscale address (100.x.y.z): safe mode (see auth.is_remote)

Nothing is exposed to the internet (inviolable rule 7): the names only resolve to
private addresses, and the certificate comes through the DNS-01 challenge, so no
one ever connects in. Both addresses are discovered at run time, so the owner
never edits them by hand, and DuckDNS follows when they change.

Certificates come from acme.sh (a shell script; Termux: pkg install openssl curl),
one per name, because DuckDNS keeps a single TXT record per name. The server picks
the right one by the name the browser asked for (SNI) and picks up renewed files
without a restart.

Files, all under <data>/certificados/:
  duckdns.json            token and names (mode 600), written by `acervo duckdns`
  publico/<name>.crt|key  the Let's Encrypt certificates, written by acme.sh
  publico/estado.json     last addresses sent to DuckDNS and last attempts
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import CERTS_DIR, Config

log = logging.getLogger(__name__)

SETTINGS_FILE = "duckdns.json"
PUBLIC_DIR = "publico"
STATE_FILE = "estado.json"
DUCKDNS_SUFFIX = ".duckdns.org"
DUCKDNS_API = "https://www.duckdns.org/update"

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_DNS = "100.100.100.100"  # MagicDNS resolver, only routed when Tailscale is on

RENEW_BEFORE = dt.timedelta(days=30)  # Let's Encrypt certificates last 90 days (or less)
RETRY_ISSUE_AFTER = dt.timedelta(hours=6)  # stay far from Let's Encrypt's failure limits
RECHECK_DNS_AFTER = dt.timedelta(days=1)  # push the addresses again even if unchanged

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FQDN_RE = re.compile(r"^[a-z0-9.-]{1,253}$")

Runner = Callable[..., subprocess.CompletedProcess]


class PublicNameError(ValueError):
    """Message in Portuguese, shown to the owner."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DuckDNS:
    token: str
    home: str        # subdomain only, e.g. "fulano-casa"
    away: str = ""   # "" = no address for Tailscale

    def names(self) -> list[tuple[str, str]]:
        """[(role, fqdn)] for the names in use, home first."""
        out = [("home", self.home + DUCKDNS_SUFFIX)]
        if self.away:
            out.append(("away", self.away + DUCKDNS_SUFFIX))
        return out


def normalize_name(raw: str) -> str:
    """'https://Fulano-Casa.duckdns.org:8765/' -> 'fulano-casa'."""
    name = raw.strip().lower()
    name = re.sub(r"^[a-z]+://", "", name)
    name = name.split("/", 1)[0].split(":", 1)[0]
    if name.endswith(DUCKDNS_SUFFIX):
        name = name[: -len(DUCKDNS_SUFFIX)]
    if not _NAME_RE.match(name):
        raise PublicNameError(
            f"Nome inválido: '{raw.strip()}'. Use só o nome que você criou no DuckDNS, "
            "por exemplo  fulano-casa  (letras, números e hífen)."
        )
    return name


def normalize_token(raw: str) -> str:
    token = raw.strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{20,64}", token):
        raise PublicNameError("Token inválido. Copie o token que aparece no topo da página do duckdns.org.")
    return token


def certs_dir(cfg: Config) -> Path:
    return cfg.subdir(CERTS_DIR)


def public_dir(cfg: Config) -> Path:
    return certs_dir(cfg) / PUBLIC_DIR


def load(cfg: Config) -> DuckDNS | None:
    path = certs_dir(cfg) / SETTINGS_FILE
    try:
        data = json.loads(path.read_text("utf-8"))
        return DuckDNS(token=data["token"], home=data["home"], away=data.get("away", ""))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("%s ilegível; endereço seguro desligado até rodar `acervo duckdns` de novo", path)
        return None


def save(cfg: Config, dd: DuckDNS) -> Path:
    folder = certs_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SETTINGS_FILE
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"token": dd.token, "home": dd.home, "away": dd.away}, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return path


def remove(cfg: Config) -> bool:
    """Turns the trusted address off. Certificates stay (harmless) until replaced."""
    path = certs_dir(cfg) / SETTINGS_FILE
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _load_state(cfg: Config) -> dict:
    try:
        return json.loads((public_dir(cfg) / STATE_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(cfg: Config, state: dict) -> None:
    folder = public_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), "utf-8")
    os.replace(tmp, folder / STATE_FILE)


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def _source_address(target: str) -> str | None:
    """The local address the system would use to reach `target`. A UDP connect
    sends nothing; it only asks the routing table, which works without any
    permission on Android (where `ip addr` is blocked for apps)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return s.getsockname()[0]
    except OSError:
        return None


def detect_addresses(source: Callable[[str], str | None] = _source_address) -> dict[str, str | None]:
    """{"lan": Wi-Fi/Ethernet address or None, "tailscale": 100.x address or None}."""
    lan = None
    for target in ("8.8.8.8", "1.1.1.1", "192.168.0.1"):
        ip = source(target)
        if not ip:
            continue
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback and addr not in TAILSCALE_NET:
            lan = ip
            break
    ts = source(TAILSCALE_DNS)
    tailscale = ts if ts and ipaddress.ip_address(ts) in TAILSCALE_NET else None
    return {"lan": lan, "tailscale": tailscale}


def duckdns_update(token: str, name: str, ip: str, opener: Callable = urllib.request.urlopen) -> bool:
    """Points <name>.duckdns.org at `ip`. True when DuckDNS answers OK."""
    query = urllib.parse.urlencode({"domains": name, "token": token, "ip": ip})
    try:
        with opener(f"{DUCKDNS_API}?{query}", timeout=20) as resp:
            body = resp.read(64).decode("ascii", "replace").strip()
    except OSError as exc:
        log.warning("DuckDNS não respondeu (%s): %s", name, getattr(exc, "reason", exc))
        return False
    if body != "OK":
        log.warning("DuckDNS recusou a atualização de %s (resposta %r): token ou nome errado?", name, body)
        return False
    return True


# ---------------------------------------------------------------------------
# Certificates (acme.sh)
# ---------------------------------------------------------------------------

def acme_script(cfg: Config) -> Path:
    return cfg.acme_home / "acme.sh"


def acme_available(cfg: Config) -> bool:
    return acme_script(cfg).is_file()


def cert_paths(cfg: Config, fqdn: str) -> tuple[Path, Path]:
    folder = public_dir(cfg)
    return folder / f"{fqdn}.crt", folder / f"{fqdn}.key"


def cert_expiry(path: Path) -> dt.datetime | None:
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError, ImportError):
        return None
    return cert.not_valid_after_utc


def cert_valid(cfg: Config, fqdn: str, now: dt.datetime | None = None) -> bool:
    crt, key = cert_paths(cfg, fqdn)
    if not key.exists():
        return False
    expiry = cert_expiry(crt)
    now = now or dt.datetime.now(dt.timezone.utc)
    return expiry is not None and expiry > now


def _acme_base(cfg: Config) -> list[str]:
    home = str(cfg.acme_home)
    return ["sh", str(acme_script(cfg)), "--home", home, "--config-home", str(cfg.acme_home / "data"),
            "--no-color", "--log", str(cfg.acme_home / "acervo.log")]


def _acme_env(dd: DuckDNS) -> dict[str, str]:
    env = dict(os.environ)
    env["DuckDNS_Token"] = dd.token
    return env


def issue(cfg: Config, dd: DuckDNS, fqdn: str, run: Runner = subprocess.run) -> bool:
    """Gets (or re-installs) the certificate for one name. Takes 1 to 3 minutes:
    acme.sh waits for the TXT record to spread before Let's Encrypt checks it."""
    if not _FQDN_RE.match(fqdn):
        raise PublicNameError(f"Nome inválido: {fqdn}")
    crt, key = cert_paths(cfg, fqdn)
    crt.parent.mkdir(parents=True, exist_ok=True)
    files = ["--fullchain-file", str(crt), "--key-file", str(key)]
    cmd = _acme_base(cfg) + ["--issue", "--dns", "dns_duckdns", "-d", fqdn, "--server", "letsencrypt",
                             "--keylength", "ec-256"] + files
    try:
        result = run(cmd, env=_acme_env(dd), capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("acme.sh falhou para %s: %s", fqdn, exc)
        return False
    if result.returncode == 2:
        # Already issued and not due: just make sure the files are where we read them.
        cmd = _acme_base(cfg) + ["--install-cert", "-d", fqdn, "--ecc"] + files
        try:
            result = run(cmd, env=_acme_env(dd), capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("acme.sh não instalou o certificado de %s: %s", fqdn, exc)
            return False
    if result.returncode != 0:
        tail = "\n".join((result.stdout or "").strip().splitlines()[-6:] + (result.stderr or "").strip().splitlines()[-4:])
        log.warning("acme.sh não conseguiu o certificado de %s (código %s):\n%s", fqdn, result.returncode, tail)
        return False
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    return cert_valid(cfg, fqdn)


def renew_due(cfg: Config, dd: DuckDNS, run: Runner = subprocess.run) -> bool:
    """acme.sh renews whatever is due and copies the new files in place."""
    try:
        result = run(_acme_base(cfg) + ["--cron"], env=_acme_env(dd), capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Renovação dos certificados falhou: %s", exc)
        return False
    if result.returncode not in (0, 2):
        log.warning("Renovação dos certificados falhou (código %s)", result.returncode)
        return False
    return True


# ---------------------------------------------------------------------------
# Upkeep (background thread) and status
# ---------------------------------------------------------------------------

_upkeep_lock = threading.Lock()


def upkeep(cfg: Config, *, now: dt.datetime | None = None, run: Runner = subprocess.run,
           opener: Callable = urllib.request.urlopen,
           detect: Callable[[], dict[str, str | None]] = detect_addresses) -> dict:
    """Keeps DuckDNS pointing at the current addresses and the certificates valid.
    Cheap when there is nothing to do; meant to run every few minutes."""
    dd = load(cfg)
    if dd is None:
        return {"configured": False}
    if not _upkeep_lock.acquire(blocking=False):
        return {"configured": True, "busy": True}
    try:
        now = now or dt.datetime.now(dt.timezone.utc)
        state = _load_state(cfg)
        addrs = detect()
        report: dict = {"configured": True, "addresses": addrs, "dns": {}, "issued": [], "renewed": False}

        for role, fqdn in dd.names():
            ip = addrs["lan"] if role == "home" else addrs["tailscale"]
            if not ip:
                continue
            key = f"dns:{fqdn}"
            last = state.get(key, {})
            fresh = last.get("ip") == ip and _age(last.get("at"), now) < RECHECK_DNS_AFTER
            if fresh:
                continue
            ok = duckdns_update(dd.token, fqdn[: -len(DUCKDNS_SUFFIX)], ip, opener=opener)
            report["dns"][fqdn] = ok
            if ok:
                state[key] = {"ip": ip, "at": now.isoformat()}
                log.info("DuckDNS: %s -> %s", fqdn, ip)
        _save_state(cfg, state)

        if not acme_available(cfg):
            report["acme"] = False
            return report

        renew = False
        for _, fqdn in dd.names():
            crt, key_file = cert_paths(cfg, fqdn)
            expiry = cert_expiry(crt) if key_file.exists() else None
            if expiry is not None and expiry - now > RENEW_BEFORE:
                continue
            key = f"acme:{fqdn}"
            if _age(state.get(key), now) < RETRY_ISSUE_AFTER:
                continue  # tried recently; don't hammer Let's Encrypt
            state[key] = now.isoformat()
            _save_state(cfg, state)
            if expiry is None:
                log.info("Pedindo o certificado de %s ao Let's Encrypt…", fqdn)
                if issue(cfg, dd, fqdn, run=run):
                    report["issued"].append(fqdn)
                    log.info("Certificado de %s pronto", fqdn)
            else:
                renew = True
        if renew:  # acme.sh renews everything that is due in one go
            report["renewed"] = renew_due(cfg, dd, run=run)
        return report
    finally:
        _upkeep_lock.release()


def mark_attempt(cfg: Config, fqdn: str, now: dt.datetime | None = None) -> None:
    """Tells the background upkeep that someone is getting this certificate now
    (`acervo duckdns`), so the two never run acme.sh for the same name at once."""
    state = _load_state(cfg)
    state[f"acme:{fqdn}"] = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    _save_state(cfg, state)


def _age(iso: str | None, now: dt.datetime) -> dt.timedelta:
    if not iso:
        return dt.timedelta.max
    try:
        then = dt.datetime.fromisoformat(iso)
    except ValueError:
        return dt.timedelta.max
    if then.tzinfo is None:
        then = then.replace(tzinfo=dt.timezone.utc)
    return now - then


def addresses(cfg: Config) -> dict[str, str | None]:
    """The trusted addresses that work right now (certificate in place), for
    /api/health: the Mac app and the web interface switch to them."""
    out: dict[str, str | None] = {"home": None, "away": None}
    dd = load(cfg)
    if dd is None or not cfg.https:
        return out
    for role, fqdn in dd.names():
        if cert_valid(cfg, fqdn):
            out[role] = f"https://{fqdn}" + ("" if cfg.port == 443 else f":{cfg.port}")
    return out


# ---------------------------------------------------------------------------
# SNI: pick the certificate by the name the browser asked for
# ---------------------------------------------------------------------------

class SniCertificates:
    """`ssl.SSLContext.sni_callback`. A request for a name with a Let's Encrypt
    certificate in certificados/publico/ gets it; anything else (an IP address,
    localhost, the old Tailscale name) keeps the server's own certificate.
    Contexts are cached and rebuilt when acme.sh replaces the files."""

    def __init__(self, cfg: Config):
        self._dir = public_dir(cfg)
        self._cache: dict[str, tuple[float, ssl.SSLContext]] = {}
        self._lock = threading.Lock()

    def context_for(self, server_name: str | None) -> ssl.SSLContext | None:
        if not server_name:
            return None
        name = server_name.lower().rstrip(".")
        if not _FQDN_RE.match(name) or ".." in name or "/" in name:
            return None
        crt, key = self._dir / f"{name}.crt", self._dir / f"{name}.key"
        try:
            mtime = max(crt.stat().st_mtime, key.stat().st_mtime)
        except OSError:
            return None
        with self._lock:
            cached = self._cache.get(name)
            if cached and cached[0] == mtime:
                return cached[1]
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.load_cert_chain(str(crt), str(key))
            except (OSError, ssl.SSLError) as exc:
                log.warning("Certificado de %s ilegível: %s", name, exc)
                return cached[1] if cached else None
            self._cache[name] = (mtime, ctx)
            return ctx

    def __call__(self, sslobj, server_name, _ctx):  # noqa: ANN001 - ssl callback signature
        try:
            ctx = self.context_for(server_name)
            if ctx is not None:
                sslobj.context = ctx
        except Exception:  # never break the handshake over this
            log.exception("Erro ao escolher o certificado de %s", server_name)
        return None


def attach_sni(ctx: ssl.SSLContext, cfg: Config) -> None:
    ctx.sni_callback = SniCertificates(cfg)
