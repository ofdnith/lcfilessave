//! Simple upload of one local file to `POST /api/upload` (raw body).
//!
//! The body is streamed from disk, so memory use does not grow with file size.
//! Network failures are retried (the server dedupes by SHA-256, so a retry
//! after a request that actually arrived is harmless).

use std::path::Path;
use std::time::Duration;

use tokio_util::io::ReaderStream;

use crate::transfer::{http_error, net_error, server_join, with_auth};

pub const MAX_ATTEMPTS: u32 = 3;

pub struct UploadParams<'a> {
    pub server_url: &'a str,
    pub token: Option<&'a str>,
    pub path: &'a Path,
    pub source: &'a str,
    pub session_id: Option<i64>,
    pub sha256: Option<&'a str>,
    pub created_ms: Option<i64>,
    /// Stable client-side key (the local path) so the server can match
    /// upload results back to precheck entries.
    pub client_key: Option<&'a str>,
}

/// Builds `/api/upload?source=…&session_id=…&sha256=…&created_at=…&client_key=…`.
pub fn upload_url(p: &UploadParams) -> Result<String, String> {
    let mut q = vec![format!("source={}", urlencoding::encode(p.source))];
    if let Some(s) = p.session_id {
        q.push(format!("session_id={s}"));
    }
    if let Some(h) = p.sha256.filter(|h| !h.is_empty()) {
        q.push(format!("sha256={}", urlencoding::encode(h)));
    }
    if let Some(ms) = p.created_ms {
        q.push(format!("created_at={ms}"));
    }
    if let Some(k) = p.client_key.filter(|k| !k.is_empty()) {
        q.push(format!("client_key={}", urlencoding::encode(k)));
    }
    server_join(p.server_url, &format!("/api/upload?{}", q.join("&")))
}

pub async fn upload_file(
    client: &reqwest::Client,
    p: UploadParams<'_>,
) -> Result<serde_json::Value, String> {
    let file_name = p
        .path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .ok_or_else(|| format!("Caminho sem nome de arquivo: {}", p.path.display()))?;
    let url = upload_url(&p)?;

    let mut last_err = String::new();
    for attempt in 1..=MAX_ATTEMPTS {
        // Re-open each time: a body stream cannot be replayed.
        let file = tokio::fs::File::open(p.path)
            .await
            .map_err(|e| format!("Não consegui abrir {}: {e}", p.path.display()))?;
        let len = file
            .metadata()
            .await
            .map_err(|e| format!("Não consegui ler {}: {e}", p.path.display()))?
            .len();
        let body = reqwest::Body::wrap_stream(ReaderStream::with_capacity(file, 1024 * 1024));
        let req = with_auth(client.post(&url), p.token)
            .header("X-Filename", urlencoding::encode(&file_name).into_owned())
            .header(reqwest::header::CONTENT_TYPE, "application/octet-stream")
            .header(reqwest::header::CONTENT_LENGTH, len)
            .body(body);
        match req.send().await {
            Ok(resp) if resp.status().is_success() => {
                return resp
                    .json::<serde_json::Value>()
                    .await
                    .map_err(|e| format!("Resposta inválida do servidor: {e}"));
            }
            // An HTTP error is an answer, not a network glitch: don't retry.
            Ok(resp) => return Err(http_error(resp).await),
            Err(e) => {
                last_err = net_error(e);
                if attempt < MAX_ATTEMPTS {
                    tokio::time::sleep(Duration::from_millis(500 * 2u64.pow(attempt - 1))).await;
                }
            }
        }
    }
    Err(format!("{last_err} (tentei {MAX_ATTEMPTS} vezes)"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transfer::tests::serve;

    #[test]
    fn builds_query() {
        let p = UploadParams {
            server_url: "http://h:1",
            token: None,
            path: Path::new("/x/Foto 1.HEIC"),
            source: "mac",
            session_id: Some(7),
            sha256: Some("ab"),
            created_ms: Some(1700000000000),
            client_key: Some("/x/Foto 1.HEIC"),
        };
        assert_eq!(
            upload_url(&p).unwrap(),
            "http://h:1/api/upload?source=mac&session_id=7&sha256=ab&created_at=1700000000000&client_key=%2Fx%2FFoto%201.HEIC"
        );
    }

    #[tokio::test]
    async fn streams_body_with_headers() {
        let srv = serve(200, br#"{"status":"new","item_id":3}"#.to_vec());
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("Férias 1.jpg");
        let data: Vec<u8> = (0..300_000u32).map(|i| i as u8).collect();
        std::fs::write(&path, &data).unwrap();
        let v = upload_file(
            &crate::transfer::http_client(),
            UploadParams {
                server_url: &srv.url,
                token: Some("t0k"),
                path: &path,
                source: "mac",
                session_id: Some(1),
                sha256: None,
                created_ms: None,
                client_key: None,
            },
        )
        .await
        .unwrap();
        assert_eq!(v["status"], "new");
        let req = srv.last_request.lock().unwrap().clone();
        let pos = req.windows(4).position(|w| w == b"\r\n\r\n").unwrap();
        let head = String::from_utf8_lossy(&req[..pos]).to_ascii_lowercase();
        assert!(head.starts_with("post /api/upload?source=mac&session_id=1 "), "{head}");
        assert!(head.contains("authorization: bearer t0k"));
        assert!(head.contains("x-filename: f%c3%a9rias%201.jpg"), "{head}");
        assert!(head.contains(&format!("content-length: {}", data.len())));
        assert!(head.contains("content-type: application/octet-stream"));
        assert_eq!(&req[pos + 4..], &data[..]);
    }

    #[tokio::test]
    async fn retries_then_fails_on_unreachable_server() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a.jpg");
        std::fs::write(&path, b"x").unwrap();
        // Bind and drop to get a port nobody listens on.
        let port = std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let url = format!("http://127.0.0.1:{port}");
        let err = upload_file(
            &crate::transfer::http_client(),
            UploadParams {
                server_url: &url, token: None, path: &path, source: "mac",
                session_id: None, sha256: None, created_ms: None, client_key: None,
            },
        )
        .await
        .unwrap_err();
        assert!(err.contains("tentei 3 vezes"), "{err}");
    }
}
