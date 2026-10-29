fn main() {
    // Declaring the app commands generates `allow-<command>` permissions, which
    // capabilities reference (statically in capabilities/default.json for the
    // bundled page, and at runtime in lib.rs for the remote server origin).
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_server_url",
            "set_server_url",
            "test_server",
            "list_disks",
            "init_volume",
            "copy_to_volume",
            "write_bundle_file",
            "verify_volume_files",
            "open_on_volume",
            "pick_folder",
            "scan_folder",
            "hash_file",
            "upload_file",
        ]),
    ))
    .expect("failed to run tauri-build");
}
