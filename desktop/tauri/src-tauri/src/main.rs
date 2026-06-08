#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    env,
    error::Error,
    fs,
    io::{BufRead, BufReader, Read, Write},
    net::{TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::mpsc,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const BACKEND_STEM: &str = "culvia-server";
const BACKEND_RUNTIME_ROOT: &str = "runtime/backend";
const MAIN_WINDOW_LABEL: &str = "main";
const DEV_BACKEND_URL: &str = "http://127.0.0.1:8501";
const HEALTH_PATH: &str = "/health";
const RUNTIME_MODE_ENV: &str = "CULVIA_DESKTOP_RUNTIME_MODE";
const DEFAULT_RUNTIME_MODE: Option<&str> = option_env!("CULVIA_DESKTOP_DEFAULT_RUNTIME_MODE");
const RUNTIME_HOME_ENV: &str = "CULVIA_RUNTIME_HOME";
const RUNTIME_CONFIG_ENV: &str = "CULVIA_RUNTIME_CONFIG";
const RUNTIME_VENV_ENV: &str = "CULVIA_RUNTIME_VENV";
const RUNTIME_PYTHON_ENV: &str = "CULVIA_RUNTIME_PYTHON";
const RUNTIME_PACKAGE_ENV: &str = "CULVIA_RUNTIME_PACKAGE";
const RUNTIME_SKIP_INSTALL_ENV: &str = "CULVIA_RUNTIME_SKIP_INSTALL";
const SMOKE_ENV: &str = "CULVIA_DESKTOP_SMOKE";
const SMOKE_EXIT_AFTER_MS_ENV: &str = "CULVIA_DESKTOP_SMOKE_EXIT_AFTER_MS";
const READY_TIMEOUT_SECS_ENV: &str = "CULVIA_DESKTOP_READY_TIMEOUT_SECS";
const BACKEND_HEALTH_TIMEOUT_SECS_ENV: &str = "CULVIA_DESKTOP_BACKEND_HEALTH_TIMEOUT_SECS";
const HEALTH_TIMEOUT_SECS_ENV: &str = "CULVIA_DESKTOP_HEALTH_TIMEOUT_SECS";
const FRONTEND_READY_TIMEOUT_SECS_ENV: &str = "CULVIA_DESKTOP_FRONTEND_READY_TIMEOUT_SECS";
const FRONTEND_READY_EVENT: &str = "frontendReady";
const SPLASH_WINDOW_LABEL: &str = "splash";
const DEFAULT_READY_TIMEOUT: Duration = Duration::from_secs(120);
const DEFAULT_BACKEND_HEALTH_TIMEOUT: Duration = Duration::from_secs(120);
const DEFAULT_HEALTH_TIMEOUT: Duration = Duration::from_secs(35);
const DEFAULT_FRONTEND_READY_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_INTERVAL: Duration = Duration::from_millis(250);
const SPLASH_STEPS: u32 = 4;
const SPLASH_HTML: &str = include_str!("../assets/splash.html");

fn splash_data_url() -> DesktopResult<Url> {
    const PREFIX: &str = "data:text/html;charset=utf-8,";
    let encoded = encode_uri_component(SPLASH_HTML);
    Url::parse(&(PREFIX.to_string() + &encoded)).map_err(|error| error.into())
}

fn encode_uri_component(value: &str) -> String {
    let mut encoded = String::new();
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            encoded.push(byte as char);
        } else {
            encoded.push('%');
            encoded.push_str(&format!("{:02X}", byte));
        }
    }
    encoded
}

const FRONTEND_READY_SCRIPT: &str = r##"
(() => {
  try {
    const selectors = [
      "#mainScoreBtn",
      "#viewerView",
      "#modelOptions",
      ".view-tab[data-view='viewer']",
      ".view-tab[data-view='gallery']",
      ".view-tab[data-view='distribution']",
      ".view-tab[data-view='export']"
    ];
    const missing = selectors.filter((selector) => !document.querySelector(selector));
    const viewTabs = document.querySelectorAll(".view-tab").length;
    const language = window.CulviaI18n?.language?.() || document.documentElement.lang || "";
    return {
      ready: document.readyState !== "loading" && Boolean(window.CulviaI18n) && missing.length === 0 && viewTabs >= 4,
      href: location.href,
      language,
      missing,
      title: document.title || "",
      viewTabs
    };
  } catch (error) {
    return { ready: false, error: String(error) };
  }
})()
"##;

type DesktopResult<T> = Result<T, Box<dyn Error>>;
type SharedBackend = Arc<Mutex<Option<Child>>>;

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct ReadyEvent {
    event: String,
    base_url: String,
    health_url: String,
}

#[derive(Debug)]
struct BackendStartup {
    base_url: String,
    child: Option<Child>,
    runtime_mode: &'static str,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct RuntimeConfigFile {
    mode: Option<String>,
    python: Option<String>,
    venv: Option<String>,
    package: Option<String>,
    auto_install: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RuntimeMode {
    Development,
    Full,
    Lite,
    Auto,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CommandSpec {
    program: String,
    args: Vec<String>,
}

impl CommandSpec {
    fn new(program: impl Into<String>, args: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Self {
            program: program.into(),
            args: args.into_iter().map(Into::into).collect(),
        }
    }

    fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command.args(&self.args);
        command
    }

    fn display(&self) -> String {
        std::iter::once(self.program.as_str())
            .chain(self.args.iter().map(String::as_str))
            .collect::<Vec<_>>()
            .join(" ")
    }
}

fn runtime_mode_from_value(
    value: Option<&str>,
    force_backend: bool,
    debug_build: bool,
) -> RuntimeMode {
    match value.map(str::trim).map(str::to_ascii_lowercase).as_deref() {
        Some("dev" | "development") => RuntimeMode::Development,
        Some("full" | "bundled") => RuntimeMode::Full,
        Some("lite" | "external") => RuntimeMode::Lite,
        Some("auto") => RuntimeMode::Auto,
        _ if force_backend => RuntimeMode::Full,
        _ if debug_build => RuntimeMode::Development,
        _ => RuntimeMode::Full,
    }
}

fn runtime_mode_from_config(config: &RuntimeConfigFile) -> RuntimeMode {
    runtime_mode_from_value(
        env::var(RUNTIME_MODE_ENV)
            .ok()
            .as_deref()
            .or(config.mode.as_deref())
            .or(DEFAULT_RUNTIME_MODE),
        env::var("CULVIA_DESKTOP_FORCE_BACKEND").ok().as_deref() == Some("1"),
        cfg!(debug_assertions),
    )
}

fn smoke_enabled() -> bool {
    env::var(SMOKE_ENV).ok().as_deref() == Some("1")
}

fn smoke_exit_delay(value: Option<&str>) -> Option<Duration> {
    let millis = value?.trim().parse::<u64>().ok()?;
    (millis > 0).then_some(Duration::from_millis(millis))
}

fn smoke_exit_delay_from_env() -> Option<Duration> {
    smoke_exit_delay(env::var(SMOKE_EXIT_AFTER_MS_ENV).ok().as_deref())
}

fn timeout_secs(value: Option<&str>, default: Duration) -> Duration {
    let Some(value) = value else {
        return default;
    };
    let Ok(seconds) = value.trim().parse::<u64>() else {
        return default;
    };
    if seconds == 0 {
        default
    } else {
        Duration::from_secs(seconds)
    }
}

fn ready_timeout_from_env() -> Duration {
    timeout_secs(
        env::var(READY_TIMEOUT_SECS_ENV).ok().as_deref(),
        DEFAULT_READY_TIMEOUT,
    )
}

fn health_timeout_from_env() -> Duration {
    timeout_secs(
        env::var(HEALTH_TIMEOUT_SECS_ENV).ok().as_deref(),
        DEFAULT_HEALTH_TIMEOUT,
    )
}

fn frontend_ready_timeout_from_env() -> Duration {
    timeout_secs(
        env::var(FRONTEND_READY_TIMEOUT_SECS_ENV).ok().as_deref(),
        DEFAULT_FRONTEND_READY_TIMEOUT,
    )
}

fn backend_health_timeout_from_env() -> Duration {
    timeout_secs(
        env::var(BACKEND_HEALTH_TIMEOUT_SECS_ENV).ok().as_deref(),
        DEFAULT_BACKEND_HEALTH_TIMEOUT,
    )
}

fn smoke_event_payload(event: &str, mut payload: Value) -> Value {
    let Value::Object(ref mut fields) = payload else {
        return json!({"event": event});
    };
    fields.insert("event".to_string(), Value::String(event.to_string()));
    payload
}

fn emit_smoke_event(event: &str, payload: Value) {
    if !smoke_enabled() {
        return;
    }
    println!("{}", smoke_event_payload(event, payload));
    let _ = std::io::stdout().flush();
}

fn update_splash_status(splash: Option<&WebviewWindow>, status: &str, step: u32, total: u32) {
    let Some(splash) = splash else {
        return;
    };
    let payload = json!({"status": status, "step": step, "total": total});
    update_splash_payload(splash, payload);
}

fn update_splash_payload(splash: &WebviewWindow, payload: Value) {
    let _ = splash.eval(&format!(
        "window.CulviaSplash && window.CulviaSplash.setStatus({payload});"
    ));
}

fn update_splash_status_from_handle(
    app_handle: &tauri::AppHandle,
    status: &str,
    step: u32,
    total: u32,
) {
    if let Some(window) = app_handle.get_webview_window(SPLASH_WINDOW_LABEL) {
        update_splash_status(Some(&window), status, step, total);
    }
}

fn update_splash_error_from_handle(app_handle: &tauri::AppHandle, status: &str) {
    if let Some(window) = app_handle.get_webview_window(SPLASH_WINDOW_LABEL) {
        update_splash_payload(
            &window,
            json!({
                "status": status,
                "hint": "Restart the app or check the logs",
                "step": SPLASH_STEPS,
                "total": SPLASH_STEPS,
                "error": true
            }),
        );
    }
}

fn create_splash_window(app: &tauri::App) -> DesktopResult<WebviewWindow> {
    let url = splash_data_url()?;
    let window = WebviewWindowBuilder::new(app, SPLASH_WINDOW_LABEL, WebviewUrl::External(url))
        .title("Culvia")
        .inner_size(760.0, 480.0)
        .center()
        .decorations(false)
        .shadow(true)
        .resizable(false)
        .maximizable(false)
        .build()?;
    update_splash_status(Some(&window), "Preparing startup", 0, SPLASH_STEPS);
    Ok(window)
}

fn parse_frontend_ready_result(result: &str) -> Option<Value> {
    let payload = serde_json::from_str::<Value>(result.trim()).ok()?;
    (payload.get("ready").and_then(Value::as_bool) == Some(true)).then_some(payload)
}

fn frontend_ready_payload(result: Value, base_url: &str) -> Value {
    let mut payload = match result {
        Value::Object(fields) => fields,
        _ => serde_json::Map::new(),
    };
    payload.insert("baseUrl".to_string(), Value::String(base_url.to_string()));
    Value::Object(payload)
}

fn schedule_exit_after_delay(handle: tauri::AppHandle, delay: Duration) {
    thread::spawn(move || {
        thread::sleep(delay);
        handle.exit(0);
    });
}

fn maybe_schedule_smoke_exit(handle: &tauri::AppHandle) {
    if let Some(delay) = smoke_exit_delay_from_env() {
        schedule_exit_after_delay(handle.clone(), delay);
    }
}

fn show_main_and_close_splash(window: &WebviewWindow, app_handle: &tauri::AppHandle, status: &str) {
    update_splash_status_from_handle(app_handle, status, SPLASH_STEPS, SPLASH_STEPS);
    let _ = window.show();
    let _ = window.set_focus();
    let _ = app_handle
        .get_webview_window(SPLASH_WINDOW_LABEL)
        .and_then(|window| window.close().ok());
}

fn schedule_frontend_ready_probe(
    window: WebviewWindow,
    app_handle: tauri::AppHandle,
    base_url: String,
) {
    thread::spawn(move || {
        let started = Instant::now();
        let timeout = frontend_ready_timeout_from_env();
        update_splash_status_from_handle(
            &app_handle,
            "Loading interface",
            SPLASH_STEPS,
            SPLASH_STEPS,
        );
        while started.elapsed() <= timeout {
            let (sender, receiver) = mpsc::channel::<String>();
            if window
                .eval_with_callback(FRONTEND_READY_SCRIPT, move |result| {
                    let _ = sender.send(result);
                })
                .is_ok()
            {
                if let Ok(result) = receiver.recv_timeout(Duration::from_millis(900)) {
                    if let Some(payload) = parse_frontend_ready_result(&result) {
                        emit_smoke_event(
                            FRONTEND_READY_EVENT,
                            frontend_ready_payload(payload, &base_url),
                        );
                        show_main_and_close_splash(&window, &app_handle, "Interface ready");
                        maybe_schedule_smoke_exit(&app_handle);
                        return;
                    }
                }
            }
            thread::sleep(HEALTH_INTERVAL);
        }
        emit_smoke_event(
            "frontendReadyTimeout",
            json!({"baseUrl": base_url, "timeoutSeconds": timeout.as_secs()}),
        );
        show_main_and_close_splash(&window, &app_handle, "Interface opened after a slow load");
        maybe_schedule_smoke_exit(&app_handle);
    });
}

fn current_target_triple() -> &'static str {
    option_env!("TAURI_ENV_TARGET_TRIPLE").unwrap_or("unknown-target")
}

fn backend_binary_name(target: &str) -> String {
    let suffix = if target.contains("windows") || cfg!(windows) {
        ".exe"
    } else {
        ""
    };
    format!("{BACKEND_STEM}{suffix}")
}

fn backend_runtime_executable(root: PathBuf, target: &str) -> PathBuf {
    root.join(BACKEND_RUNTIME_ROOT)
        .join(target)
        .join(BACKEND_STEM)
        .join(backend_binary_name(target))
}

fn backend_executable_from_path(path: PathBuf, target: &str) -> Vec<PathBuf> {
    vec![
        path.clone(),
        path.join(backend_binary_name(target)),
        path.join(BACKEND_STEM).join(backend_binary_name(target)),
        backend_runtime_executable(path, target),
    ]
}

fn parse_ready_event(line: &str) -> Option<ReadyEvent> {
    let event = serde_json::from_str::<ReadyEvent>(line.trim()).ok()?;
    (event.event == "ready" && ready_event_urls_are_local(&event)).then_some(event)
}

fn local_http_socket(url: &str) -> DesktopResult<(String, u16, String)> {
    let parsed = Url::parse(url)?;
    if parsed.scheme() != "http" {
        return Err(format!("health check URL must use http: {url}").into());
    }
    let host = parsed
        .host_str()
        .filter(|host| matches!(*host, "127.0.0.1" | "localhost"))
        .ok_or_else(|| format!("health check URL must target localhost: {url}"))?;
    let port = parsed
        .port()
        .ok_or_else(|| format!("health check URL must include a port: {url}"))?;
    Ok((host.to_string(), port, parsed.path().to_string()))
}

fn ready_event_urls_are_local(event: &ReadyEvent) -> bool {
    let Ok((base_host, base_port, _)) = local_http_socket(&event.base_url) else {
        return false;
    };
    let Ok((health_host, health_port, health_path)) = local_http_socket(&event.health_url) else {
        return false;
    };
    base_host == health_host && base_port == health_port && health_path == HEALTH_PATH
}

fn health_check(url: &str) -> bool {
    let Ok((host, port, path)) = local_http_socket(url) else {
        return false;
    };
    let Ok(mut addresses) = (host.as_str(), port).to_socket_addrs() else {
        return false;
    };
    let Some(address) = addresses.next() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(800)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let request =
        format!("GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = [0_u8; 96];
    match stream.read(&mut response) {
        Ok(size) => std::str::from_utf8(&response[..size])
            .map(|text| text.starts_with("HTTP/1.1 200") || text.starts_with("HTTP/1.0 200"))
            .unwrap_or(false),
        Err(_) => false,
    }
}

fn wait_until_healthy(url: &str, timeout: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() <= timeout {
        if health_check(url) {
            return true;
        }
        std::thread::sleep(HEALTH_INTERVAL);
    }
    false
}

fn candidate_backend_paths_from_dirs(
    target: &str,
    resource_dir: Option<PathBuf>,
    current_exe: Option<PathBuf>,
    current_dir: Option<PathBuf>,
) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Some(path) = env::var_os("CULVIA_BACKEND_PATH").map(PathBuf::from) {
        paths.extend(backend_executable_from_path(path, target));
    }
    if let Some(exe_dir) = current_exe.and_then(|path| path.parent().map(PathBuf::from)) {
        paths.push(backend_runtime_executable(exe_dir.clone(), target));
        if let Some(package_root) = exe_dir.parent().map(PathBuf::from) {
            paths.push(backend_runtime_executable(package_root, target));
        }
    }
    if let Some(resource_dir) = resource_dir {
        paths.push(backend_runtime_executable(resource_dir, target));
    }
    if let Some(current_dir) = current_dir {
        paths.push(backend_runtime_executable(
            current_dir.join("src-tauri"),
            target,
        ));
        paths.push(backend_runtime_executable(
            current_dir.join("desktop").join("tauri").join("src-tauri"),
            target,
        ));
    }
    paths
}

fn candidate_backend_paths_by_resource(resource_dir: Option<PathBuf>) -> Vec<PathBuf> {
    candidate_backend_paths_from_dirs(
        current_target_triple(),
        resource_dir,
        env::current_exe().ok(),
        env::current_dir().ok(),
    )
}

fn backend_path_by_resource(resource_dir: Option<PathBuf>) -> DesktopResult<PathBuf> {
    let candidates = candidate_backend_paths_by_resource(resource_dir);
    candidates
        .iter()
        .find(|path| path.exists())
        .cloned()
        .ok_or_else(|| {
            let searched = candidates
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(", ");
            format!("Culvia local service was not found. Searched: {searched}").into()
        })
}

fn home_dir() -> DesktopResult<PathBuf> {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .ok_or_else(|| "Could not resolve the current user's home directory.".into())
}

fn lite_runtime_home() -> DesktopResult<PathBuf> {
    if let Some(path) = env::var_os(RUNTIME_HOME_ENV).map(PathBuf::from) {
        return Ok(path);
    }
    let home = home_dir()?;
    if cfg!(target_os = "macos") {
        return Ok(home
            .join("Library")
            .join("Application Support")
            .join("Culvia")
            .join("runtime"));
    }
    if cfg!(windows) {
        let base = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join("AppData").join("Local"));
        return Ok(base.join("Culvia").join("runtime"));
    }
    let base = env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".local").join("share"));
    Ok(base.join("culvia").join("runtime"))
}

fn runtime_config_path() -> DesktopResult<PathBuf> {
    if let Some(path) = env::var_os(RUNTIME_CONFIG_ENV).map(PathBuf::from) {
        return Ok(path);
    }
    Ok(lite_runtime_home()?.join("runtime.json"))
}

fn load_runtime_config() -> RuntimeConfigFile {
    let Ok(path) = runtime_config_path() else {
        return RuntimeConfigFile::default();
    };
    let Ok(text) = fs::read_to_string(path) else {
        return RuntimeConfigFile::default();
    };
    serde_json::from_str::<RuntimeConfigFile>(&text).unwrap_or_default()
}

fn lite_venv_path(config: &RuntimeConfigFile) -> DesktopResult<PathBuf> {
    if let Some(path) = env::var_os(RUNTIME_VENV_ENV).map(PathBuf::from) {
        return Ok(path);
    }
    if let Some(path) = config
        .venv
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        return Ok(PathBuf::from(path));
    }
    Ok(lite_runtime_home()?.join("venv"))
}

fn lite_venv_python(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn python_command_candidates(config: &RuntimeConfigFile) -> Vec<CommandSpec> {
    let mut candidates = Vec::new();
    if let Some(path) = env::var_os(RUNTIME_PYTHON_ENV) {
        candidates.push(CommandSpec::new(
            path.to_string_lossy().to_string(),
            Vec::<&str>::new(),
        ));
    }
    if let Some(path) = config
        .python
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        candidates.push(CommandSpec::new(path.to_string(), Vec::<&str>::new()));
    }
    if cfg!(windows) {
        candidates.push(CommandSpec::new("py", ["-3.12"]));
        candidates.push(CommandSpec::new("py", ["-3.11"]));
        candidates.push(CommandSpec::new("python", Vec::<&str>::new()));
    } else {
        candidates.push(CommandSpec::new("python3.12", Vec::<&str>::new()));
        candidates.push(CommandSpec::new("python3.11", Vec::<&str>::new()));
        candidates.push(CommandSpec::new("python3", Vec::<&str>::new()));
        candidates.push(CommandSpec::new("python", Vec::<&str>::new()));
    }
    let mut deduped = Vec::new();
    for candidate in candidates {
        if !deduped
            .iter()
            .any(|existing: &CommandSpec| existing == &candidate)
        {
            deduped.push(candidate);
        }
    }
    deduped
}

fn python_is_supported(spec: &CommandSpec) -> bool {
    let mut command = spec.command();
    command
        .arg("-c")
        .arg("import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn find_lite_python(config: &RuntimeConfigFile) -> DesktopResult<CommandSpec> {
    for candidate in python_command_candidates(config) {
        if python_is_supported(&candidate) {
            return Ok(candidate);
        }
    }
    let searched = python_command_candidates(config)
        .iter()
        .map(CommandSpec::display)
        .collect::<Vec<_>>()
        .join(", ");
    Err(format!("Python 3.11+ was not found. Searched: {searched}").into())
}

fn run_status_command(mut command: Command, label: &str) -> DesktopResult<()> {
    let status = command.status()?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("{label} failed: {status}").into())
    }
}

fn create_lite_venv(base_python: &CommandSpec, venv: &Path) -> DesktopResult<()> {
    if let Some(parent) = venv.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut command = base_python.command();
    command.arg("-m").arg("venv").arg(venv);
    run_status_command(command, "Create Python runtime")
}

fn lite_package_install_args(config: &RuntimeConfigFile) -> Vec<String> {
    let package = env::var(RUNTIME_PACKAGE_ENV)
        .ok()
        .or_else(|| config.package.clone())
        .unwrap_or_else(|| format!("culvia[desktop-runtime]=={}", env!("CARGO_PKG_VERSION")));
    package.split_whitespace().map(str::to_string).collect()
}

fn lite_modules_missing(python: &Path) -> DesktopResult<Vec<String>> {
    let probe = concat!(
        "import importlib.util; ",
        "culvia_spec = importlib.util.find_spec('culvia'); ",
        "mods = ['culvia'] if culvia_spec is None else __import__('culvia.runtime_dependencies', fromlist=['REQUIRED_RUNTIME_MODULES']).REQUIRED_RUNTIME_MODULES; ",
        "missing = [item for item in mods if importlib.util.find_spec(item) is None]; ",
        "print('\\n'.join(missing)); ",
        "raise SystemExit(1 if missing else 0)"
    );
    let output = Command::new(python).arg("-c").arg(probe).output()?;
    let missing = String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_string)
        .collect::<Vec<_>>();
    if output.status.success() || !missing.is_empty() {
        Ok(missing)
    } else {
        let error = String::from_utf8_lossy(&output.stderr).trim().to_string();
        Err(format!("Lite dependency check failed: {error}").into())
    }
}

fn install_lite_dependencies(python: &Path, config: &RuntimeConfigFile) -> DesktopResult<()> {
    let mut upgrade = Command::new(python);
    upgrade
        .args(["-m", "pip", "install", "-U", "pip"])
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    run_status_command(upgrade, "Upgrade pip")?;

    let mut install = Command::new(python);
    install
        .args(["-m", "pip", "install"])
        .args(lite_package_install_args(config))
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    run_status_command(install, "Install Culvia runtime")
}

fn ensure_lite_runtime(
    config: &RuntimeConfigFile,
    set_status: &impl Fn(&str, u32, u32),
) -> DesktopResult<PathBuf> {
    set_status("Checking Python", 1, SPLASH_STEPS);
    let venv = lite_venv_path(config)?;
    let python = lite_venv_python(&venv);
    if !python.exists() {
        let base_python = find_lite_python(config)?;
        set_status("Creating runtime", 1, SPLASH_STEPS);
        create_lite_venv(&base_python, &venv)?;
    }

    set_status("Checking dependencies", 2, SPLASH_STEPS);
    let missing = lite_modules_missing(&python)?;
    if !missing.is_empty() {
        if env::var(RUNTIME_SKIP_INSTALL_ENV).ok().as_deref() == Some("1")
            || config.auto_install == Some(false)
        {
            return Err(format!(
                "Lite runtime is missing dependencies: {}",
                missing.join(", ")
            )
            .into());
        }
        set_status("Installing dependencies", 2, SPLASH_STEPS);
        install_lite_dependencies(&python, config)?;
        let remaining = lite_modules_missing(&python)?;
        if !remaining.is_empty() {
            return Err(format!(
                "Lite runtime dependencies are still incomplete: {}",
                remaining.join(", ")
            )
            .into());
        }
    }
    Ok(python)
}

fn read_ready_event(child: &mut Child, timeout: Duration) -> DesktopResult<ReadyEvent> {
    let stdout = child
        .stdout
        .take()
        .ok_or("Culvia local service output was not captured")?;
    let (sender, receiver) = mpsc::channel::<Result<ReadyEvent, String>>();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut ready_sent = false;
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    if !ready_sent {
                        if let Some(event) = parse_ready_event(&text) {
                            let _ = sender.send(Ok(event));
                            ready_sent = true;
                        }
                    }
                }
                Err(error) => {
                    if !ready_sent {
                        let _ = sender
                            .send(Err(format!("Failed to read local service output: {error}")));
                    }
                    return;
                }
            }
        }
        if !ready_sent {
            let _ = sender.send(Err(
                "The local service closed output before it became ready".to_string(),
            ));
        }
    });

    let started = Instant::now();
    while started.elapsed() <= timeout {
        match receiver.recv_timeout(HEALTH_INTERVAL) {
            Ok(Ok(event)) => return Ok(event),
            Ok(Err(message)) => return Err(message.into()),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if let Some(status) = child.try_wait()? {
                    return Err(
                        format!("Culvia local service exited before readiness: {status}").into(),
                    );
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err("The local service readiness listener stopped".into());
            }
        }
    }
    Err("Timed out waiting for the Culvia local service".into())
}

fn start_production_backend(
    resource_dir: Option<PathBuf>,
    set_status: &impl Fn(&str, u32, u32),
) -> DesktopResult<BackendStartup> {
    set_status("Locating service", 1, SPLASH_STEPS);
    let path = backend_path_by_resource(resource_dir)?;
    set_status("Starting service", 2, SPLASH_STEPS);
    let backend_health_timeout = backend_health_timeout_from_env().as_secs().to_string();
    let mut child = Command::new(path)
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            "auto",
            "--no-open",
            "--print-json",
        ])
        .arg("--health-timeout")
        .arg(backend_health_timeout)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    set_status("Waiting for service", 3, SPLASH_STEPS);
    let ready = read_ready_event(&mut child, ready_timeout_from_env())?;
    set_status("Checking service", 4, SPLASH_STEPS);
    if !wait_until_healthy(&ready.health_url, health_timeout_from_env()) {
        let _ = child.kill();
        return Err(format!(
            "Culvia local service health check failed: {}",
            ready.health_url
        )
        .into());
    }
    Ok(BackendStartup {
        base_url: ready.base_url,
        child: Some(child),
        runtime_mode: "full",
    })
}

fn start_lite_backend(
    config: &RuntimeConfigFile,
    set_status: &impl Fn(&str, u32, u32),
) -> DesktopResult<BackendStartup> {
    let python = ensure_lite_runtime(config, set_status)?;
    set_status("Starting service", 3, SPLASH_STEPS);
    let backend_health_timeout = backend_health_timeout_from_env().as_secs().to_string();
    let mut child = Command::new(python)
        .args([
            "-m",
            "culvia.server",
            "--host",
            "127.0.0.1",
            "--port",
            "auto",
            "--no-open",
            "--print-json",
        ])
        .arg("--health-timeout")
        .arg(backend_health_timeout)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    set_status("Waiting for service", 3, SPLASH_STEPS);
    let ready = read_ready_event(&mut child, ready_timeout_from_env())?;
    set_status("Checking service", 4, SPLASH_STEPS);
    if !wait_until_healthy(&ready.health_url, health_timeout_from_env()) {
        let _ = child.kill();
        return Err(format!(
            "Culvia local service health check failed: {}",
            ready.health_url
        )
        .into());
    }
    Ok(BackendStartup {
        base_url: ready.base_url,
        child: Some(child),
        runtime_mode: "lite",
    })
}

fn start_development_backend(
    set_status: &impl Fn(&str, u32, u32),
) -> DesktopResult<BackendStartup> {
    set_status("Checking dev service", 1, SPLASH_STEPS);
    let health_url = format!("{DEV_BACKEND_URL}{HEALTH_PATH}");
    if !wait_until_healthy(&health_url, health_timeout_from_env()) {
        return Err(format!("Development backend is not healthy at {health_url}").into());
    }
    set_status("Dev backend ready", 4, SPLASH_STEPS);
    Ok(BackendStartup {
        base_url: DEV_BACKEND_URL.to_string(),
        child: None,
        runtime_mode: "dev",
    })
}

fn create_main_window(app: &tauri::AppHandle, base_url: &str) -> DesktopResult<WebviewWindow> {
    let url = Url::parse(base_url)?;
    let mut config = app
        .config()
        .app
        .windows
        .first()
        .cloned()
        .ok_or("tauri.conf.json must define a main window")?;
    config.label = MAIN_WINDOW_LABEL.to_string();
    config.create = true;
    config.url = WebviewUrl::External(url);
    config.visible = false;
    config.focus = false;
    let window = WebviewWindowBuilder::from_config(app, &config)?.build()?;
    Ok(window)
}

fn setup_desktop(app: &tauri::App, backend_slot: &SharedBackend) {
    if let Err(error) = create_splash_window(app) {
        eprintln!("Culvia desktop failed to create splash window: {error}");
        emit_smoke_event("splashCreateError", json!({"error": error.to_string()}));
    }
    let app_handle = app.handle().clone();
    let backend_slot = Arc::clone(backend_slot);
    let runtime_config = load_runtime_config();
    let runtime_mode = runtime_mode_from_config(&runtime_config);
    let resource_dir = app.path().resource_dir().ok();

    thread::spawn(move || {
        let startup_progress_handle = app_handle.clone();
        let set_status = move |status: &str, step: u32, total: u32| {
            update_splash_status_from_handle(&startup_progress_handle, status, step, total);
        };

        let backend = match runtime_mode {
            RuntimeMode::Development => start_development_backend(&set_status),
            RuntimeMode::Full => start_production_backend(resource_dir, &set_status),
            RuntimeMode::Lite => start_lite_backend(&runtime_config, &set_status),
            RuntimeMode::Auto => {
                if backend_path_by_resource(resource_dir.clone()).is_ok() {
                    start_production_backend(resource_dir, &set_status)
                } else {
                    start_lite_backend(&runtime_config, &set_status)
                }
            }
        };

        match backend {
            Ok(mut startup) => {
                emit_smoke_event(
                    "backendReady",
                    json!({"baseUrl": startup.base_url, "runtimeMode": startup.runtime_mode}),
                );
                match create_main_window(&app_handle, &startup.base_url) {
                    Ok(window) => {
                        emit_smoke_event(
                            "windowCreated",
                            json!({"label": MAIN_WINDOW_LABEL, "baseUrl": startup.base_url}),
                        );
                        schedule_frontend_ready_probe(
                            window,
                            app_handle.clone(),
                            startup.base_url.clone(),
                        );
                        if let Some(child) = startup.child.take() {
                            if let Ok(mut guard) = backend_slot.lock() {
                                *guard = Some(child);
                            }
                        }
                    }
                    Err(error) => {
                        eprintln!("Culvia desktop failed to create main window: {error}");
                        emit_smoke_event("windowCreateError", json!({"error": error.to_string()}));
                        update_splash_error_from_handle(&app_handle, "Main window failed to open");
                    }
                }
            }
            Err(error) => {
                eprintln!("Culvia desktop backend startup failed: {error}");
                emit_smoke_event("backendError", json!({"error": error.to_string()}));
                update_splash_error_from_handle(&app_handle, "Startup failed");
            }
        }
    });
}

fn stop_backend(backend_slot: &SharedBackend) {
    if let Ok(mut guard) = backend_slot.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn main() {
    let backend_slot: SharedBackend = Arc::new(Mutex::new(None));
    let setup_backend_slot = Arc::clone(&backend_slot);
    let app = match tauri::Builder::default()
        .setup(move |app| {
            setup_desktop(app, &setup_backend_slot);
            Ok(())
        })
        .build(tauri::generate_context!())
    {
        Ok(app) => app,
        Err(error) => {
            eprintln!("Failed to build Culvia desktop shell: {error}");
            std::process::exit(1);
        }
    };
    app.run(move |_app, event| {
        if matches!(event, RunEvent::Exit) {
            stop_backend(&backend_slot);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_json_line() {
        let event = parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/health"}"#,
        )
        .expect("ready event should parse");

        assert_eq!(event.base_url, "http://127.0.0.1:8501");
        assert_eq!(event.health_url, "http://127.0.0.1:8501/health");
        assert!(parse_ready_event(r#"{"event":"log"}"#).is_none());
    }

    #[test]
    fn ready_event_accepts_only_matching_local_http_urls() {
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://localhost:8501","healthUrl":"http://localhost:8501/health"}"#,
        )
        .is_some());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"https://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/health"}"#,
        )
        .is_none());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://example.com:8501","healthUrl":"http://127.0.0.1:8501/health"}"#,
        )
        .is_none());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8502/health"}"#,
        )
        .is_none());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://127.0.0.1","healthUrl":"http://127.0.0.1/health"}"#,
        )
        .is_none());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/"}"#,
        )
        .is_none());
        assert!(parse_ready_event(
            r#"{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/ready"}"#,
        )
        .is_none());
    }

    #[test]
    fn backend_name_matches_runtime_executable_name() {
        assert_eq!(backend_binary_name("aarch64-apple-darwin"), "culvia-server");
        assert_eq!(
            backend_binary_name("x86_64-pc-windows-msvc"),
            "culvia-server.exe"
        );
    }

    #[test]
    fn backend_candidates_include_tauri_bundle_locations() {
        let candidates = candidate_backend_paths_from_dirs(
            "aarch64-apple-darwin",
            Some(PathBuf::from("/App/Contents/Resources")),
            Some(PathBuf::from("/App/Contents/MacOS/culvia-desktop")),
            Some(PathBuf::from("/workspace")),
        );

        assert!(candidates.contains(&PathBuf::from(
            "/App/Contents/MacOS/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server"
        )));
        assert!(candidates.contains(&PathBuf::from(
            "/App/Contents/Resources/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server"
        )));
        assert!(candidates.contains(&PathBuf::from(
            "/App/Contents/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server"
        )));
    }

    #[test]
    fn health_socket_accepts_only_local_http() {
        assert_eq!(
            local_http_socket("http://127.0.0.1:8501/health").unwrap(),
            ("127.0.0.1".to_string(), 8501, "/health".to_string())
        );
        assert!(local_http_socket("https://127.0.0.1:8501/health").is_err());
        assert!(local_http_socket("http://example.com:8501/health").is_err());
        assert!(local_http_socket("http://127.0.0.1/health").is_err());
    }

    #[test]
    fn smoke_exit_delay_parses_positive_millis() {
        assert_eq!(
            smoke_exit_delay(Some("1500")),
            Some(Duration::from_millis(1500))
        );
        assert_eq!(smoke_exit_delay(Some("0")), None);
        assert_eq!(smoke_exit_delay(Some("bad")), None);
        assert_eq!(smoke_exit_delay(None), None);
    }

    #[test]
    fn timeout_secs_uses_default_for_missing_zero_or_invalid_values() {
        let default = Duration::from_secs(120);

        assert_eq!(timeout_secs(Some("45"), default), Duration::from_secs(45));
        assert_eq!(timeout_secs(Some("0"), default), default);
        assert_eq!(timeout_secs(Some("bad"), default), default);
        assert_eq!(timeout_secs(None, default), default);
    }

    #[test]
    fn frontend_ready_result_requires_ready_true() {
        let payload = parse_frontend_ready_result(
            r#"{"ready":true,"title":"Culvia","viewTabs":4,"missing":[]}"#,
        )
        .expect("ready result should parse");

        assert_eq!(payload["viewTabs"], 4);
        assert!(parse_frontend_ready_result(r#"{"ready":false,"viewTabs":4}"#).is_none());
        assert!(parse_frontend_ready_result("not json").is_none());
    }

    #[test]
    fn frontend_ready_script_checks_core_workbench_dom() {
        assert!(FRONTEND_READY_SCRIPT.contains("#mainScoreBtn"));
        assert!(FRONTEND_READY_SCRIPT.contains("#viewerView"));
        assert!(FRONTEND_READY_SCRIPT.contains(".view-tab[data-view='export']"));
        assert!(FRONTEND_READY_SCRIPT.contains("window.CulviaI18n"));
    }

    #[test]
    fn splash_uses_generated_brand_mark() {
        assert!(SPLASH_HTML.contains(r#"<svg id="mark" xmlns="http://www.w3.org/2000/svg""#));
        assert!(SPLASH_HTML.contains("<title>Culvia</title>"));
        assert!(!SPLASH_HTML.contains("M48.1 15.9A22.8"));
        assert!(!SPLASH_HTML.contains("M20.6 34 29.7 42.6 47.4 22.4"));
    }

    #[test]
    fn smoke_event_payload_adds_event_field() {
        let payload = smoke_event_payload("windowCreated", json!({"label": "main"}));

        assert_eq!(payload["event"], "windowCreated");
        assert_eq!(payload["label"], "main");
    }

    #[test]
    fn runtime_mode_defaults_are_explicit() {
        assert_eq!(
            runtime_mode_from_value(None, false, true),
            RuntimeMode::Development
        );
        assert_eq!(
            runtime_mode_from_value(None, false, false),
            RuntimeMode::Full
        );
        assert_eq!(runtime_mode_from_value(None, true, true), RuntimeMode::Full);
        assert_eq!(
            runtime_mode_from_value(Some("lite"), false, false),
            RuntimeMode::Lite
        );
        assert_eq!(
            runtime_mode_from_value(Some("auto"), false, false),
            RuntimeMode::Auto
        );
        assert_eq!(
            runtime_mode_from_value(Some("dev"), true, false),
            RuntimeMode::Development
        );
    }

    #[test]
    fn runtime_mode_can_come_from_config() {
        let config = RuntimeConfigFile {
            mode: Some("lite".to_string()),
            ..RuntimeConfigFile::default()
        };

        assert_eq!(runtime_mode_from_config(&config), RuntimeMode::Lite);
    }

    #[test]
    fn runtime_config_drives_lite_candidates_and_paths() {
        let config = RuntimeConfigFile {
            python: Some("/opt/culvia/python".to_string()),
            venv: Some("/Users/example/Culvia/venv".to_string()),
            package: Some("culvia[desktop-runtime]==9.9.9".to_string()),
            auto_install: Some(false),
            ..RuntimeConfigFile::default()
        };

        assert!(python_command_candidates(&config)
            .iter()
            .any(|candidate| candidate.program == "/opt/culvia/python"));
        assert_eq!(
            lite_venv_path(&config).unwrap(),
            PathBuf::from("/Users/example/Culvia/venv")
        );
        assert_eq!(
            lite_package_install_args(&config),
            vec!["culvia[desktop-runtime]==9.9.9"]
        );
        assert_eq!(config.auto_install, Some(false));
    }

    #[test]
    fn command_spec_keeps_program_and_args_separate() {
        let spec = CommandSpec::new("py", ["-3.11"]);

        assert_eq!(spec.display(), "py -3.11");
    }
}
