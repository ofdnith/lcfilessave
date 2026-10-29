//! End-to-end test against a real Acervo server (ignored by default).
//!
//! ```sh
//! cd server && ACERVO_DATA_DIR=/tmp/acervo-mac-test .venv/bin/acervo serve &
//! cd mac/src-tauri && ACERVO_TEST_SERVER=http://127.0.0.1:8765 cargo test -- --ignored
//! ```
//! Uses a temp folder as the "HD"; runs from localhost, so no token is needed.

use std::path::Path;

use serde_json::{json, Value};

use crate::{disks, transfer, upload};

fn server() -> String {
    std::env::var("ACERVO_TEST_SERVER").unwrap_or_else(|_| "http://127.0.0.1:8765".into())
}

async fn get(c: &reqwest::Client, url: String) -> Value {
    let r = c.get(&url).send().await.unwrap();
    assert!(r.status().is_success(), "GET {url}: {}", r.status());
    r.json().await.unwrap()
}

async fn post(c: &reqwest::Client, url: String, body: Value) -> Value {
    let r = c.post(&url).json(&body).send().await.unwrap();
    let st = r.status();
    let v: Value = r.json().await.unwrap_or(Value::Null);
    assert!(st.is_success(), "POST {url}: {st} {v}");
    v
}

/// A unique tiny PNG per run so the server sees new content every time.
fn unique_png(seed: u128) -> Vec<u8> {
    // Valid 1x1 PNG header + a trailing tEXt-like payload is fine for the
    // server (it hashes bytes; thumbnails may fail, which doesn't matter here).
    let mut v = vec![
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 0x0D, 0x49, 0x48, 0x44, 0x52, 0,
        0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 0x1F, 0x15, 0xC4, 0x89, 0, 0, 0, 0x0A, 0x49, 0x44,
        0x41, 0x54, 0x78, 0x9C, 0x63, 0, 1, 0, 0, 5, 0, 1, 0x0D, 0x0A, 0x2D, 0xB4, 0, 0, 0, 0,
        0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ];
    v.extend_from_slice(seed.to_string().as_bytes());
    v
}

#[tokio::test]
#[ignore = "needs a running Acervo server (ACERVO_TEST_SERVER)"]
async fn full_archive_flow_against_real_server() {
    let srv = server();
    let c = transfer::http_client();
    let seed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();

    // 1. Upload two files from a "local folder" through upload_file.
    let folder = tempfile::tempdir().unwrap();
    let a = folder.path().join("IMG_0001.png");
    let b = folder.path().join("Nota fiscal ç.pdf");
    std::fs::write(&a, unique_png(seed)).unwrap();
    std::fs::write(&b, format!("%PDF-1.4\n% acervo {seed}\n%%EOF\n")).unwrap();
    let scanned = transfer::scan_folder(folder.path()).unwrap();
    assert_eq!(scanned[0].name, "IMG_0001.png", "photos first");

    let session = post(
        &c,
        format!("{srv}/api/sessions"),
        json!({"source": "mac", "expected_count": 2}),
    )
    .await;
    let session_id = session["id"].as_i64().unwrap();
    let mut item_ids = Vec::new();
    for f in &scanned {
        let sha = transfer::sha256_file(Path::new(&f.path)).unwrap();
        let r = upload::upload_file(
            &c,
            upload::UploadParams {
                server_url: &srv,
                token: None,
                path: Path::new(&f.path),
                source: "mac",
                session_id: Some(session_id),
                sha256: Some(&sha),
                created_ms: Some(f.modified_ms),
                client_key: Some(&f.path),
            },
        )
        .await
        .unwrap();
        assert_eq!(r["status"], "new", "{r}");
        item_ids.push(r["item_id"].as_i64().unwrap());
    }
    let fin = post(
        &c,
        format!("{srv}/api/sessions/{session_id}/finish"),
        json!({}),
    )
    .await;
    assert_eq!(fin["safe_to_delete"], true, "{fin}");

    // Same content again -> duplicate (dedupe by hash, rule 4).
    let again = upload::upload_file(
        &c,
        upload::UploadParams {
            server_url: &srv,
            token: None,
            path: &a,
            source: "mac",
            session_id: None,
            sha256: None,
            created_ms: None,
            client_key: None,
        },
    )
    .await
    .unwrap();
    assert_eq!(again["status"], "duplicate", "{again}");

    // 2. Keep them (Entrada -> Acervo) so they become archivable.
    let kept = post(
        &c,
        format!("{srv}/api/items/actions"),
        json!({"ids": item_ids, "action": "keep"}),
    )
    .await;
    assert_eq!(kept["ok"].as_array().unwrap().len(), 2, "{kept}");

    // 3. New volume on a fake exFAT disk.
    let hd = tempfile::tempdir().unwrap();
    let vol = post(
        &c,
        format!("{srv}/api/volumes"),
        json!({"capacity_bytes": 1_000_000_000u64, "filesystem": "exfat"}),
    )
    .await;
    let vid = vol["id"].as_str().unwrap().to_string();
    let vj = disks::init_volume_at(
        hd.path(),
        "exfat",
        &vid,
        vol["name"].as_str().unwrap(),
        vol["created_at"].as_str().unwrap_or(""),
    )
    .unwrap();
    assert_eq!(
        disks::build_disk(hd.path(), "exfat", 0, 0, false)
            .volume
            .unwrap()
            .id,
        vj.id
    );

    // 4. Plan, copy with read-back verification, report.
    let plan = get(&c, format!("{srv}/api/archive/plan?volume_id={vid}")).await;
    let files = plan["files"].as_array().unwrap();
    let ours: Vec<&Value> = files
        .iter()
        .filter(|f| item_ids.contains(&f["item_id"].as_i64().unwrap()))
        .collect();
    assert_eq!(ours.len(), 2, "{plan}");
    let mut copies = Vec::new();
    for f in files {
        let r = transfer::copy_to_volume(
            &c,
            &srv,
            None,
            hd.path(),
            f["url"].as_str().unwrap(),
            f["rel_path"].as_str().unwrap(),
            f["sha256"].as_str().unwrap(),
            f["size_bytes"].as_u64(),
            |_, _| {},
        )
        .await
        .unwrap();
        assert!(!r.skipped);
        copies
            .push(json!({"file_id": f["file_id"], "rel_path": f["rel_path"], "sha256": r.sha256}));
    }
    // Copying again is a no-op (already on the HD with the right hash).
    let f0 = &files[0];
    let again = transfer::copy_to_volume(
        &c,
        &srv,
        None,
        hd.path(),
        f0["url"].as_str().unwrap(),
        f0["rel_path"].as_str().unwrap(),
        f0["sha256"].as_str().unwrap(),
        f0["size_bytes"].as_u64(),
        |_, _| {},
    )
    .await
    .unwrap();
    assert!(again.skipped);

    let ver = post(
        &c,
        format!("{srv}/api/archive/verified"),
        json!({"volume_id": vid, "copies": copies}),
    )
    .await;
    assert!(ver["rejected"].as_array().unwrap().is_empty(), "{ver}");

    // 5. Commit: the server may now drop its copies (rule 3 satisfied).
    let commit = post(
        &c,
        format!("{srv}/api/archive/commit"),
        json!({"volume_id": vid}),
    )
    .await;
    assert!(commit["archived_items"].as_u64().unwrap() >= 2, "{commit}");
    // The original is gone from the server...
    let gone = c
        .get(format!("{srv}{}", f0["url"].as_str().unwrap()))
        .send()
        .await
        .unwrap();
    assert_eq!(gone.status().as_u16(), 404);

    // 6. Bundle: catalog + offline HTML (+ thumbnails when they exist).
    let bundle = get(&c, format!("{srv}/api/volumes/{vid}/bundle")).await;
    for bf in bundle["files"].as_array().unwrap() {
        transfer::write_bundle_file(
            &c,
            &srv,
            None,
            hd.path(),
            bf["path"].as_str().unwrap(),
            bf["url"].as_str().unwrap(),
        )
        .await
        .unwrap();
    }
    assert!(hd.path().join("ABRIR-ACERVO.html").is_file());
    assert!(hd.path().join(".acervo/catalogo.db").is_file());
    assert!(
        disks::volume_json_path(hd.path()).is_file(),
        "bundle must not clobber volume.json"
    );

    // 7. Health check on the HD, then corrupt one file and check again.
    let sample = get(&c, format!("{srv}/api/volumes/{vid}/sample?n=50&full=1")).await;
    let to_check: Vec<transfer::VerifyFile> =
        serde_json::from_value(sample["files"].clone()).unwrap();
    assert!(to_check.len() >= 2);
    assert!(to_check
        .iter()
        .all(|f| transfer::verify_one(hd.path(), f).ok));
    let victim = hd.path().join(&to_check[0].rel_path);
    std::fs::write(&victim, b"bit rot").unwrap();
    let r = transfer::verify_one(hd.path(), &to_check[0]);
    assert!(!r.ok, "corruption must be detected");
}
