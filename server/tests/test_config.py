from pathlib import Path

import pytest

from acervo.__main__ import main
from acervo.config import ConfigError, is_loopback, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ACERVO_CONFIG", raising=False)
    monkeypatch.delenv("ACERVO_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


def test_defaults_without_file():
    cfg = load_config()
    assert cfg.config_file is None
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.db_path.name == "catalogo.db"


def test_file_values_and_relative_data_dir(tmp_path: Path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "acervo.toml").write_text('data_dir = "meus-dados"\nport = 9000\n')
    cfg = load_config(conf_dir / "acervo.toml")
    assert cfg.port == 9000
    assert cfg.data_dir == (conf_dir / "meus-dados").resolve()


def test_env_data_dir_wins(tmp_path: Path, monkeypatch):
    (tmp_path / "acervo.toml").write_text('data_dir = "/nao/usar"\n')
    monkeypatch.setenv("ACERVO_DATA_DIR", str(tmp_path / "outra"))
    cfg = load_config()
    assert cfg.data_dir == (tmp_path / "outra").resolve()


@pytest.mark.parametrize(
    "content",
    [
        "port = 70000\n",
        'port = "8765"\n',
        "trash_days = 7\n",
        "storage_alert_pct = 99\n",
        "senha = 1\n",
        "port = \n",
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, content: str):
    path = tmp_path / "acervo.toml"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize(
    "host,expected",
    [("127.0.0.1", True), ("localhost", True), ("::1", True), ("0.0.0.0", False), ("192.168.0.10", False)],
)
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


def test_serve_refuses_network_host_without_password(tmp_path: Path, capsys):
    (tmp_path / "acervo.toml").write_text('host = "0.0.0.0"\n')
    assert main(["serve"]) == 2
    assert "Fase 3" in capsys.readouterr().err
