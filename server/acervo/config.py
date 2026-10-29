"""Configuration: defaults, overridden by a TOML file, overridden by env vars.

Lookup order for the config file:
  1. explicit path passed to load_config()
  2. $ACERVO_CONFIG
  3. ./acervo.toml (if it exists)
  4. none -> built-in defaults

$ACERVO_DATA_DIR always wins over data_dir from the file, so dev scripts and
tests can point the server somewhere else without editing anything.
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = Path.home() / "acervo-dados"
REPO_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Subfolders of the data dir. Keep in sync with docs and README.
INBOX_DIR = "entrada"
LIBRARY_DIR = "acervo"
TRASH_DIR = "lixeira"
THUMBS_DIR = "miniaturas"
PREVIEWS_DIR = "previas"  # disposable cache of browser-viewable previews (HEIC -> JPEG)
TMP_DIR = "tmp"  # partial uploads; same filesystem as the rest so moves are atomic
GEO_DIR = "geo"  # offline city database
CERTS_DIR = "certificados"
DB_FILENAME = "catalogo.db"


class ConfigError(ValueError):
    """Raised with a message in Portuguese, meant to be shown to the owner."""


@dataclass(frozen=True)
class Config:
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    server_name: str = "Acervo"
    storage_alert_pct: int = 80
    archive_batch_gb: int = 80
    archive_copies: int = 1
    trash_days: int = 30
    https: bool = False
    tls_names: tuple[str, ...] = ()
    sd_dir: Path | None = None
    # True: everything kept in triage goes to the microSD (the phone keeps only the
    # Entrada). False: the card is only used when internal storage passes the alert.
    sd_for_library: bool = False
    # Maximum size of the Entrada (awaiting triage), in GB. 0 = no limit.
    inbox_max_gb: int = 100
    # Background jobs pause while the battery is at or above this temperature (°C).
    max_temp_c: int = 40
    catalog_backup_dir: Path | None = None
    web_dir: Path = field(default_factory=lambda: REPO_WEB_DIST)
    # Away from home (Tailscale): "seguro" forbids deleting and drive operations.
    remote_mode: str = "seguro"
    remote_networks: tuple[str, ...] = ("100.64.0.0/10", "fd7a:115c:a1e0::/48")
    shortcut_manual_url: str = ""
    shortcut_daily_url: str = ""
    push_contact: str = "mailto:acervo@example.com"
    workers: bool = True  # background jobs (thumbnails, OCR…); tests turn them off
    config_file: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    def subdir(self, name: str) -> Path:
        return self.data_dir / name

    def root_dir(self, root: str) -> Path:
        if root == "main":
            return self.data_dir
        if root == "sd" and self.sd_dir is not None:
            return self.sd_dir
        raise ConfigError(f"Local de armazenamento '{root}' não configurado.")

    def validate(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ConfigError(f"Porta inválida: {self.port}. Use um número entre 1 e 65535.")
        if not (50 <= self.storage_alert_pct <= 95):
            raise ConfigError("storage_alert_pct deve ficar entre 50 e 95.")
        if self.archive_batch_gb <= 0:
            raise ConfigError("archive_batch_gb deve ser maior que zero.")
        if self.archive_copies not in (1, 2, 3):
            raise ConfigError("archive_copies deve ser 1, 2 ou 3.")
        if self.remote_mode not in ("seguro", "completo"):
            raise ConfigError('remote_mode deve ser "seguro" ou "completo".')
        for net in self.remote_networks:
            try:
                ipaddress.ip_network(net)
            except ValueError:
                raise ConfigError(f"remote_networks: rede inválida '{net}'.") from None
        if self.inbox_max_gb < 0:
            raise ConfigError("inbox_max_gb não pode ser negativo (0 = sem limite).")
        if not (30 <= self.max_temp_c <= 55):
            raise ConfigError("max_temp_c deve ficar entre 30 e 55 (graus Celsius).")
        if self.sd_for_library and self.sd_dir is None:
            raise ConfigError("sd_for_library = true precisa de sd_dir (o caminho do cartão microSD).")
        if self.trash_days < 30:
            # Inviolable rule 6: discarded items spend 30 days in the trash.
            raise ConfigError("trash_days não pode ser menor que 30 (regra da lixeira).")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


_INT_KEYS = {"port", "storage_alert_pct", "archive_batch_gb", "archive_copies", "trash_days",
             "inbox_max_gb", "max_temp_c"}
_STR_KEYS = {"host", "server_name", "remote_mode", "shortcut_manual_url", "shortcut_daily_url", "push_contact"}
_BOOL_KEYS = {"https", "workers", "sd_for_library"}
_PATH_KEYS = {"data_dir", "sd_dir", "catalog_backup_dir", "web_dir"}
_LIST_KEYS = {"tls_names", "remote_networks"}
_ALLOWED_KEYS = _INT_KEYS | _STR_KEYS | _BOOL_KEYS | _PATH_KEYS | _LIST_KEYS


def load_config(path: str | os.PathLike[str] | None = None, **overrides: object) -> Config:
    file_path = _find_config_file(path)
    values: dict[str, object] = {}

    if file_path is not None:
        try:
            with open(file_path, "rb") as fh:
                raw = tomllib.load(fh)
        except FileNotFoundError:
            raise ConfigError(f"Arquivo de configuração não encontrado: {file_path}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Erro de sintaxe em {file_path}: {exc}") from None

        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise ConfigError(f"Opções desconhecidas em {file_path}: {', '.join(sorted(unknown))}")
        values.update(raw)
        for key in _PATH_KEYS & set(values):
            values[key] = _resolve(Path(str(values[key])), file_path.parent)

    env_data_dir = os.environ.get("ACERVO_DATA_DIR")
    if env_data_dir:
        values["data_dir"] = _resolve(Path(env_data_dir), Path.cwd())
    values.update(overrides)

    for key in _INT_KEYS & set(values):
        if not isinstance(values[key], int) or isinstance(values[key], bool):
            raise ConfigError(f"'{key}' precisa ser um número inteiro.")
    for key in _STR_KEYS & set(values):
        if not isinstance(values[key], str):
            raise ConfigError(f"'{key}' precisa ser texto entre aspas.")
    for key in _BOOL_KEYS & set(values):
        if not isinstance(values[key], bool):
            raise ConfigError(f"'{key}' precisa ser true ou false.")
    for key in _LIST_KEYS & set(values):
        names = values[key]
        if not isinstance(names, (list, tuple)) or not all(isinstance(n, str) for n in names):
            raise ConfigError(f"'{key}' precisa ser uma lista de textos.")
        values[key] = tuple(names)

    cfg = Config(config_file=file_path, **values)  # type: ignore[arg-type]
    cfg.validate()
    return cfg


def _find_config_file(path: str | os.PathLike[str] | None) -> Path | None:
    if path is not None:
        return Path(path).expanduser().resolve()
    env = os.environ.get("ACERVO_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    local = Path.cwd() / "acervo.toml"
    return local.resolve() if local.is_file() else None


def _resolve(p: Path, base: Path) -> Path:
    p = p.expanduser()
    return (p if p.is_absolute() else base / p).resolve()
