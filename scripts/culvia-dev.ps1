param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonDist = Join-Path (Join-Path $RepoRoot "dist") "python"
$Venv = if ($env:CULVIA_VENV) { $env:CULVIA_VENV } else { Join-Path $HOME ".venvs/culvia" }
$BasePython = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Show-Help {
    @"
Culvia developer command runner

Usage:
  scripts/culvia-dev.ps1 <command> [args...]

Environment:
  CULVIA_VENV  Virtualenv path. Default: ~/.venvs/culvia
  PYTHON          Python executable used to create the virtualenv. Default: python

Commands:
  init                 Create/update the dev virtualenv and install .[desktop,release,dev]
  install              Create/update the virtualenv and install the runtime package
  web [args...]        Start the Web server from the source checkout
  server [args...]     Start the supervised local app from the source checkout
  cli [args...]        Run the batch scoring CLI
  runtime-config       Show the persisted desktop runtime config
  runtime-configure    Update the persisted desktop runtime config
  runtime-reset-config Remove the persisted desktop runtime config
  runtime-doctor       Inspect the app-managed Python runtime
  runtime-create       Create the app-managed Python virtualenv
  runtime-install      Install Culvia into the app-managed Python runtime
  runtime-ensure       Create and repair the app-managed Python runtime
  test                 Run the unit test suite
  js-check             Check all web/**/*.js files with node --check
  lint                 Run high-signal lint, syntax, format, and secret checks
  format               Format Python and Rust source files
  pre-commit-install   Install Git pre-commit hooks
  pre-commit           Run all pre-commit hooks against the repository
  gate                 Run formal gate without release smoke
  gate-full            Run the full formal gate
  desktop-ready          Run Desktop readiness checks
  desktop-dev          Install desktop npm deps and run the dev shell
  app-icons            Sync web favicon, desktop icons, and splash mark from assets/brand/culvia-icon.svg
  backend-plan         Check the PyInstaller backend build plan
  backend-placeholder  Ensure the desktop compile-check backend placeholder
  backend-build        Build the production backend
  python-release-plan  Print the pip wheel/sdist release build command
  python-release       Build and verify pip wheel/sdist artifacts under dist/python
  macos-release-plan   Print the local macOS release build plan
  macos-release        Build the local macOS app/dmg release
  macos-lite-release-plan
                       Print the local macOS Lite app/dmg release plan
  macos-lite-release   Build the local macOS Lite app/dmg release
  macos-notarized-release-plan
                       Print the strict Developer ID/notarized macOS release plan
  macos-notarized-release
                       Build the strict Developer ID/notarized macOS release
  windows-release-plan Print the Windows native release contract
  windows-release      Run the Windows native release contract on Windows
  windows-lite-release-plan
                       Print the Windows Lite native release contract
  windows-lite-release Run the Windows Lite native release contract on Windows
  linux-release-plan   Print the Linux native release contract
  linux-release        Run the Linux native release contract on Linux
  linux-lite-release-plan
                       Print the Linux Lite native release contract
  linux-lite-release   Run the Linux Lite native release contract on Linux
  lite-release-plan    Print the Lite release plan for the current OS
  lite-release         Build the Lite release for the current OS
  release-status       Print the release status report
  clean [args...]      Run runtime artifact cleanup; pass --apply to delete
"@
}

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$CommandArgs
    )
    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Get-VenvPython {
    $candidates = @(
        (Join-Path $Venv "Scripts/python.exe"),
        (Join-Path $Venv "bin/python")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $BasePython
}

function Ensure-Venv {
    $windowsPython = Join-Path $Venv "Scripts/python.exe"
    $posixPython = Join-Path $Venv "bin/python"
    if ((Test-Path $windowsPython) -or (Test-Path $posixPython)) {
        return
    }
    $parent = Split-Path $Venv -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    Invoke-Checked $BasePython @("-m", "venv", $Venv)
}

function Invoke-PythonMain {
    param(
        [string]$Module,
        [string]$DisplayName,
        [string[]]$CommandArgs
    )
    Push-Location $RepoRoot
    try {
        $python = Get-VenvPython
        Invoke-Checked $python (@("-c", "from $Module import main; import sys; sys.argv[0] = '$DisplayName'; raise SystemExit(main(sys.argv[1:]))") + $CommandArgs)
    }
    finally {
        Pop-Location
    }
}

function Invoke-Tool {
    param(
        [string[]]$CommandArgs
    )
    Push-Location $RepoRoot
    try {
        $python = Get-VenvPython
        Invoke-Checked $python $CommandArgs
    }
    finally {
        Pop-Location
    }
}

$CommandName = if ($Args.Count -gt 0) { $Args[0] } else { "help" }
$Rest = if ($Args.Count -gt 1) { $Args[1..($Args.Count - 1)] } else { @() }

switch ($CommandName) {
    { $_ -in @("help", "-h", "--help") } { Show-Help }
    "init" {
        Ensure-Venv
        $python = Get-VenvPython
        Push-Location $RepoRoot
        try {
            Invoke-Checked $python @("-m", "pip", "install", "-U", "pip")
            Invoke-Checked $python @("-m", "pip", "install", "-e", ".[desktop,release,dev]")
        }
        finally {
            Pop-Location
        }
    }
    "install" {
        Ensure-Venv
        $python = Get-VenvPython
        Push-Location $RepoRoot
        try {
            Invoke-Checked $python @("-m", "pip", "install", "-U", "pip")
            Invoke-Checked $python @("-m", "pip", "install", "-e", ".")
        }
        finally {
            Pop-Location
        }
    }
    "web" { Invoke-PythonMain "culvia.server" "culvia-web" $Rest }
    "server" { Invoke-PythonMain "culvia.supervisor" "culvia-supervisor" $Rest }
    "cli" { Invoke-PythonMain "culvia.cli" "culvia" $Rest }
    "runtime-config" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("config") + $Rest) }
    "runtime-configure" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("configure") + $Rest) }
    "runtime-reset-config" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("reset-config") + $Rest) }
    "runtime-doctor" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("doctor") + $Rest) }
    "runtime-create" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("create") + $Rest) }
    "runtime-install" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("install") + $Rest) }
    "runtime-ensure" { Invoke-PythonMain "culvia.runtime_manager" "culvia runtime" (@("ensure") + $Rest) }
    "test" {
        $env:CULVIA_DISABLE_KEYCHAIN = "1"
        try { Invoke-Tool @("-m", "unittest", "discover", "-s", "tests") }
        finally { Remove-Item Env:CULVIA_DISABLE_KEYCHAIN -ErrorAction SilentlyContinue }
    }
    "js-check" { Invoke-Tool @("tools/pre_commit_checks.py", "js-syntax") }
    "lint" {
        Invoke-Tool @("-m", "ruff", "format", "--check", "culvia", "culvia_app.py", "tests", "tools", "desktop/tauri/scripts")
        Invoke-Tool @("-m", "ruff", "check", "culvia", "culvia_app.py", "tests", "tools", "desktop/tauri/scripts")
        Invoke-Tool @("tools/pre_commit_checks.py", "js-syntax")
        Invoke-Tool @("tools/pre_commit_checks.py", "shell-syntax")
        Invoke-Tool @("tools/pre_commit_checks.py", "makefile")
        Invoke-Tool @("tools/pre_commit_checks.py", "rust-format")
        Invoke-Tool @("tools/pre_commit_checks.py", "secret-scan")
    }
    "format" {
        Invoke-Tool @("-m", "ruff", "format", "culvia", "culvia_app.py", "tests", "tools", "desktop/tauri/scripts")
        Invoke-Tool @("tools/pre_commit_checks.py", "rust-format", "--fix")
    }
    "pre-commit-install" { Invoke-Tool @("-m", "pre_commit", "install") }
    "pre-commit" { Invoke-Tool @("-m", "pre_commit", "run", "--all-files") }
    "gate" { Invoke-Tool @("tools/formal_gate.py", "--skip-release-smoke") }
    "gate-full" { Invoke-Tool @("tools/formal_gate.py") }
    "desktop-ready" { Invoke-Tool @("tools/check_desktop_readiness.py") }
    "desktop-dev" {
        Push-Location $RepoRoot
        try {
            Invoke-Checked "npm" @("--prefix", "desktop/tauri", "install")
            Invoke-Checked "npm" @("--prefix", "desktop/tauri", "run", "tauri:dev")
        }
        finally {
            Pop-Location
        }
    }
    "app-icons" { Invoke-Tool (@("tools/generate_app_icons.py") + $Rest) }
    "backend-plan" { Invoke-Tool @("desktop/tauri/scripts/build-backend.py", "--check-plan") }
    "backend-placeholder" { Invoke-Tool @("desktop/tauri/scripts/build-backend.py", "--ensure-placeholder") }
    "backend-build" { Invoke-Tool @("desktop/tauri/scripts/build-backend.py", "--build") }
    "python-release-plan" { Write-Output "python tools/release_smoke.py --build --wheelhouse dist/python --build-sdist --dist-dir dist/python --install --twine-check --strict" }
    "python-release" { Invoke-Tool @("tools/release_smoke.py", "--build", "--wheelhouse", $PythonDist, "--build-sdist", "--dist-dir", $PythonDist, "--install", "--twine-check", "--strict") }
    "macos-release-plan" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first", "--check-plan") }
    "macos-release" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first") }
    "macos-lite-release-plan" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first", "--runtime-profile", "lite", "--check-plan") }
    "macos-lite-release" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first", "--runtime-profile", "lite") }
    "macos-notarized-release-plan" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first", "--strict-release-signing", "--strict-artifacts", "--check-plan") }
    "macos-notarized-release" { Invoke-Tool @("tools/build_macos_app.py", "--clean-first", "--strict-release-signing", "--strict-artifacts") }
    "windows-release-plan" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--check-plan") }
    "windows-release" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--run") }
    "windows-lite-release-plan" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--profile", "lite", "--check-plan") }
    "windows-lite-release" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--profile", "lite", "--run") }
    "linux-release-plan" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "linux", "--check-plan") }
    "linux-release" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "linux", "--run") }
    "linux-lite-release-plan" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "linux", "--profile", "lite", "--check-plan") }
    "linux-lite-release" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "linux", "--profile", "lite", "--run") }
    "lite-release-plan" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--profile", "lite", "--check-plan") }
    "lite-release" { Invoke-Tool @("tools/desktop_release_contract.py", "--platform", "windows", "--profile", "lite", "--run") }
    "release-status" { Invoke-Tool @("tools/release_status_report.py") }
    "clean" { Invoke-Tool (@("tools/clean_runtime_artifacts.py") + $Rest) }
    default {
        Write-Error "Unknown command: $CommandName"
        Show-Help
        exit 2
    }
}
