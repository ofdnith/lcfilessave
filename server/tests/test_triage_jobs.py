"""Triage (keep / discard / restore / purge), suggestions, background jobs,
search, auth and crash recovery."""

import os
import zipfile

from fastapi.testclient import TestClient

from acervo import db
from acervo.app import create_app
from conftest import make_jpeg


def test_keep_moves_to_library_tree(api, tmp_path):
    iid = api.upload(make_jpeg(tmp_path / "IMG_1.JPG"))["item_id"]
    assert api.act([iid], "keep") == {"ok": [iid], "failed": []}
    assert (api.cfg.data_dir / "acervo/2024/05/fotos/2024-05-01_1012_IMG_1.JPG").exists()
    assert api.item(iid)["state"] == "library"
    assert api.get("/api/stats").json()["tabs"]["photo"]["count"] == 1


def test_discard_restore_and_purge_after_30_days(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_2.JPG")
    iid = api.upload(photo)["item_id"]
    api.act([iid], "discard")
    item = api.item(iid)
    assert item["state"] == "trash" and item["trash_expires_at"]
    assert (api.cfg.data_dir / "lixeira/2024-05-01_1012_IMG_2.JPG").exists()
    assert api.upload(photo)["status"] == "in_trash"  # re-sent while in the trash: offer restore
    api.act([iid], "restore")
    assert api.item(iid)["state"] == "inbox"

    api.act([iid], "discard")
    assert api.post("/api/trash/purge-expired").json()["purged"] == 0  # too early
    c = db.connect(api.cfg.db_path)
    c.execute("UPDATE items SET trashed_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (iid,))
    c.close()
    assert api.post("/api/trash/purge-expired").json()["purged"] == 1
    assert not list((api.cfg.data_dir / "lixeira").iterdir())
    assert api.get(f"/api/items/{iid}").status_code == 404
    # the daily backup sends it again (it is still on the iPhone): not stored again
    assert api.upload(photo)["status"] == "discarded"
    assert not list((api.cfg.data_dir / "entrada").iterdir())


def test_archived_items_cannot_be_trashed(api, tmp_path):
    from test_archive import archive_everything
    iid = api.upload(make_jpeg(tmp_path / "IMG_3.JPG"))["item_id"]
    api.act([iid], "keep")
    archive_everything(api, tmp_path / "hd")
    res = api.act([iid], "discard")
    assert res["failed"] and "HD" in res["failed"][0]["error"]


def test_thumbnails_and_near_duplicate_suggestion(api, tmp_path):
    a = make_jpeg(tmp_path / "IMG_A.JPG", size=(800, 600), pattern=4)
    b = tmp_path / "IMG-20240501-WA0001.jpg"  # same picture re-sent through WhatsApp (recompressed)
    from PIL import Image
    Image.open(a).resize((400, 300)).save(b, "JPEG", quality=40)
    other = make_jpeg(tmp_path / "IMG_C.JPG", color=(10, 200, 10), size=(800, 600), pattern=11)
    ids = [api.upload(p)["item_id"] for p in (a, b, other)]
    assert api.run_jobs() >= 3
    item = api.item(ids[0])
    assert item["thumb_url"] and api.get(item["thumb_url"]).headers["content-type"] == "image/webp"
    sugg = api.get("/api/suggestions").json()["suggestions"]
    kinds = {s["kind"]: {i["id"] for i in s["items"]} for s in sugg}
    assert kinds["near-duplicate"] == {ids[0], ids[1]}
    assert kinds["whatsapp"] == {ids[1]}
    # suggestions never discard anything
    assert {api.item(i)["state"] for i in ids} == {"inbox"}
    api.act(ids, "keep")
    assert api.get("/api/suggestions").json()["suggestions"] == []


def test_heic_preview_and_thumbnail(api, tmp_path):
    from PIL import Image
    import pillow_heif  # noqa: F401
    p = tmp_path / "IMG_H.HEIC"
    Image.new("RGB", (300, 200), (30, 90, 160)).save(p)
    iid = api.upload(p)["item_id"]
    api.run_jobs()
    item = api.item(iid)
    assert item["thumb_url"]
    prev = api.get(item["preview_url"])
    assert prev.status_code == 200 and prev.headers["content-type"] == "image/jpeg"
    orig = api.get(item["original_url"], headers={"Range": "bytes=0-9"})
    assert orig.status_code == 206 and len(orig.content) == 10


def test_document_text_is_searchable(api, tmp_path):
    docx = tmp_path / "Contrato aluguel.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:t>Cláusula de reajuste pelo IPCA</w:t></w:document>")
    iid = api.upload(docx)["item_id"]
    api.run_jobs()
    found = api.get("/api/items", params={"view": "inbox", "q": "clausula ipca"}).json()
    assert [i["id"] for i in found["items"]] == [iid]
    assert api.get("/api/items", params={"view": "inbox", "kind": "photo", "q": "ipca"}).json()["items"] == []


def test_ocr_runs_while_charging(api, tmp_path, monkeypatch):
    from acervo import power
    monkeypatch.setattr(power, "is_charging", lambda: True)
    p = make_jpeg(tmp_path / "Screenshot 2024.png".replace(".png", ".JPG"), color=(255, 255, 255),
                  size=(900, 300), text="BOLETO VENCIMENTO JANEIRO")
    iid = api.upload(p)["item_id"]
    api.run_jobs()
    found = api.get("/api/items", params={"view": "inbox", "q": "boleto"}).json()["items"]
    assert [i["id"] for i in found] == [iid]


def test_ocr_waits_when_not_charging(api, tmp_path, monkeypatch):
    from acervo import power
    monkeypatch.setattr(power, "is_charging", lambda: False)
    api.upload(make_jpeg(tmp_path / "IMG_O.JPG"))
    api.run_jobs()
    c = db.connect(api.cfg.db_path)
    assert c.execute("SELECT status FROM jobs WHERE kind = 'ocr'").fetchone()[0] == "pending"


def test_place_from_gps_offline(api, tmp_path):
    geo = api.cfg.subdir("geo")
    (geo / "cities.txt").write_text(
        "3448439\tSão Paulo\tSao Paulo\t\t-23.5475\t-46.63611\tP\tPPLA\tBR\t\t27\t\t\t\t10021295\t\t\tAmerica/Sao_Paulo\t2023\n"
        "3451190\tRio de Janeiro\tRio de Janeiro\t\t-22.90642\t-43.18223\tP\tPPLA\tBR\t\t21\t\t\t\t6023699\t\t\tAmerica/Sao_Paulo\t2023\n")
    (geo / "admin1.txt").write_text("BR.27\tSão Paulo\tSao Paulo\t3448433\nBR.21\tRio de Janeiro\tRio de Janeiro\t3451189\n")
    (geo / "countries.txt").write_text("#ISO\nBR\tBRA\t076\tBR\tBrasil\n")
    iid = api.upload(make_jpeg(tmp_path / "IMG_G.JPG", gps=(-23.56, -46.65)))["item_id"]
    api.run_jobs()
    assert api.item(iid)["place"] == "São Paulo, São Paulo, Brasil"
    assert [i["id"] for i in api.get("/api/items", params={"view": "inbox", "q": "sao paulo"}).json()["items"]] == [iid]


def test_timeline_and_pagination(api, tmp_path):
    for i in range(5):
        api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 40, 9, 9), date=f"2022:0{i + 1}:01 12:00:00"))
    months = api.get("/api/timeline", params={"view": "inbox"}).json()["months"]
    assert [m["month"] for m in months] == [5, 4, 3, 2, 1]
    page1 = api.get("/api/items", params={"view": "inbox", "limit": 2}).json()
    page2 = api.get("/api/items", params={"view": "inbox", "limit": 2, "cursor": page1["next_cursor"]}).json()
    assert page1["total"] == 5
    assert [i["captured_at"][:7] for i in page1["items"] + page2["items"]] == ["2022-05", "2022-04", "2022-03", "2022-02"]
    jump = api.get("/api/items", params={"view": "inbox", "start": "2022-02"}).json()
    assert [i["captured_at"][:7] for i in jump["items"]] == ["2022-02", "2022-01"]


def test_auth_required_and_login(cfg):
    with TestClient(create_app(cfg)) as client:
        assert client.get("/api/stats").status_code == 401  # not loopback, no login
        from conftest import login
        login(client, cfg, "senha-forte-123")
        assert client.get("/api/auth/status").json()["password_set"] is True
        assert client.post("/api/auth/login", json={"password": "errada"}).status_code == 401
        res = client.post("/api/auth/login", json={"password": "senha-forte-123"})
        assert res.status_code == 200 and "acervo_session" in res.cookies
        assert client.get("/api/stats").status_code == 200  # cookie
        assert client.post("/api/auth/app-token").json()["token"]
        client.post("/api/auth/logout")
        client.cookies.clear()
        assert client.get("/api/stats").status_code == 401


def test_login_is_rate_limited(cfg):
    from acervo import auth
    auth._failures.clear()
    with TestClient(create_app(cfg)) as client:
        from conftest import login
        login(client, cfg)
        codes = [client.post("/api/auth/login", json={"password": "x"}).status_code for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
    auth._failures.clear()


def test_reconcile_after_crash(cfg, tmp_path):
    from conftest import Api, login
    with TestClient(create_app(cfg)) as client:
        api = Api(client, cfg, login(client, cfg))
        iid = api.upload(make_jpeg(tmp_path / "IMG_R.JPG"))["item_id"]
    entrada = cfg.data_dir / "entrada"
    # 1. crash after the move but before the catalog update
    (cfg.data_dir / "acervo/2024/05/fotos").mkdir(parents=True)
    os.replace(entrada / "2024-05-01_1012_IMG_R.JPG", cfg.data_dir / "acervo/2024/05/fotos/2024-05-01_1012_IMG_R.JPG")
    # 2. a file that the catalog never heard of
    make_jpeg(entrada / "2024-06-01_1200_PERDIDO.JPG", color=(1, 99, 1))
    with TestClient(create_app(cfg)) as client:
        report = client.app.state.reconcile_report
        api = Api(client, cfg, login(client, cfg))
        assert report["fixed_paths"] == 1 and report["reingested"] == 1 and report["missing"] == 0
        assert api.get(f"/api/items/{iid}/original").status_code == 200
        names = [i["original_name"] for i in api.get("/api/items", params={"view": "inbox"}).json()["items"]]
        assert "PERDIDO.JPG" in names


def test_https_certificate_for_iphone(tmp_path):
    from cryptography import x509
    from acervo.certs import generate
    ca = generate(tmp_path / "certs", ["192.168.0.50", "acervo.tail1234.ts.net"])
    cert = x509.load_pem_x509_certificate((tmp_path / "certs" / "server.crt").read_bytes())
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "acervo.tail1234.ts.net" in sans.get_values_for_type(x509.DNSName)
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= 825  # Apple's limit
    ca_cert = x509.load_pem_x509_certificate(ca.read_bytes())
    assert cert.issuer == ca_cert.subject
    # regenerating keeps the same CA (already installed on the iPhone)
    generate(tmp_path / "certs", ["192.168.0.51"])
    assert x509.load_pem_x509_certificate(ca.read_bytes()).serial_number == ca_cert.serial_number
