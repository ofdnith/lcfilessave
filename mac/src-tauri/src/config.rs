//! Persistent app settings (just the server address for now).
//!
//! Stored as JSON in the app config dir (on macOS:
//! `~/Library/Application Support/br.acervo.app/config.json`).

use std::fs;
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Clone, Serialize, Deserialize, PartialEq)]
pub struct AppConfig {
    /// Normalized origin of the Acervo server, e.g. `http://192.168.0.50:8765`.
    #[serde(default)]
    pub server_url: Option<String>,
}

/// Turns what the user typed into a bare origin (`scheme://host[:port]`).
///
/// Accepts `192.168.0.50:8765` (assumes http), `http://…`, `https://…`, with or
/// without a trailing slash. Rejects paths, queries, credentials and anything
/// that is not http/https, because the result is used both to navigate the
/// window and as the remote-capability URL pattern: it must be exactly one origin.
pub fn normalize_server_url(input: &str) -> Result<String, String> {
    let raw = input.trim();
    if raw.is_empty() {
        return Err("Digite o endereço do servidor.".into());
    }
    let with_scheme = if raw.contains("://") {
        raw.to_string()
    } else {
        format!("http://{raw}")
    };
    let url = reqwest::Url::parse(&with_scheme)
        .map_err(|_| format!("Endereço inválido: {raw}"))?;
    match url.scheme() {
        "http" | "https" => {}
        other => return Err(format!("Use http:// ou https:// (recebido {other}://).")),
    }
    let host = url
        .host_str()
        .filter(|h| !h.is_empty())
        .ok_or_else(|| "O endereço precisa ter um nome ou IP.".to_string())?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err("Não coloque usuário/senha no endereço.".into());
    }
    if url.path() != "/" && !url.path().is_empty() {
        return Err("Use só o endereço do servidor, sem caminho (ex.: http://192.168.0.50:8765).".into());
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err("O endereço não pode ter ? nem #.".into());
    }
    // Hostnames go into a URLPattern; only allow characters that are literal there.
    let host_ok = host
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_' | '[' | ']' | ':'));
    if !host_ok {
        return Err(format!("Nome de servidor inválido: {host}"));
    }
    let origin = match url.port() {
        Some(port) => format!("{}://{}:{}", url.scheme(), host, port),
        None => format!("{}://{}", url.scheme(), host),
    };
    Ok(origin.to_ascii_lowercase())
}

pub fn load(path: &Path) -> AppConfig {
    match fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_default(),
        Err(_) => AppConfig::default(),
    }
}

/// Atomic save: write a temp file, fsync, rename over the old one.
pub fn save(path: &Path, cfg: &AppConfig) -> Result<(), String> {
    let dir = path
        .parent()
        .ok_or_else(|| "Pasta de configuração inválida.".to_string())?;
    fs::create_dir_all(dir).map_err(|e| format!("Não consegui criar {}: {e}", dir.display()))?;
    let tmp = path.with_extension("json.tmp");
    let json = serde_json::to_vec_pretty(cfg).map_err(|e| e.to_string())?;
    let mut f = fs::File::create(&tmp)
        .map_err(|e| format!("Não consegui salvar a configuração: {e}"))?;
    f.write_all(&json)
        .and_then(|_| f.sync_all())
        .map_err(|e| format!("Não consegui salvar a configuração: {e}"))?;
    drop(f);
    fs::rename(&tmp, path).map_err(|e| format!("Não consegui salvar a configuração: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_common_inputs() {
        assert_eq!(normalize_server_url("192.168.0.50:8765").unwrap(), "http://192.168.0.50:8765");
        assert_eq!(normalize_server_url(" http://192.168.0.50:8765/ ").unwrap(), "http://192.168.0.50:8765");
        assert_eq!(
            normalize_server_url("https://Acervo.tailnet.ts.net").unwrap(),
            "https://acervo.tailnet.ts.net"
        );
        // Default port is dropped by the URL parser.
        assert_eq!(normalize_server_url("https://x.ts.net:443/").unwrap(), "https://x.ts.net");
    }

    #[test]
    fn rejects_bad_inputs() {
        for bad in [
            "",
            "ftp://x",
            "http://x/api",
            "http://u:p@x",
            "http://x/?a=1",
            "file:///etc",
        ] {
            assert!(normalize_server_url(bad).is_err(), "{bad} should be rejected");
        }
    }

    #[test]
    fn save_and_load_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sub/config.json");
        assert_eq!(load(&path), AppConfig::default());
        let cfg = AppConfig { server_url: Some("http://a:1".into()) };
        save(&path, &cfg).unwrap();
        assert_eq!(load(&path), cfg);
    }
}
