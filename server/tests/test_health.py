from fastapi.testclient import TestClient

from acervo import db
from acervo.app import create_app
from acervo.storage import LAYOUT


def test_health_ok_and_layout_created(cfg):
    with TestClient(create_app(cfg)) as client:
        res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["catalog"]["schema_version"] == db.latest_version()
    assert body["storage"]["total_bytes"] > 0
    assert body["problems"] == []
    assert "exiftool" in body["tools"]
    for name in LAYOUT:
        assert (cfg.data_dir / name).is_dir()


def test_health_reports_missing_folder(cfg):
    with TestClient(create_app(cfg)) as client:
        (cfg.data_dir / "lixeira").rmdir()
        res = client.get("/api/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
    assert any("lixeira" in p for p in res.json()["problems"])


def test_placeholder_page_without_web_build(cfg):
    with TestClient(create_app(cfg)) as client:
        res = client.get("/")
    assert res.status_code == 200
    assert "Acervo" in res.text


def test_web_build_is_served_with_spa_fallback(cfg, tmp_path):
    web = cfg.web_dir
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>APP</html>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(cfg)) as client:
        assert client.get("/").text == "<html>APP</html>"
        assert client.get("/entrada/rapido").text == "<html>APP</html>"
        js = client.get("/assets/app.js")
        assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
        assert client.get("/../../etc/passwd").text == "<html>APP</html>"
        assert client.get("/api/nao-existe").status_code in (401, 404)


def test_restart_keeps_catalog(cfg):
    with TestClient(create_app(cfg)):
        pass
    conn = db.connect(cfg.db_path)
    conn.execute("INSERT INTO settings (key, value) VALUES ('teste', '1')")
    conn.close()
    with TestClient(create_app(cfg)) as client:
        assert client.get("/api/health").status_code == 200
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT value FROM settings WHERE key = 'teste'").fetchone()[0] == "1"
