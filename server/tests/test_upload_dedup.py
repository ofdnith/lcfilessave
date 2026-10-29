"""Upload, deduplication and organisation — including the five tests the spec
makes mandatory (marked MANDATORY)."""

import base64
import shutil
import threading

from fastapi.testclient import TestClient

from acervo import db
from acervo.app import create_app
from conftest import Api, login, make_jpeg, sha


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_new_photo_lands_in_inbox_with_standard_name(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_1234.JPG")
    res = api.upload(photo)
    assert res["status"] == "new"
    item = api.item(res["item_id"])
    assert item["state"] == "inbox"
    assert item["captured_at"] == "2024-05-01T10:12:33" and item["captured_tz"] == "-03:00"
    assert item["standard_name"] == "2024-05-01_1012_IMG_1234.JPG"
    assert item["camera"] == "Apple iPhone 13"
    assert (api.cfg.data_dir / "entrada" / "2024-05-01_1012_IMG_1234.JPG").read_bytes() == photo.read_bytes()


def test_MANDATORY_same_file_different_name_is_not_stored_twice(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_1.JPG")
    first = api.upload(photo)
    second = api.upload(photo, name="foto renomeada.jpg")
    assert first["status"] == "new" and second["status"] == "duplicate"
    assert second["item_id"] == first["item_id"]
    assert len(list((api.cfg.data_dir / "entrada").iterdir())) == 1


def test_MANDATORY_same_name_different_content_keeps_both(api, tmp_path):
    a = make_jpeg(tmp_path / "a" / "IMG_1.JPG", color=(10, 200, 10))
    b = make_jpeg(tmp_path / "b" / "IMG_1.JPG", color=(10, 10, 200))
    ra, rb = api.upload(a), api.upload(b)
    assert ra["status"] == rb["status"] == "new"
    names = sorted(p.name for p in (api.cfg.data_dir / "entrada").iterdir())
    assert names == ["2024-05-01_1012_IMG_1.JPG", "2024-05-01_1012_IMG_1_2.JPG"]


def test_MANDATORY_interrupted_upload_resumes_after_restart(cfg, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_9.JPG", size=(1200, 900), pattern=3)
    data = photo.read_bytes()
    half = len(data) // 2
    with TestClient(create_app(cfg)) as client:
        api = Api(client, cfg, login(client, cfg))
        res = api.post("/api/uploads", headers={
            "Tus-Resumable": "1.0.0", "Upload-Length": str(len(data)),
            "Upload-Metadata": f"filename {b64('IMG_9.JPG')},source {b64('web')}"})
        assert res.status_code == 201
        url = res.headers["location"]
        res = client.patch(url, content=data[:half], headers={**api.headers, "Tus-Resumable": "1.0.0",
                           "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"})
        assert res.status_code == 204 and res.headers["upload-offset"] == str(half)
    # The server process "dies" and starts again.
    with TestClient(create_app(cfg)) as client:
        api = Api(client, cfg, login(client, cfg))
        head = client.head(url, headers={**api.headers, "Tus-Resumable": "1.0.0"})
        assert head.headers["upload-offset"] == str(half)
        wrong = client.patch(url, content=data[half:], headers={**api.headers, "Tus-Resumable": "1.0.0",
                             "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"})
        assert wrong.status_code == 409
        res = client.patch(url, content=data[half:], headers={**api.headers, "Tus-Resumable": "1.0.0",
                           "Upload-Offset": str(half), "Content-Type": "application/offset+octet-stream"})
        assert res.status_code == 204
        result = api.get(url + "/result").json()
        assert result["status"] == "new"
        assert api.item(result["item_id"])["sha256"] == sha(photo)


def test_MANDATORY_two_simultaneous_uploads_of_the_same_file(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_7.JPG", size=(2000, 1500), pattern=5)
    results = []

    def send():
        results.append(api.upload(photo))

    threads = [threading.Thread(target=send) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r["status"] for r in results) == ["duplicate", "duplicate", "duplicate", "new"]
    assert len({r["item_id"] for r in results}) == 1
    assert len(list((api.cfg.data_dir / "entrada").iterdir())) == 1


def test_MANDATORY_file_already_archived_on_a_drive(api, tmp_path):
    from test_archive import archive_everything
    photo = make_jpeg(tmp_path / "IMG_5.JPG")
    item_id = api.upload(photo)["item_id"]
    api.act([item_id], "keep")
    archive_everything(api, tmp_path / "hd")
    assert api.item(item_id)["state"] == "archived"
    res = api.upload(photo, name="de novo.jpg")
    assert res["status"] == "duplicate" and res["message"] == "Já está no VOLUME-001"
    assert not any((api.cfg.data_dir / "entrada").iterdir())


def test_hash_mismatch_is_rejected(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_2.JPG")
    res = api.upload(photo, sha256="0" * 64)
    assert res["status"] == "failed"
    assert not any((api.cfg.data_dir / "entrada").iterdir())


def test_dates_fall_back_to_client_mtime_then_upload_time(api, tmp_path):
    doc = tmp_path / "contrato.pdf"
    doc.write_bytes(b"%PDF-1.4 not really a pdf")
    res = api.upload(doc, created_at="2023-02-03T04:05:06Z")
    item = api.item(res["item_id"])
    assert item["kind"] == "document" and not item["date_uncertain"]
    no_date = tmp_path / "notas.txt"
    no_date.write_text("anotações")
    item2 = api.item(api.upload(no_date)["item_id"])
    assert item2["date_uncertain"] is True


def test_precheck_by_fingerprint_and_hash(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_3.JPG")
    api.upload(photo, created_at=1714569153000)
    res = api.post("/api/precheck", json={"entries": [
        {"key": "a", "name": "IMG_3.JPG", "created_at": "2024-05-01T13:12:33Z", "size": photo.stat().st_size},
        {"key": "b", "sha256": sha(photo)},
        {"key": "c", "name": "IMG_3.JPG", "created_at": "2024-05-01T13:12:33Z", "size": 1},
        {"key": "d", "sha256": "f" * 64},
    ]}).json()["results"]
    by_key = {r["key"]: r for r in res}
    assert by_key["a"]["known"] and by_key["a"]["by"] == "fingerprint" and not by_key["a"]["verified"]
    assert by_key["b"]["known"] and by_key["b"]["verified"]
    assert not by_key["c"]["known"] and not by_key["d"]["known"]


def test_empty_iphone_session_is_safe_only_when_every_file_is_verified(api, tmp_path):
    files = [make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 40, 50, 50)) for i in range(3)]
    copy = tmp_path / "copia" / "IMG_0_copia.JPG"
    copy.parent.mkdir()
    shutil.copy(files[0], copy)  # the iPhone has the same photo twice
    api.upload(files[0])  # sent days ago
    s = api.post("/api/sessions", json={"source": "iphone-empty", "expected_count": 4}).json()
    pre = api.post("/api/precheck", json={"session_id": s["id"], "entries": [
        {"key": str(p), "sha256": sha(p)} for p in (*files, copy)]}).json()["results"]
    assert [r["known"] for r in pre] == [True, False, False, True]
    assert api.get(f"/api/sessions/{s['id']}").json()["safe_to_delete"] is False
    for p in files[1:]:
        api.upload(p, source="iphone-empty", session_id=s["id"], sha256=sha(p), client_key=str(p))
        api.upload(p, source="iphone-empty", session_id=s["id"], sha256=sha(p), client_key=str(p))  # retry
    done = api.post(f"/api/sessions/{s['id']}/finish").json()
    assert done["received_verified_count"] == 4 and done["safe_to_delete"] is True


def test_daily_backup_summary_and_last_time(api, tmp_path):
    daily = api.get("/api/daily").json()
    assert daily["last_at"] is None and daily["overdue"] is False and daily["since"]
    s = api.post("/api/sessions", json={"source": "iphone-daily"}).json()
    api.upload(make_jpeg(tmp_path / "IMG_1.JPG"), source="iphone-daily", session_id=s["id"])
    api.upload(make_jpeg(tmp_path / "IMG_2.JPG", color=(1, 2, 3)), source="iphone-daily", session_id=s["id"])
    done = api.post(f"/api/sessions/{s['id']}/finish").json()
    assert done["summary_text"] == "Backup diário: 2 fotos, 0 vídeos"
    assert api.get("/api/daily").json()["last_at"] is not None
    assert api.get("/api/stats").json()["inbox_count"] == 2  # rule 2: everything lands in the Entrada


def test_shortcuts_multipart_upload(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_8.JPG")
    res = api.post("/api/upload", files={"file": ("IMG_8.JPG", photo.read_bytes(), "image/jpeg")},
                   data={"source": "iphone-manual"})
    assert res.status_code == 200 and res.json()["status"] == "new"
    assert api.item(res.json()["item_id"])["source"] == "iphone-manual"


def test_live_photo_video_is_attached_to_its_photo(api, tmp_path):
    import subprocess
    photo = make_jpeg(tmp_path / "IMG_0001.JPG")
    item_id = api.upload(photo)["item_id"]
    c = db.connect(api.cfg.db_path)
    c.execute("UPDATE items SET live_photo_id = 'ABC-123' WHERE id = ?", (item_id,))
    c.close()
    mov = tmp_path / "IMG_0001.MOV"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=5",
                    "-metadata", "com.apple.quicktime.content.identifier=ABC-123",
                    "-movflags", "use_metadata_tags", str(mov)], check=True)
    res = api.upload(mov)
    assert res["status"] == "attached" and res["item_id"] == item_id
    item = api.item(item_id)
    assert item["is_live_photo"] and item["live_video_url"]
    assert [f["role"] for f in item["files"]] == ["original", "live-video"]
    assert (api.cfg.data_dir / "entrada" / "2024-05-01_1012_IMG_0001.MOV").exists()
    assert api.upload(mov)["status"] == "duplicate"  # the pair is deduplicated too
