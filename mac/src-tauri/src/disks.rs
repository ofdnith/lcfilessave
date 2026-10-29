//! Plugged-in disks and the `.acervo/volume.json` that identifies an Acervo volume.
//!
//! `list_disks` is polled by the UI every ~1.5 s, so it only does a directory
//! listing, one `statfs` per mount and one small file read per disk.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::transfer::io_pt;

pub const ACERVO_DIR: &str = ".acervo";
pub const VOLUME_FILE: &str = "volume.json";
pub const THUMBS_DIR: &str = "miniaturas";
/// Format version written in `volume.json` (`"acervo": 1`).
pub const VOLUME_FORMAT: u32 = 1;
/// The only filesystem accepted for new volumes (spec: "Formato: exFAT").
pub const REQUIRED_FS: &str = "exfat";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VolumeJson {
    pub id: String,
    pub name: String,
    pub created_at: String,
    #[serde(default = "default_format")]
    pub acervo: u32,
}

fn default_format() -> u32 {
    VOLUME_FORMAT
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct VolumeRef {
    pub id: String,
    pub name: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Disk {
    pub mount_path: String,
    pub label: String,
    /// Lowercase filesystem type: "exfat", "apfs", "msdos", "hfs", "ntfs"…
    pub filesystem: String,
    pub total_bytes: u64,
    pub free_bytes: u64,
    pub read_only: bool,
    /// Present when `.acervo/volume.json` exists and is valid.
    pub volume: Option<VolumeRef>,
    /// Set when `.acervo/volume.json` exists but could not be read/parsed.
    pub volume_error: Option<String>,
}

pub fn volume_json_path(mount: &Path) -> PathBuf {
    mount.join(ACERVO_DIR).join(VOLUME_FILE)
}

/// Ok(None) = no volume.json (unknown disk). Err = file present but unusable.
pub fn read_volume_json(mount: &Path) -> Result<Option<VolumeJson>, String> {
    let path = volume_json_path(mount);
    let bytes = match fs::read(&path) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => {
            return Err(format!(
                "Não consegui ler {}: {}",
                path.display(),
                io_pt(&e)
            ))
        }
    };
    let v: VolumeJson = serde_json::from_slice(&bytes)
        .map_err(|_| "volume.json inválido (arquivo corrompido)".to_string())?;
    if v.id.trim().is_empty() {
        return Err("volume.json sem id".into());
    }
    Ok(Some(v))
}

/// Builds a `Disk` from already-collected filesystem facts.
pub fn build_disk(
    mount: &Path,
    filesystem: &str,
    total_bytes: u64,
    free_bytes: u64,
    read_only: bool,
) -> Disk {
    let label = mount
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| mount.display().to_string());
    let (volume, volume_error) = match read_volume_json(mount) {
        Ok(Some(v)) => (
            Some(VolumeRef {
                id: v.id,
                name: v.name,
                created_at: v.created_at,
            }),
            None,
        ),
        Ok(None) => (None, None),
        Err(e) => (None, Some(e)),
    };
    Disk {
        mount_path: mount.display().to_string(),
        label,
        filesystem: filesystem.to_ascii_lowercase(),
        total_bytes,
        free_bytes,
        read_only,
        volume,
        volume_error,
    }
}

fn valid_volume_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
}

/// Writes `.acervo/volume.json` (atomically) and creates `.acervo/miniaturas/`.
///
/// `filesystem` is what the OS reports for `mount`; anything but exFAT is refused.
/// Idempotent: calling it again with the same id just returns the existing file.
pub fn init_volume_at(
    mount: &Path,
    filesystem: &str,
    id: &str,
    name: &str,
    created_at: &str,
) -> Result<VolumeJson, String> {
    if !filesystem.eq_ignore_ascii_case(REQUIRED_FS) {
        return Err(format!(
            "Este disco está formatado como {}. O Acervo só usa HDs em exFAT \
             (formate pelo Utilitário de Disco escolhendo \"ExFAT\").",
            if filesystem.is_empty() {
                "desconhecido"
            } else {
                filesystem
            }
        ));
    }
    if !valid_volume_id(id) {
        return Err("Identificador de volume inválido.".into());
    }
    let name = name.trim();
    if name.is_empty() || name.len() > 64 || name.chars().any(|c| c.is_control()) {
        return Err("Nome de volume inválido.".into());
    }
    match read_volume_json(mount) {
        Ok(Some(existing)) if existing.id != id => {
            return Err(format!(
                "Este disco já pertence ao volume {} ({}). Não vou sobrescrever.",
                existing.name, existing.id
            ));
        }
        Ok(Some(existing)) => {
            fs::create_dir_all(mount.join(ACERVO_DIR).join(THUMBS_DIR))
                .map_err(|e| format!("Não consegui criar a pasta de miniaturas: {}", io_pt(&e)))?;
            return Ok(existing);
        }
        Ok(None) => {}
        Err(e) => return Err(format!("{e}. Não vou sobrescrever; verifique o disco.")),
    }

    let dir = mount.join(ACERVO_DIR);
    fs::create_dir_all(dir.join(THUMBS_DIR))
        .map_err(|e| format!("Não consegui criar {}: {}", dir.display(), io_pt(&e)))?;
    let vol = VolumeJson {
        id: id.to_string(),
        name: name.to_string(),
        created_at: created_at.to_string(),
        acervo: VOLUME_FORMAT,
    };
    let json = serde_json::to_vec_pretty(&vol).map_err(|e| e.to_string())?;
    write_file_atomic(&volume_json_path(mount), &json)?;
    Ok(vol)
}

/// tmp + fsync + rename + fsync(dir).
pub fn write_file_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let dir = path.parent().ok_or("caminho sem pasta")?;
    let tmp = path.with_file_name(format!(
        "{}.tmp",
        path.file_name()
            .map(|n| n.to_string_lossy())
            .unwrap_or_default()
    ));
    let err = |e: std::io::Error| format!("Não consegui gravar {}: {}", path.display(), io_pt(&e));
    let mut f = fs::File::create(&tmp).map_err(err)?;
    f.write_all(bytes).and_then(|_| f.sync_all()).map_err(err)?;
    drop(f);
    fs::rename(&tmp, path).map_err(err)?;
    crate::transfer::fsync_dir(dir);
    Ok(())
}

// ---------------------------------------------------------------------------
// Enumeration
// ---------------------------------------------------------------------------

/// Lists external disks, sorted by label.
pub fn list_disks() -> Vec<Disk> {
    let mut disks = platform::list();
    disks.sort_by_key(|d| d.label.to_lowercase());
    disks
}

/// Returns the plugged disk whose mount point is exactly `mount_path`.
/// Commands that write use this so a page can never make us write elsewhere.
pub fn find_disk(mount_path: &str) -> Option<Disk> {
    let wanted = Path::new(mount_path.trim_end_matches('/'));
    list_disks()
        .into_iter()
        .find(|d| Path::new(&d.mount_path) == wanted)
}

#[cfg(target_os = "macos")]
mod platform {
    //! macOS: every external disk is mounted under /Volumes. The boot volume
    //! appears there as a symlink to "/", which we skip.
    use super::{build_disk, Disk};
    use std::ffi::{CStr, CString};
    use std::os::unix::ffi::OsStrExt;
    use std::path::Path;

    pub fn list() -> Vec<Disk> {
        let Ok(entries) = std::fs::read_dir("/Volumes") else {
            return Vec::new();
        };
        let mut out = Vec::new();
        for entry in entries.flatten() {
            let name = entry.file_name();
            if name.as_bytes().starts_with(b".") {
                continue;
            }
            let path = entry.path();
            let Ok(meta) = std::fs::symlink_metadata(&path) else {
                continue;
            };
            if meta.file_type().is_symlink() || !meta.is_dir() {
                continue;
            }
            if let Some(d) = stat(&path) {
                out.push(d);
            }
        }
        out
    }

    fn stat(path: &Path) -> Option<Disk> {
        let c = CString::new(path.as_os_str().as_bytes()).ok()?;
        let mut st: libc::statfs = unsafe { std::mem::zeroed() };
        // SAFETY: c is a valid NUL-terminated path, st is a valid out pointer.
        if unsafe { libc::statfs(c.as_ptr(), &mut st) } != 0 {
            return None;
        }
        // A leftover empty folder in /Volumes is not a mount point: the
        // filesystem it lives on is mounted somewhere else.
        let mnt_on = unsafe { CStr::from_ptr(st.f_mntonname.as_ptr()) };
        if mnt_on.to_bytes() != path.as_os_str().as_bytes() {
            return None;
        }
        let flags = st.f_flags as i32;
        if flags & libc::MNT_DONTBROWSE != 0 {
            return None; // e.g. Time Machine local snapshots
        }
        let fstype = unsafe { CStr::from_ptr(st.f_fstypename.as_ptr()) }
            .to_string_lossy()
            .into_owned();
        let bsize = st.f_bsize as u64;
        Some(build_disk(
            path,
            &fstype,
            st.f_blocks.saturating_mul(bsize),
            st.f_bavail.saturating_mul(bsize),
            flags & libc::MNT_RDONLY != 0,
        ))
    }
}

#[cfg(not(target_os = "macos"))]
mod platform {
    //! Development fallback (Linux): removable disks under /media, /run/media
    //! and /mnt, read from /proc/self/mounts. Extra prefixes can be given in
    //! `ACERVO_DISK_ROOTS` (colon-separated) for manual testing.
    use super::{build_disk, Disk};
    use std::path::{Path, PathBuf};

    pub fn list() -> Vec<Disk> {
        let mut prefixes: Vec<PathBuf> = ["/media/", "/run/media/", "/mnt/"]
            .iter()
            .map(PathBuf::from)
            .collect();
        if let Ok(extra) = std::env::var("ACERVO_DISK_ROOTS") {
            prefixes.extend(
                extra
                    .split(':')
                    .filter(|s| !s.is_empty())
                    .map(PathBuf::from),
            );
        }
        let Ok(text) = std::fs::read_to_string("/proc/self/mounts") else {
            return Vec::new();
        };
        parse_mounts(&text)
            .into_iter()
            .filter(|m| {
                prefixes
                    .iter()
                    .any(|p| m.mount.starts_with(p) && m.mount != *p)
            })
            .filter_map(|m| {
                let (total, free) = statvfs(&m.mount)?;
                Some(build_disk(&m.mount, &m.fstype, total, free, m.read_only))
            })
            .collect()
    }

    #[derive(Debug, PartialEq)]
    pub struct MountLine {
        pub mount: PathBuf,
        pub fstype: String,
        pub read_only: bool,
    }

    /// `/proc/mounts` escapes spaces etc. as `\040`-style octal.
    fn unescape(s: &str) -> String {
        let b = s.as_bytes();
        let mut out = Vec::with_capacity(b.len());
        let mut i = 0;
        while i < b.len() {
            if b[i] == b'\\'
                && i + 3 < b.len()
                && b[i + 1..i + 4].iter().all(|c| (b'0'..=b'7').contains(c))
            {
                let v = (b[i + 1] - b'0') * 64 + (b[i + 2] - b'0') * 8 + (b[i + 3] - b'0');
                out.push(v);
                i += 4;
            } else {
                out.push(b[i]);
                i += 1;
            }
        }
        String::from_utf8_lossy(&out).into_owned()
    }

    pub fn parse_mounts(text: &str) -> Vec<MountLine> {
        text.lines()
            .filter_map(|line| {
                let mut f = line.split_whitespace();
                let _dev = f.next()?;
                let mount = unescape(f.next()?);
                let fstype = f.next()?.to_string();
                let opts = f.next().unwrap_or("");
                Some(MountLine {
                    mount: PathBuf::from(mount),
                    fstype,
                    read_only: opts.split(',').any(|o| o == "ro"),
                })
            })
            .collect()
    }

    fn statvfs(path: &Path) -> Option<(u64, u64)> {
        use std::os::unix::ffi::OsStrExt;
        let c = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
        let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
        // SAFETY: valid C string and out pointer.
        if unsafe { libc::statvfs(c.as_ptr(), &mut st) } != 0 {
            return None;
        }
        let frsize = st.f_frsize as u64;
        Some((
            (st.f_blocks as u64).saturating_mul(frsize),
            (st.f_bavail as u64).saturating_mul(frsize),
        ))
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn parses_proc_mounts() {
            let text = "/dev/sda1 / ext4 rw,relatime 0 0\n\
                        /dev/sdb1 /media/me/MEU\\040HD exfat rw,nosuid 0 0\n\
                        /dev/sdc1 /mnt/x vfat ro,nosuid 0 0\n";
            let m = parse_mounts(text);
            assert_eq!(m.len(), 3);
            assert_eq!(m[1].mount, PathBuf::from("/media/me/MEU HD"));
            assert_eq!(m[1].fstype, "exfat");
            assert!(!m[1].read_only);
            assert!(m[2].read_only);
        }
    }
}

/// Free bytes available to us on the filesystem holding `path`.
pub fn free_bytes(path: &Path) -> Option<u64> {
    use std::os::unix::ffi::OsStrExt;
    let c = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: valid C string and out pointer.
    if unsafe { libc::statvfs(c.as_ptr(), &mut st) } != 0 {
        return None;
    }
    #[allow(clippy::unnecessary_cast)]
    Some((st.f_bavail as u64).saturating_mul(st.f_frsize as u64))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_disk_has_no_volume() {
        let dir = tempfile::tempdir().unwrap();
        let d = build_disk(dir.path(), "ExFAT", 100, 50, false);
        assert_eq!(d.filesystem, "exfat");
        assert!(d.volume.is_none());
        assert!(d.volume_error.is_none());
    }

    #[test]
    fn init_then_recognized() {
        let dir = tempfile::tempdir().unwrap();
        let v = init_volume_at(
            dir.path(),
            "exfat",
            "a1b2-c3",
            "VOLUME-001",
            "2026-10-29T10:00:00Z",
        )
        .unwrap();
        assert_eq!(v.acervo, 1);
        assert!(dir.path().join(".acervo/miniaturas").is_dir());
        let raw: serde_json::Value =
            serde_json::from_slice(&fs::read(volume_json_path(dir.path())).unwrap()).unwrap();
        assert_eq!(raw["id"], "a1b2-c3");
        assert_eq!(raw["name"], "VOLUME-001");
        assert_eq!(raw["acervo"], 1);
        let d = build_disk(dir.path(), "exfat", 0, 0, false);
        assert_eq!(d.volume.unwrap().name, "VOLUME-001");
        // Same id again: idempotent.
        assert_eq!(
            init_volume_at(dir.path(), "exfat", "a1b2-c3", "VOLUME-001", "x").unwrap(),
            v
        );
    }

    #[test]
    fn init_refuses_non_exfat() {
        let dir = tempfile::tempdir().unwrap();
        let err = init_volume_at(dir.path(), "apfs", "id1", "VOLUME-001", "t").unwrap_err();
        assert!(err.contains("exFAT"), "{err}");
        assert!(!volume_json_path(dir.path()).exists());
    }

    #[test]
    fn init_refuses_different_id() {
        let dir = tempfile::tempdir().unwrap();
        init_volume_at(dir.path(), "exfat", "id1", "VOLUME-001", "t").unwrap();
        let err = init_volume_at(dir.path(), "exfat", "id2", "VOLUME-002", "t").unwrap_err();
        assert!(err.contains("VOLUME-001"), "{err}");
        assert_eq!(read_volume_json(dir.path()).unwrap().unwrap().id, "id1");
    }

    #[test]
    fn init_refuses_over_corrupt_volume_json() {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(dir.path().join(".acervo")).unwrap();
        fs::write(volume_json_path(dir.path()), b"{not json").unwrap();
        assert!(init_volume_at(dir.path(), "exfat", "id1", "V", "t").is_err());
        let d = build_disk(dir.path(), "exfat", 0, 0, false);
        assert!(d.volume.is_none());
        assert!(d.volume_error.is_some());
    }

    #[test]
    fn init_rejects_bad_id() {
        let dir = tempfile::tempdir().unwrap();
        assert!(init_volume_at(dir.path(), "exfat", "../x", "V", "t").is_err());
    }
}
