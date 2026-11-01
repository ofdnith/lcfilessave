//! Finding the Acervo on the home network, so nobody types an address.
//!
//! The Mac looks at its own Wi-Fi/Ethernet address (192.168.1.x), asks every
//! address of that /24 for `/api/health` on the Acervo port, and keeps the
//! answers that identify themselves as an Acervo. Android drops the multicast
//! that Bonjour needs unless an app holds a special lock (Termux doesn't), so a
//! direct sweep is the reliable way; 254 small requests take a few seconds.
//!
//! Safety: the sweep accepts any certificate, because the server's own one is not
//! trusted yet, but it never sends the login token and only reads the public
//! health report. The trusted address it learns (DuckDNS + Let's Encrypt) is then
//! checked with normal certificate verification before anything else happens,
//! and it must resolve to the very machine that answered.

use std::net::{IpAddr, Ipv4Addr, UdpSocket};
use std::time::Duration;

use futures_util::stream::{self, StreamExt};
use serde::Serialize;

pub const ACERVO_PORT: u16 = 8765;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Found {
    /// Where it answered, e.g. `https://192.168.1.104:8765`.
    pub url: String,
    pub version: Option<String>,
    /// Trusted addresses the server reported and that check out (see `addresses`).
    pub home: Option<String>,
    pub away: Option<String>,
}

/// The Mac's own private IPv4 address on the local network, if any. A UDP
/// "connect" sends nothing: it only asks the routing table.
pub fn local_ipv4() -> Option<Ipv4Addr> {
    for target in ["8.8.8.8:53", "1.1.1.1:53", "192.168.0.1:53"] {
        let Ok(sock) = UdpSocket::bind("0.0.0.0:0") else {
            continue;
        };
        if sock.connect(target).is_err() {
            continue;
        }
        if let Ok(addr) = sock.local_addr() {
            if let IpAddr::V4(ip) = addr.ip() {
                if ip.is_private() {
                    return Some(ip);
                }
            }
        }
    }
    None
}

/// Every other address of the /24 the Mac is on (192.168.1.1 … .254).
pub fn neighbours(me: Ipv4Addr) -> Vec<Ipv4Addr> {
    let [a, b, c, _] = me.octets();
    (1..=254u8)
        .map(|d| Ipv4Addr::new(a, b, c, d))
        .filter(|ip| *ip != me)
        .collect()
}

/// Client for the sweep only: short timeouts, any certificate, never a token.
fn sweep_client() -> reqwest::Client {
    reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .connect_timeout(Duration::from_millis(1200))
        .timeout(Duration::from_millis(2500))
        .user_agent(concat!("Acervo-Mac/", env!("CARGO_PKG_VERSION"), " (procura)"))
        .build()
        .expect("http client")
}

/// Is this health report from an Acervo? Newer servers say so; older ones are
/// recognized by the shape of the report.
pub fn looks_like_acervo(body: &serde_json::Value) -> bool {
    match body.get("service").and_then(|v| v.as_str()) {
        Some(s) => s == "acervo",
        None => body.get("catalog").is_some() && body.get("storage").is_some() && body.get("status").is_some(),
    }
}

/// A reported trusted address is only kept if it is a plain https origin
/// (checked by the same rules as a typed address).
fn reported(body: &serde_json::Value, role: &str) -> Option<String> {
    let url = body.get("addresses")?.get(role)?.as_str()?;
    let origin = crate::config::normalize_server_url(url).ok()?;
    origin.starts_with("https://").then_some(origin)
}

async fn probe(client: &reqwest::Client, ip: Ipv4Addr, port: u16) -> Option<(String, serde_json::Value)> {
    for scheme in ["https", "http"] {
        let base = format!("{scheme}://{ip}:{port}");
        match client.get(format!("{base}/api/health")).send().await {
            Ok(resp) => {
                let body: serde_json::Value = resp.json().await.ok()?;
                return looks_like_acervo(&body).then_some((base, body));
            }
            // Nobody at this address: no point trying http.
            Err(e) if e.is_timeout() => return None,
            // Refused, or a plain-http server that can't speak TLS: http is cheap to try.
            Err(_) => continue,
        }
    }
    None
}

/// Does `host:port` resolve to `ip`? Guards against a device on the network
/// advertising somebody else's name.
async fn resolves_to(origin: &str, ip: Ipv4Addr) -> bool {
    let Ok(url) = reqwest::Url::parse(origin) else {
        return false;
    };
    let (Some(host), Some(port)) = (url.host_str().map(str::to_string), url.port_or_known_default()) else {
        return false;
    };
    // A named binding (not a tail expression) so the borrow of `host` ends in time.
    #[allow(clippy::let_and_return)]
    let matches = match tokio::net::lookup_host((host.as_str(), port)).await {
        Ok(mut addrs) => addrs.any(|a| a.ip() == IpAddr::V4(ip)),
        Err(_) => false,
    };
    matches
}

/// Sweeps the local /24 and returns every Acervo found, closest address first.
pub async fn sweep(port: u16) -> Result<Vec<Found>, String> {
    let me = local_ipv4().ok_or_else(|| {
        "Este computador não parece estar numa rede local (Wi-Fi ou cabo). Conecte e tente de novo."
            .to_string()
    })?;
    let client = sweep_client();
    let hits: Vec<(Ipv4Addr, String, serde_json::Value)> = stream::iter(neighbours(me))
        .map(|ip| {
            let client = client.clone();
            async move { probe(&client, ip, port).await.map(|(url, body)| (ip, url, body)) }
        })
        .buffer_unordered(64)
        .filter_map(|x| async move { x })
        .collect()
        .await;

    let mut found = Vec::new();
    for (ip, url, body) in hits {
        // The home name must point at the machine that answered. The away name
        // points at its Tailscale address, which cannot be checked from here.
        let home = match reported(&body, "home") {
            Some(h) if resolves_to(&h, ip).await => Some(h),
            _ => None,
        };
        let away = if home.is_some() { reported(&body, "away") } else { None };
        found.push(Found {
            url,
            version: body.get("version").and_then(|v| v.as_str()).map(str::to_string),
            home,
            away,
        });
    }
    found.sort_by(|a, b| a.url.cmp(&b.url));
    Ok(found)
}

/// True when the request failed because of the server's certificate.
pub fn is_tls_error(e: &reqwest::Error) -> bool {
    let mut src: Option<&dyn std::error::Error> = Some(e);
    while let Some(err) = src {
        let text = err.to_string().to_ascii_lowercase();
        if text.contains("certificate") || text.contains("unknownissuer") || text.contains("tls") {
            return true;
        }
        src = err.source();
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn neighbours_cover_the_24_without_me() {
        let me = Ipv4Addr::new(192, 168, 1, 37);
        let n = neighbours(me);
        assert_eq!(n.len(), 253);
        assert_eq!(n[0], Ipv4Addr::new(192, 168, 1, 1));
        assert_eq!(*n.last().unwrap(), Ipv4Addr::new(192, 168, 1, 254));
        assert!(!n.contains(&me));
    }

    #[test]
    fn recognizes_an_acervo() {
        assert!(looks_like_acervo(&json!({"service": "acervo", "status": "ok"})));
        assert!(looks_like_acervo(&json!({"status": "ok", "catalog": {}, "storage": {}})));
        assert!(!looks_like_acervo(&json!({"service": "outra-coisa", "catalog": {}, "storage": {}, "status": "ok"})));
        assert!(!looks_like_acervo(&json!({"status": "ok"})));
    }

    #[test]
    fn only_clean_https_addresses_are_taken() {
        let body = json!({"addresses": {
            "home": "https://Fulano-Casa.duckdns.org:8765",
            "away": "http://fulano.duckdns.org:8765"
        }});
        assert_eq!(reported(&body, "home").as_deref(), Some("https://fulano-casa.duckdns.org:8765"));
        assert_eq!(reported(&body, "away"), None);
        let evil = json!({"addresses": {"home": "https://x.duckdns.org/caminho?roubar=1"}});
        assert_eq!(reported(&evil, "home"), None);
        assert_eq!(reported(&json!({}), "home"), None);
    }

    #[tokio::test]
    async fn name_must_point_at_the_machine_that_answered() {
        assert!(resolves_to("https://localhost:8765", Ipv4Addr::LOCALHOST).await);
        assert!(!resolves_to("https://localhost:8765", Ipv4Addr::new(192, 168, 1, 104)).await);
        assert!(!resolves_to("nao-e-url", Ipv4Addr::LOCALHOST).await);
    }
}
