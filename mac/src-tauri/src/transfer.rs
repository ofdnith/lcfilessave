//! Copying originals from the server to an Acervo HD, with verification.
//!
//! Inviolable rule 3: the server only deletes a file after the HD copy has been
//! verified by SHA-256. This module is the HD side of that guarantee:
//!
//! 1. download into `<rel_path>.part` on the HD;
//! 2. fsync the file and its folder, rename to the final name, fsync again;
//! 3. re-open the final file **from the disk** and hash it again;
//! 4. only a matching hash is reported back (the server re-checks it in
//!    `POST /api/archive/verified`). A mismatching copy is removed from the HD.
//!
//! Nothing here ever deletes anything except a `.part` file or a copy on the
//! HD that we just wrote and that failed verification.

use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant, UNIX_EPOCH};

use futures_util::{Stream, StreamExt};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;

pub const HASH_BUF: usize = 1024 * 1024;
/// Keep this much free on the HD on top of the file being copied.
pub const FREE_SPACE_MARGIN: u64 = 64 * 1024 * 1024;
/// Minimum interval between progress events.
pub const PROGRESS_INTERVAL: Duration = Duration::from_millis(100);

/// Short Portuguese description of an I/O error (the UI shows these as-is).
pub fn io_pt(e: &io::Error) -> String {
    use io::ErrorKind as K;
    let msg = match e.kind() {
        K::NotFound => "não encontrado",
        K::PermissionDenied => {
            "sem permissão (libere o Acervo em Ajustes do Sistema › Privacidade e Segurança)"
        }
        K::AlreadyExists => "já existe",
        K::StorageFull => "disco cheio",
        K::ReadOnlyFilesystem => "disco só para leitura",
        K::NotADirectory => "não é uma pasta",
        K::IsADirectory => "é uma pasta",
        K::UnexpectedEof => "arquivo terminou antes do esperado",
        K::Interrupted | K::TimedOut => "operação interrompida",
        K::InvalidInput | K::InvalidData | K::InvalidFilename => "nome ou dado inválido",
        K::ResourceBusy => "em uso por outro programa",
        _ => match e.raw_os_error() {
            Some(libc::EIO) => "erro de leitura/gravação no disco (cabo ou disco com defeito?)",
            Some(libc::ENXIO) | Some(libc::ENODEV) => "o disco foi desconectado",
            _ => return format!("erro do sistema ({e})"),
        },
    };
    msg.to_string()
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

/// Validates a relative path that comes from the server/page and joins it to
/// the mount point. Rejects absolute paths, `..`, `.`, empty components,
/// backslashes, NUL and control characters.
pub fn safe_join(mount: &Path, rel_path: &str) -> Result<PathBuf, String> {
    let bad = || format!("Caminho inválido: {rel_path:?}");
    if rel_path.is_empty()
        || rel_path.len() > 1024
        || rel_path.starts_with('/')
        || rel_path.contains('\\')
        || rel_path.chars().any(|c| c.is_control())
    {
        return Err(bad());
    }
    let p = Path::new(rel_path);
    // Check raw segments: Path::components() would silently drop "." and "".
    if rel_path
        .split('/')
        .any(|seg| seg.is_empty() || seg == "." || seg == "..")
    {
        return Err(bad());
    }
    // Belt and braces: every component must be a plain name.
    if !p.components().all(|c| matches!(c, Component::Normal(_))) {
        return Err(bad());
    }
    if rel_path.ends_with(".part") || rel_path.ends_with(".tmp") {
        return Err(bad());
    }
    Ok(mount.join(p))
}

/// Paths for originals must not land inside `.acervo/` (reserved for the
/// catalog and thumbnails, written by `write_bundle_file`).
pub fn validate_original_rel_path(rel_path: &str) -> Result<(), String> {
    let first = rel_path.split('/').next().unwrap_or("");
    if first.eq_ignore_ascii_case(crate::disks::ACERVO_DIR) {
        return Err(format!("Caminho reservado: {rel_path}"));
    }
    Ok(())
}

/// Creates the parent folders of `target` and makes sure that, after
/// resolving symlinks, they are still inside `mount`.
fn prepare_parent(mount: &Path, target: &Path) -> Result<PathBuf, String> {
    let parent = target.parent().ok_or("Caminho sem pasta")?.to_path_buf();
    fs::create_dir_all(&parent).map_err(|e| {
        format!(
            "Não consegui criar a pasta {}: {}",
            parent.display(),
            io_pt(&e)
        )
    })?;
    let real_mount = fs::canonicalize(mount)
        .map_err(|e| format!("Disco inacessível ({}): {}", mount.display(), io_pt(&e)))?;
    let real_parent = fs::canonicalize(&parent)
        .map_err(|e| format!("Pasta inacessível ({}): {}", parent.display(), io_pt(&e)))?;
    if !real_parent.starts_with(&real_mount) {
        return Err("O caminho sai do disco (link simbólico?). Recusado.".into());
    }
    if let Ok(meta) = fs::symlink_metadata(target) {
        if meta.file_type().is_symlink() || meta.is_dir() {
            return Err(format!("{} não é um arquivo comum.", target.display()));
        }
    }
    Ok(parent)
}

pub fn part_path(target: &Path) -> PathBuf {
    let mut name = target.file_name().unwrap_or_default().to_os_string();
    name.push(".part");
    target.with_file_name(name)
}

/// Best-effort fsync of a directory so a rename survives power loss.
/// Some filesystems (exFAT on macOS among them) refuse fsync on directories;
/// that is not an error worth failing a copy for — the file data itself is
/// already fsynced, and the read-back hash proves it is on disk.
pub fn fsync_dir(dir: &Path) {
    if let Ok(d) = File::open(dir) {
        let _ = d.sync_all();
    }
}

// ---------------------------------------------------------------------------
// Hashing
// ---------------------------------------------------------------------------

/// Streaming SHA-256 of a file, 1 MiB at a time. Blocking: call it from
/// `spawn_blocking`.
pub fn sha256_file(path: &Path) -> io::Result<String> {
    let mut f = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; HASH_BUF];
    loop {
        let n = match f.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        hasher.update(&buf[..n]);
    }
    Ok(hex::encode(hasher.finalize()))
}

pub async fn sha256_file_async(path: PathBuf) -> io::Result<String> {
    tokio::task::spawn_blocking(move || sha256_file(&path))
        .await
        .map_err(io::Error::other)?
}

fn normalize_hash(h: &str) -> Result<String, String> {
    let h = h.trim().to_ascii_lowercase();
    if h.len() != 64 || !h.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(format!("SHA-256 inválido: {h:?}"));
    }
    Ok(h)
}

// ---------------------------------------------------------------------------
// Atomic write from a byte stream
// ---------------------------------------------------------------------------

/// Calls `f(done, total)` at most every [`PROGRESS_INTERVAL`] plus once at the end.
pub struct Throttle<F: FnMut(u64, u64)> {
    f: F,
    last: Option<Instant>,
}

impl<F: FnMut(u64, u64)> Throttle<F> {
    pub fn new(f: F) -> Self {
        Self { f, last: None }
    }
    pub fn tick(&mut self, done: u64, total: u64) {
        let now = Instant::now();
        if self
            .last
            .is_none_or(|t| now.duration_since(t) >= PROGRESS_INTERVAL)
        {
            self.last = Some(now);
            (self.f)(done, total);
        }
    }
    pub fn finish(&mut self, done: u64, total: u64) {
        (self.f)(done, total);
    }
}

/// Writes `stream` to `<target>.part`, fsyncs, renames to `target`, fsyncs the
/// folder. Removes the `.part` file on any error. Returns bytes written.
pub async fn write_stream_atomic<S, E, F>(
    mount: &Path,
    target: &Path,
    mut stream: S,
    total: u64,
    progress: F,
) -> Result<u64, String>
where
    S: Stream<Item = Result<bytes::Bytes, E>> + Unpin,
    E: std::fmt::Display,
    F: FnMut(u64, u64),
{
    let parent = prepare_parent(mount, target)?;
    let part = part_path(target);
    let result: Result<u64, String> = async {
        let mut file = tokio::fs::File::create(&part)
            .await
            .map_err(|e| format!("Não consegui criar {}: {}", part.display(), io_pt(&e)))?;
        let mut done = 0u64;
        let mut throttle = Throttle::new(progress);
        throttle.tick(0, total);
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("Falha ao baixar do servidor: {e}"))?;
            file.write_all(&chunk)
                .await
                .map_err(|e| format!("Falha ao gravar no disco: {}", io_pt(&e)))?;
            done += chunk.len() as u64;
            throttle.tick(done, total);
        }
        file.flush()
            .await
            .map_err(|e| format!("Falha ao gravar no disco: {}", io_pt(&e)))?;
        // On macOS std's sync_all uses F_FULLFSYNC, which also flushes the
        // drive's own write cache — what we want before trusting an HD copy.
        file.sync_all()
            .await
            .map_err(|e| format!("Falha ao confirmar a gravação no disco: {}", io_pt(&e)))?;
        drop(file);
        throttle.finish(done, total);
        Ok(done)
    }
    .await;
    match result {
        Ok(done) => {
            if let Err(e) = fs::rename(&part, target) {
                let _ = fs::remove_file(&part);
                return Err(format!(
                    "Não consegui renomear {}: {}",
                    part.display(),
                    io_pt(&e)
                ));
            }
            fsync_dir(&parent);
            Ok(done)
        }
        Err(e) => {
            let _ = fs::remove_file(&part);
            Err(e)
        }
    }
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

pub fn http_client() -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(Duration::from_secs(120))
        .user_agent(concat!("Acervo-Mac/", env!("CARGO_PKG_VERSION")))
        .build()
        .expect("http client")
}

/// Joins the server origin with a server-relative URL such as
/// `/api/files/1/content`. Absolute URLs are refused so a token is never sent
/// to another host.
pub fn server_join(server_url: &str, url: &str) -> Result<String, String> {
    if !url.starts_with('/') || url.starts_with("//") {
        return Err(format!("URL do servidor inválida: {url}"));
    }
    Ok(format!("{}{}", server_url.trim_end_matches('/'), url))
}

pub fn with_auth(req: reqwest::RequestBuilder, token: Option<&str>) -> reqwest::RequestBuilder {
    match token.map(str::trim).filter(|t| !t.is_empty()) {
        Some(t) => req.bearer_auth(t),
        None => req,
    }
}

/// Human message for a failed HTTP response, using the server's `{error}` if any.
pub async fn http_error(resp: reqwest::Response) -> String {
    let status = resp.status();
    let detail = resp.json::<serde_json::Value>().await.ok().and_then(|v| {
        v.get("error")
            .or_else(|| v.get("detail"))
            .and_then(|e| e.as_str().map(str::to_string))
    });
    let base = match status.as_u16() {
        401 => "O servidor pediu login de novo (token inválido ou expirado).".to_string(),
        403 => "O servidor recusou o acesso.".to_string(),
        404 => "Arquivo não encontrado no servidor.".to_string(),
        410 => "Este arquivo não está mais no servidor (já está num HD).".to_string(),
        s => format!("O servidor respondeu com erro {s}."),
    };
    match detail {
        Some(d) => format!("{base} {d}"),
        None => base,
    }
}

pub fn net_error(e: reqwest::Error) -> String {
    if e.is_timeout() {
        "O servidor demorou demais para responder.".into()
    } else if e.is_connect() {
        "Não consegui conectar ao servidor. Ele está ligado e na mesma rede?".into()
    } else {
        format!("Falha de rede: {e}")
    }
}

#[allow(clippy::too_many_arguments)]
async fn download_to(
    client: &reqwest::Client,
    server_url: &str,
    token: Option<&str>,
    url: &str,
    mount: &Path,
    target: &Path,
    expected_size: Option<u64>,
    progress: impl FnMut(u64, u64),
) -> Result<u64, String> {
    let full = server_join(server_url, url)?;
    let resp = with_auth(client.get(&full), token)
        .send()
        .await
        .map_err(net_error)?;
    if !resp.status().is_success() {
        return Err(http_error(resp).await);
    }
    let total = expected_size.or(resp.content_length()).unwrap_or(0);
    let need = total.saturating_add(FREE_SPACE_MARGIN);
    if let Some(free) = crate::disks::free_bytes(mount) {
        if free < need {
            return Err(format!(
                "Espaço insuficiente no disco: livres {}, necessários {}.",
                human_bytes(free),
                human_bytes(need)
            ));
        }
    }
    let written = write_stream_atomic(mount, target, resp.bytes_stream(), total, progress).await?;
    if let Some(exp) = expected_size {
        if written != exp {
            let _ = fs::remove_file(target);
            return Err(format!(
                "Tamanho errado ao baixar ({written} bytes, esperado {exp}). Cópia removida."
            ));
        }
    }
    Ok(written)
}

pub fn human_bytes(b: u64) -> String {
    const U: [&str; 5] = ["B", "KB", "MB", "GB", "TB"];
    let mut v = b as f64;
    let mut i = 0;
    while v >= 1000.0 && i < U.len() - 1 {
        v /= 1000.0;
        i += 1;
    }
    if i == 0 {
        format!("{b} B")
    } else {
        format!("{v:.1} {}", U[i]).replace('.', ",")
    }
}

// ---------------------------------------------------------------------------
// copy_to_volume
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CopyResult {
    /// Hash of the file as re-read from the HD after writing.
    pub sha256: String,
    /// True when the file was already on the HD with the right hash.
    pub skipped: bool,
}

/// Copies one original to the HD and proves it by re-reading it.
#[allow(clippy::too_many_arguments)]
pub async fn copy_to_volume(
    client: &reqwest::Client,
    server_url: &str,
    token: Option<&str>,
    mount: &Path,
    url: &str,
    rel_path: &str,
    sha256: &str,
    size_bytes: Option<u64>,
    progress: impl FnMut(u64, u64),
) -> Result<CopyResult, String> {
    let expected = normalize_hash(sha256)?;
    validate_original_rel_path(rel_path)?;
    let target = safe_join(mount, rel_path)?;

    // Already there? Only trust it after hashing it.
    if let Ok(meta) = fs::symlink_metadata(&target) {
        if !meta.is_file() {
            return Err(format!(
                "{rel_path} existe no disco mas não é um arquivo comum."
            ));
        }
        let size_ok = size_bytes.is_none_or(|s| s == meta.len());
        let existing = if size_ok {
            sha256_file_async(target.clone())
                .await
                .map_err(|e| format!("Não consegui ler {rel_path} no disco: {}", io_pt(&e)))?
        } else {
            String::new()
        };
        if existing == expected {
            return Ok(CopyResult {
                sha256: existing,
                skipped: true,
            });
        }
        // A different file already sits where this original should go. It is
        // not ours to overwrite or delete: stop and let the user look.
        return Err(format!(
            "Já existe no disco um arquivo diferente em {rel_path}. Não vou sobrescrever."
        ));
    }

    download_to(
        client, server_url, token, url, mount, &target, size_bytes, progress,
    )
    .await?;

    // Read back from the disk — this hash, not the downloaded bytes, is what counts.
    let reread = match sha256_file_async(target.clone()).await {
        Ok(h) => h,
        Err(e) => {
            let _ = fs::remove_file(&target);
            return Err(format!(
                "Não consegui reler {rel_path} do disco: {}. Cópia removida.",
                io_pt(&e)
            ));
        }
    };
    if reread != expected {
        let _ = fs::remove_file(&target);
        fsync_dir(target.parent().unwrap_or(mount));
        return Err(format!(
            "A cópia de {rel_path} no disco não confere (SHA-256 diferente). Cópia removida."
        ));
    }
    Ok(CopyResult {
        sha256: reread,
        skipped: false,
    })
}

/// Downloads a bundle file (catalog, HTML, thumbnails) with an atomic write.
pub async fn write_bundle_file(
    client: &reqwest::Client,
    server_url: &str,
    token: Option<&str>,
    mount: &Path,
    path: &str,
    url: &str,
) -> Result<(), String> {
    let target = safe_join(mount, path)?;
    download_to(
        client,
        server_url,
        token,
        url,
        mount,
        &target,
        None,
        |_, _| {},
    )
    .await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// verify_volume_files
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct VerifyFile {
    pub file_id: i64,
    pub rel_path: String,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct VerifyResult {
    pub file_id: i64,
    pub ok: bool,
    pub error: Option<String>,
}

pub fn verify_one(mount: &Path, f: &VerifyFile) -> VerifyResult {
    let fail = |msg: String| VerifyResult {
        file_id: f.file_id,
        ok: false,
        error: Some(msg),
    };
    let expected = match normalize_hash(&f.sha256) {
        Ok(h) => h,
        Err(e) => return fail(e),
    };
    let path = match safe_join(mount, &f.rel_path) {
        Ok(p) => p,
        Err(e) => return fail(e),
    };
    match sha256_file(&path) {
        Ok(h) if h == expected => VerifyResult {
            file_id: f.file_id,
            ok: true,
            error: None,
        },
        Ok(_) => fail("Conteúdo diferente do original (SHA-256 não confere).".into()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            fail("Arquivo não encontrado no disco.".into())
        }
        Err(e) => fail(format!("Não consegui ler o arquivo: {}", io_pt(&e))),
    }
}

// ---------------------------------------------------------------------------
// scan_folder
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ScannedFile {
    pub path: String,
    pub name: String,
    pub size: u64,
    pub modified_ms: i64,
}

const PHOTO_EXT: &[&str] = &[
    "heic", "heif", "jpg", "jpeg", "png", "gif", "webp", "tif", "tiff", "dng", "raw", "cr2", "cr3",
    "nef", "arw", "orf", "rw2", "raf", "bmp", "avif",
];
const VIDEO_EXT: &[&str] = &[
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mts", "m2ts", "webm", "wmv", "mpg", "mpeg",
];

/// 0 = photo, 1 = anything else, 2 = video. Photos go first so a Live Photo's
/// video finds its photo already on the server.
pub fn kind_rank(name: &str) -> u8 {
    let ext = Path::new(name)
        .extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    if PHOTO_EXT.contains(&ext.as_str()) {
        0
    } else if VIDEO_EXT.contains(&ext.as_str()) {
        2
    } else {
        1
    }
}

/// Recursive listing; skips hidden files/folders (".*", including .DS_Store)
/// and does not follow symlinks.
pub fn scan_folder(root: &Path) -> Result<Vec<ScannedFile>, String> {
    let meta = fs::metadata(root)
        .map_err(|e| format!("Pasta inacessível ({}): {}", root.display(), io_pt(&e)))?;
    if !meta.is_dir() {
        return Err(format!("{} não é uma pasta.", root.display()));
    }
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') || name == "Icon\r" {
                continue;
            }
            let Ok(ft) = entry.file_type() else { continue };
            if ft.is_dir() {
                stack.push(entry.path());
            } else if ft.is_file() {
                let Ok(m) = entry.metadata() else { continue };
                let modified_ms = m
                    .modified()
                    .ok()
                    .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
                    .map(|d| d.as_millis() as i64)
                    .unwrap_or(0);
                out.push(ScannedFile {
                    path: entry.path().to_string_lossy().into_owned(),
                    name,
                    size: m.len(),
                    modified_ms,
                });
            }
        }
    }
    sort_scanned(&mut out);
    Ok(out)
}

pub fn sort_scanned(files: &mut [ScannedFile]) {
    files.sort_by(|a, b| {
        kind_rank(&a.name)
            .cmp(&kind_rank(&b.name))
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
            .then_with(|| a.path.cmp(&b.path))
    });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use std::io::Write as _;
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    pub fn sha_hex(data: &[u8]) -> String {
        hex::encode(Sha256::digest(data))
    }

    /// Tiny HTTP/1.1 server for tests: serves `body` for every GET, counts
    /// requests, and records the last request head + body.
    pub struct TestServer {
        pub url: String,
        pub hits: Arc<AtomicUsize>,
        pub last_request: Arc<std::sync::Mutex<Vec<u8>>>,
    }

    pub fn serve(status: u16, body: Vec<u8>) -> TestServer {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let hits = Arc::new(AtomicUsize::new(0));
        let last_request = Arc::new(std::sync::Mutex::new(Vec::new()));
        let (h, lr) = (hits.clone(), last_request.clone());
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut s) = stream else { continue };
                h.fetch_add(1, Ordering::SeqCst);
                let req = read_request(&mut s);
                *lr.lock().unwrap() = req;
                let head = format!(
                    "HTTP/1.1 {status} X\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                let _ = s.write_all(head.as_bytes());
                let _ = s.write_all(&body);
            }
        });
        TestServer {
            url,
            hits,
            last_request,
        }
    }

    fn read_request(s: &mut std::net::TcpStream) -> Vec<u8> {
        let mut buf = Vec::new();
        let mut tmp = [0u8; 65536];
        loop {
            let n = s.read(&mut tmp).unwrap_or(0);
            if n == 0 {
                break;
            }
            buf.extend_from_slice(&tmp[..n]);
            if let Some(pos) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                let head = String::from_utf8_lossy(&buf[..pos]).to_ascii_lowercase();
                let len = head
                    .lines()
                    .find_map(|l| l.strip_prefix("content-length:"))
                    .and_then(|v| v.trim().parse::<usize>().ok())
                    .unwrap_or(0);
                if buf.len() >= pos + 4 + len {
                    break;
                }
            }
        }
        buf
    }

    #[test]
    fn rel_path_validation() {
        let m = Path::new("/Volumes/HD");
        assert_eq!(
            safe_join(m, "2024/05/fotos/a.heic").unwrap(),
            PathBuf::from("/Volumes/HD/2024/05/fotos/a.heic")
        );
        assert!(safe_join(m, ".acervo/catalogo.db").is_ok());
        for bad in [
            "",
            "/etc/passwd",
            "../x",
            "a/../../x",
            "a/./b",
            "a//b",
            "a/",
            "a\\b",
            "a\0b",
            "a/b.part",
            "..",
        ] {
            assert!(safe_join(m, bad).is_err(), "{bad:?} should be rejected");
        }
        assert!(validate_original_rel_path(".acervo/volume.json").is_err());
        assert!(validate_original_rel_path("2024/a.jpg").is_ok());
    }

    #[test]
    fn hash_file_streams() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f");
        let data: Vec<u8> = (0..3 * HASH_BUF + 17).map(|i| (i % 251) as u8).collect();
        fs::write(&p, &data).unwrap();
        assert_eq!(sha256_file(&p).unwrap(), sha_hex(&data));
    }

    #[tokio::test]
    async fn copy_happy_path_then_skip() {
        let data = b"conteudo original da foto".to_vec();
        let sha = sha_hex(&data);
        let srv = serve(200, data.clone());
        let disk = tempfile::tempdir().unwrap();
        let client = http_client();
        let mut events = Vec::new();
        let r = copy_to_volume(
            &client,
            &srv.url,
            Some("tok"),
            disk.path(),
            "/api/files/1/content",
            "2024/05/fotos/a.jpg",
            &sha,
            Some(data.len() as u64),
            |d, t| events.push((d, t)),
        )
        .await
        .unwrap();
        assert_eq!(
            r,
            CopyResult {
                sha256: sha.clone(),
                skipped: false
            }
        );
        let final_path = disk.path().join("2024/05/fotos/a.jpg");
        assert_eq!(fs::read(&final_path).unwrap(), data);
        assert!(!part_path(&final_path).exists());
        assert_eq!(events.last(), Some(&(data.len() as u64, data.len() as u64)));
        let req = String::from_utf8_lossy(&srv.last_request.lock().unwrap()).to_string();
        assert!(req.starts_with("GET /api/files/1/content "), "{req}");
        assert!(
            req.to_ascii_lowercase()
                .contains("authorization: bearer tok"),
            "{req}"
        );

        // Second time: already there with the right hash -> no download.
        let r2 = copy_to_volume(
            &client,
            &srv.url,
            Some("tok"),
            disk.path(),
            "/api/files/1/content",
            "2024/05/fotos/a.jpg",
            &sha.to_uppercase(),
            Some(data.len() as u64),
            |_, _| {},
        )
        .await
        .unwrap();
        assert!(r2.skipped);
        assert_eq!(srv.hits.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn corrupted_copy_is_detected_and_removed() {
        // The server sends bytes whose hash is not the expected one
        // (simulates corruption on the way or on the disk).
        let srv = serve(200, b"bytes corrompidos".to_vec());
        let disk = tempfile::tempdir().unwrap();
        let expected = sha_hex(b"bytes originais");
        let err = copy_to_volume(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "/api/files/2/content",
            "2024/06/fotos/b.jpg",
            &expected,
            None,
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(err.contains("não confere"), "{err}");
        let target = disk.path().join("2024/06/fotos/b.jpg");
        assert!(!target.exists(), "bad copy must be removed");
        assert!(!part_path(&target).exists());
    }

    #[tokio::test]
    async fn wrong_size_is_rejected() {
        let data = b"abc".to_vec();
        let srv = serve(200, data.clone());
        let disk = tempfile::tempdir().unwrap();
        let err = copy_to_volume(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "/x",
            "a/b.jpg",
            &sha_hex(&data),
            Some(10),
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(err.contains("Tamanho"), "{err}");
        assert!(!disk.path().join("a/b.jpg").exists());
    }

    #[tokio::test]
    async fn existing_different_file_is_not_overwritten() {
        let srv = serve(200, b"novo".to_vec());
        let disk = tempfile::tempdir().unwrap();
        fs::create_dir_all(disk.path().join("a")).unwrap();
        fs::write(disk.path().join("a/b.jpg"), b"outro arquivo").unwrap();
        let err = copy_to_volume(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "/x",
            "a/b.jpg",
            &sha_hex(b"novo"),
            None,
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(err.contains("diferente"), "{err}");
        assert_eq!(
            fs::read(disk.path().join("a/b.jpg")).unwrap(),
            b"outro arquivo"
        );
        assert_eq!(srv.hits.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn traversal_rejected_before_any_request() {
        let srv = serve(200, b"x".to_vec());
        let disk = tempfile::tempdir().unwrap();
        for bad in ["../fora.jpg", "/etc/x", ".acervo/volume.json"] {
            let r = copy_to_volume(
                &http_client(),
                &srv.url,
                None,
                disk.path(),
                "/x",
                bad,
                &sha_hex(b"x"),
                None,
                |_, _| {},
            )
            .await;
            assert!(r.is_err(), "{bad}");
        }
        assert_eq!(srv.hits.load(Ordering::SeqCst), 0);
        // Absolute or protocol-relative URLs are refused (token never leaves).
        assert!(server_join(&srv.url, "http://evil/x").is_err());
        assert!(server_join(&srv.url, "//evil/x").is_err());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn symlink_escape_rejected() {
        let srv = serve(200, b"x".to_vec());
        let disk = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(outside.path(), disk.path().join("2024")).unwrap();
        let err = copy_to_volume(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "/x",
            "2024/a.jpg",
            &sha_hex(b"x"),
            None,
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(err.contains("sai do disco"), "{err}");
        assert!(fs::read_dir(outside.path()).unwrap().next().is_none());
    }

    #[tokio::test]
    async fn http_error_leaves_nothing() {
        let srv = serve(410, br#"{"error":"no HD","volume":"VOLUME-001"}"#.to_vec());
        let disk = tempfile::tempdir().unwrap();
        let err = copy_to_volume(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "/x",
            "a/b.jpg",
            &sha_hex(b"x"),
            None,
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(err.contains("não está mais no servidor"), "{err}");
        assert!(!disk.path().join("a/b.jpg").exists());
    }

    #[tokio::test]
    async fn bundle_file_overwrites_atomically() {
        let srv = serve(200, b"<html>novo</html>".to_vec());
        let disk = tempfile::tempdir().unwrap();
        fs::write(disk.path().join("ABRIR-ACERVO.html"), b"velho").unwrap();
        write_bundle_file(
            &http_client(),
            &srv.url,
            None,
            disk.path(),
            "ABRIR-ACERVO.html",
            "/b",
        )
        .await
        .unwrap();
        assert_eq!(
            fs::read(disk.path().join("ABRIR-ACERVO.html")).unwrap(),
            b"<html>novo</html>"
        );
        assert!(
            write_bundle_file(&http_client(), &srv.url, None, disk.path(), "../x", "/b")
                .await
                .is_err()
        );
    }

    #[test]
    fn verify_reports_each_problem() {
        let disk = tempfile::tempdir().unwrap();
        fs::create_dir_all(disk.path().join("a")).unwrap();
        fs::write(disk.path().join("a/ok.jpg"), b"ok").unwrap();
        fs::write(disk.path().join("a/bad.jpg"), b"mudou").unwrap();
        let files = [
            VerifyFile {
                file_id: 1,
                rel_path: "a/ok.jpg".into(),
                sha256: sha_hex(b"ok"),
            },
            VerifyFile {
                file_id: 2,
                rel_path: "a/bad.jpg".into(),
                sha256: sha_hex(b"orig"),
            },
            VerifyFile {
                file_id: 3,
                rel_path: "a/sumiu.jpg".into(),
                sha256: sha_hex(b"x"),
            },
            VerifyFile {
                file_id: 4,
                rel_path: "../x".into(),
                sha256: sha_hex(b"x"),
            },
        ];
        let r: Vec<_> = files.iter().map(|f| verify_one(disk.path(), f)).collect();
        assert!(r[0].ok && r[0].error.is_none());
        assert!(!r[1].ok && r[1].error.as_deref().unwrap().contains("SHA-256"));
        assert!(!r[2].ok && r[2].error.as_deref().unwrap().contains("não encontrado"));
        assert!(!r[3].ok);
    }

    #[test]
    fn scan_orders_photos_first_and_skips_hidden() {
        let dir = tempfile::tempdir().unwrap();
        let d = dir.path();
        fs::create_dir_all(d.join("sub")).unwrap();
        fs::create_dir_all(d.join(".escondida")).unwrap();
        for (p, c) in [
            ("IMG_2.MOV", "v"),
            ("IMG_2.HEIC", "p"),
            ("sub/IMG_1.jpg", "p"),
            ("nota.pdf", "d"),
            (".DS_Store", "x"),
            (".escondida/x.jpg", "x"),
            ("a.mp4", "v"),
        ] {
            fs::write(d.join(p), c).unwrap();
        }
        let names: Vec<_> = scan_folder(d)
            .unwrap()
            .into_iter()
            .map(|f| f.name)
            .collect();
        assert_eq!(
            names,
            ["IMG_1.jpg", "IMG_2.HEIC", "nota.pdf", "a.mp4", "IMG_2.MOV"]
        );
        assert!(scan_folder(&d.join("nao-existe")).is_err());
    }

    #[test]
    fn human_bytes_pt() {
        assert_eq!(human_bytes(512), "512 B");
        assert_eq!(human_bytes(1_500_000_000), "1,5 GB");
    }
}
