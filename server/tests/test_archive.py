"""Transfer to an external drive, simulating exactly what the Mac app does."""

import hashlib
import sqlite3
from pathlib import Path

from conftest import make_jpeg


def copy_like_the_mac_app(api, drive: Path, plan_file: dict, corrupt: bool = False) -> str:
    data = api.get(plan_file["url"]).content
    dest = drive / plan_file["rel_path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data[:-1] + b"X" if corrupt else data)
    return hashlib.sha256(dest.read_bytes()).hexdigest()  # re-read FROM THE DRIVE


def archive_everything(api, drive: Path) -> dict:
    vol = api.post("/api/volumes", json={"capacity_bytes": 2_000_000_000_000, "filesystem": "exfat"}).json()
    plan = api.get("/api/archive/plan", params={"volume_id": vol["id"]}).json()
    copies = [{"file_id": f["file_id"], "rel_path": f["rel_path"], "sha256": copy_like_the_mac_app(api, drive, f)}
              for f in plan["files"]]
    res = api.post("/api/archive/verified", json={"volume_id": vol["id"], "copies": copies}).json()
    assert not res["rejected"]
    commit = api.post("/api/archive/commit", json={"volume_id": vol["id"]}).json()
    for f in api.get(f"/api/volumes/{vol['id']}/bundle").json()["files"]:
        dest = drive / f["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(api.get(f["url"]).content)
    return {"volume": vol, "plan": plan, "commit": commit}


def kept_photos(api, tmp_path, n=3):
    ids = []
    for i in range(n):
        p = make_jpeg(tmp_path / "src" / f"IMG_{i}.JPG", color=(i * 60, 80, 120), date=f"2023:0{i + 1}:10 09:00:00")
        ids.append(api.upload(p)["item_id"])
    api.run_jobs()
    api.act(ids, "keep")
    return ids


def test_full_archive_flow(api, tmp_path):
    ids = kept_photos(api, tmp_path)
    drive = tmp_path / "hd"
    out = archive_everything(api, drive)
    assert out["volume"]["name"] == "VOLUME-001"
    assert out["commit"]["archived_items"] == 3 and out["commit"]["freed_bytes"] > 0
    assert (drive / "2023" / "01" / "fotos" / "2023-01-10_0900_IMG_0.JPG").exists()

    item = api.item(ids[0])
    assert item["state"] == "archived" and item["volume"]["name"] == "VOLUME-001"
    assert item["original_url"] is None and item["thumb_url"]  # still browsable
    assert item["files"][0]["volumes"] == ["VOLUME-001"]
    assert not list((api.cfg.data_dir / "acervo").rglob("*.JPG"))  # server copy gone
    assert api.get(f"/api/items/{ids[0]}/original").status_code == 410

    # still searchable and listed in the Acervo
    listed = api.get("/api/items", params={"q": "IMG_0"}).json()
    assert [i["id"] for i in listed["items"]] == [ids[0]]

    # the drive is self-sufficient (rule 8)
    html = (drive / "ABRIR-ACERVO.html").read_text()
    assert "VOLUME-001" in html and "2023-01-10_0900_IMG_0.JPG" in html and "/*__ACERVO_DATA__*/" not in html
    vdb = sqlite3.connect(drive / ".acervo" / "catalogo.db")
    assert vdb.execute("SELECT count(*) FROM items").fetchone()[0] == 3
    assert len(list((drive / ".acervo" / "miniaturas").glob("*.webp"))) == 3


def test_corrupted_copy_is_rejected_and_nothing_is_deleted(api, tmp_path):
    ids = kept_photos(api, tmp_path, n=1)
    vol = api.post("/api/volumes", json={"capacity_bytes": 10**12, "filesystem": "exfat"}).json()
    plan = api.get("/api/archive/plan", params={"volume_id": vol["id"]}).json()
    f = plan["files"][0]
    bad = copy_like_the_mac_app(api, tmp_path / "hd", f, corrupt=True)
    res = api.post("/api/archive/verified", json={"volume_id": vol["id"], "copies": [
        {"file_id": f["file_id"], "rel_path": f["rel_path"], "sha256": bad}]}).json()
    assert res["accepted"] == [] and "não confere" in res["rejected"][0]["error"]
    assert api.post("/api/archive/commit", json={"volume_id": vol["id"]}).json()["archived_items"] == 0
    assert api.item(ids[0])["state"] == "library" and api.item(ids[0])["on_server"]


def test_two_copies_policy_waits_for_the_second_drive(cfg, tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from acervo.app import create_app
    from conftest import Api, login
    cfg2 = replace(cfg, archive_copies=2)
    with TestClient(create_app(cfg2)) as client:
        api = Api(client, cfg2, login(client, cfg2))
        ids = kept_photos(api, tmp_path, n=1)
        first = archive_everything(api, tmp_path / "hd1")
        assert first["commit"]["archived_items"] == 0 and api.item(ids[0])["on_server"]
        second = archive_everything(api, tmp_path / "hd2")
        assert second["volume"]["name"] == "VOLUME-002"
        assert second["commit"]["archived_items"] == 1
        assert sorted(api.item(ids[0])["files"][0]["volumes"]) == ["VOLUME-001", "VOLUME-002"]


def test_inbox_items_are_not_archived(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_X.JPG")
    api.upload(p)
    vol = api.post("/api/volumes", json={"capacity_bytes": 10**12, "filesystem": "exfat"}).json()
    assert api.get("/api/archive/plan", params={"volume_id": vol["id"]}).json()["files"] == []


def test_non_exfat_drive_is_refused(api):
    res = api.post("/api/volumes", json={"capacity_bytes": 10**12, "filesystem": "apfs"})
    assert res.status_code == 400


def test_health_check_records_problems(api, tmp_path):
    kept_photos(api, tmp_path, n=2)
    vol = archive_everything(api, tmp_path / "hd")["volume"]
    sample = api.get(f"/api/volumes/{vol['id']}/sample", params={"n": 10}).json()["files"]
    assert len(sample) == 2
    v = api.post(f"/api/volumes/{vol['id']}/checks", json={
        "kind": "full", "files_checked": 2, "problems": [], "checked_file_ids": [s["file_id"] for s in sample]}).json()
    assert v["last_full_check_at"] and v["last_check"]["problems"] == 0 and v["status"] == "active"
    v = api.post(f"/api/volumes/{vol['id']}/checks", json={
        "kind": "partial", "files_checked": 1, "problems": [{"file_id": sample[0]["file_id"], "error": "hash"}]}).json()
    assert v["status"] == "problem"


def test_rel_path_traversal_is_rejected(api, tmp_path):
    kept_photos(api, tmp_path, n=1)
    vol = api.post("/api/volumes", json={"capacity_bytes": 10**12, "filesystem": "exfat"}).json()
    f = api.get("/api/archive/plan", params={"volume_id": vol["id"]}).json()["files"][0]
    res = api.post("/api/archive/verified", json={"volume_id": vol["id"], "copies": [
        {"file_id": f["file_id"], "rel_path": "../../etc/x", "sha256": f["sha256"]}]}).json()
    assert res["rejected"] and not res["accepted"]
