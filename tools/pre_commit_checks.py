from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
TAURI_MANIFEST = ROOT / "desktop" / "tauri" / "src-tauri" / "Cargo.toml"
POSIX_SHELL_FILES = (
    ROOT / "bin" / "culvia-web",
    ROOT / "scripts" / "culvia-dev",
)
SECRET_TEXT_SUFFIXES = {
    ".cfg",
    ".bat",
    ".cmd",
    ".conf",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".plist",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_TEXT_NAMES = {
    ".gitignore",
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "culvia-dev",
    "culvia-web",
}
SECRET_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "analysis_cache",
    "build",
    "dist",
    "gen",
    "htmlcov",
    "culvia.egg-info",
    "culvia_uploads",
    "model_cache",
    "node_modules",
    "target",
    "thumbnail_cache",
    "upload_cache",
}
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-compatible API key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{16,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    line_number: int
    label: str
    match: str


def command_text(command: Sequence[str]) -> str:
    return " ".join(command)


def run(command: Sequence[str], *, cwd: Path = ROOT) -> int:
    print(f"$ {command_text(command)}")
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode


def require_executable(name: str) -> bool:
    if shutil.which(name):
        return True
    print(f"Missing required executable: {name}", file=sys.stderr)
    return False


def js_files() -> list[Path]:
    return sorted(WEB_DIR.rglob("*.js"))


def check_js_syntax() -> int:
    if not require_executable("node"):
        return 1
    status = 0
    for path in js_files():
        status = run(("node", "--check", str(path.relative_to(ROOT)))) or status
    return status


def check_shell_syntax() -> int:
    if not require_executable("sh"):
        return 1
    status = 0
    for path in POSIX_SHELL_FILES:
        status = run(("sh", "-n", str(path.relative_to(ROOT)))) or status
    return status


def check_makefile() -> int:
    if not require_executable("make"):
        return 1
    return run(("make", "-n", "help"))


def rust_format_command(*, fix: bool = False) -> tuple[str, ...]:
    command = ["cargo", "fmt", "--manifest-path", str(TAURI_MANIFEST.relative_to(ROOT)), "--all"]
    if not fix:
        command.extend(("--", "--check"))
    return tuple(command)


def check_rust_format(*, fix: bool = False) -> int:
    if not TAURI_MANIFEST.exists():
        return 0
    if not require_executable("cargo"):
        return 1
    return run(rust_format_command(fix=fix))


def git_tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ("git", "-C", str(root), "ls-files", "-z"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return [path for path in root.rglob("*") if path.is_file()]
    return [root / item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def should_scan_secret_file(path: Path, *, root: Path = ROOT) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part in SECRET_EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False
    return path.name in SECRET_TEXT_NAMES or path.suffix in SECRET_TEXT_SUFFIXES


def iter_secret_findings(paths: Iterable[Path], *, root: Path = ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in sorted(paths):
        if not path.exists() or not path.is_file() or not should_scan_secret_file(path, root=root):
            continue
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    findings.append(
                        SecretFinding(path=path, line_number=line_number, label=label, match=match.group(0))
                    )
    return findings


def check_secret_scan(*, root: Path = ROOT) -> int:
    findings = iter_secret_findings(git_tracked_files(root), root=root)
    for finding in findings:
        relative = finding.path.relative_to(root).as_posix()
        print(f"{relative}:{finding.line_number}: {finding.label}: {finding.match}", file=sys.stderr)
    return 1 if findings else 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Culvia pre-commit helper checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("js-syntax")
    subparsers.add_parser("shell-syntax")
    subparsers.add_parser("makefile")
    rust_parser = subparsers.add_parser("rust-format")
    rust_parser.add_argument("--fix", action="store_true", help="Apply cargo fmt instead of checking only.")
    subparsers.add_parser("secret-scan")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "js-syntax":
        return check_js_syntax()
    if args.command == "shell-syntax":
        return check_shell_syntax()
    if args.command == "makefile":
        return check_makefile()
    if args.command == "rust-format":
        return check_rust_format(fix=args.fix)
    if args.command == "secret-scan":
        return check_secret_scan()
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
