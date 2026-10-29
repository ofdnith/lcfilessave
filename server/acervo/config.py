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

# Subfolders of the data dir. Keep in sync with docs and README.
INBOX_DIR = "entrada"
LIBRARY_DIR = "acervo"
TRASH_DIR = "lixeira"
THUMBS_DIR = "miniaturas"
TMP_DIR = "tmp"  # partial uploads; same filesystem as the rest so moves are atomic
DB_FILENAME = "catalogo.db"


class ConfigError(ValueError):
    """Raised with a message in Portuguese, meant to be shown to the owner."""


@dataclass(frozen=True)
class Config:
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    storage_alert_pct: int = 80
    archive_batch_gb: int = 80
    trash_days: int = 30
    config_file: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    def subdir(self, name: str) -> Path:
        return self.data_dir / name

    def validate(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ConfigError(f"Porta inválida: {self.port}. Use um número entre 1 e 65535.")
        if not (50 <= self.storage_alert_pct <= 95):
            raise ConfigError("storage_alert_pct deve ficar entre 50 e 95.")
        if self.archive_batch_gb <= 0:
            raise ConfigError("archive_batch_gb deve ser maior que zero.")
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


_ALLOWED_KEYS = {"data_dir", "host", "port", "storage_alert_pct", "archive_batch_gb", "trash_days"}


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
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
            raise ConfigError(
                f"Opções desconhecidas em {file_path}: {', '.join(sorted(unknown))}"
            )
        values.update(raw)
        if "data_dir" in values:
            values["data_dir"] = _resolve(Path(str(values["data_dir"])), file_path.parent)

    env_data_dir = os.environ.get("ACERVO_DATA_DIR")
    if env_data_dir:
        values["data_dir"] = _resolve(Path(env_data_dir), Path.cwd())

    for key in ("port", "storage_alert_pct", "archive_batch_gb", "trash_days"):
        if key in values and not isinstance(values[key], int):
            raise ConfigError(f"'{key}' precisa ser um número inteiro.")
    if "host" in values and not isinstance(values["host"], str):
        raise ConfigError("'host' precisa ser texto, por exemplo \"127.0.0.1\".")

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
