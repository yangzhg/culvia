fn main() {
    println!("cargo:rerun-if-env-changed=CULVIA_DESKTOP_DEFAULT_RUNTIME_MODE");
    tauri_build::build()
}
