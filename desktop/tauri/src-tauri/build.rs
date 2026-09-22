fn main() {
    println!("cargo:rerun-if-env-changed=CULVIA_DESKTOP_DEFAULT_RUNTIME_MODE");
    let target = std::env::var("TARGET").expect("Cargo must provide the desktop build target");
    println!("cargo:rustc-env=CULVIA_DESKTOP_BUILD_TARGET={target}");
    tauri_build::build()
}
