from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

ROOT_DIRECTORIES = (
    ".eggs",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "analysis_cache",
    "build",
    "dist",
    "htmlcov",
    "model_cache",
    "culvia_uploads",
    "thumbnail_cache",
    "upload_cache",
)
ROOT_FILES = (".coverage",)
ROOT_GLOBS = (
    "*.egg",
    "*.egg-info",
    "*.part",
    "*.tmp",
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.db",
    "*.db-*",
    "*.csv",
    "desktop/tauri/src-tauri/tauri.*.generated.conf.json",
)
KNOWN_GENERATED_DIRECTORIES = (
    "desktop/tauri/node_modules",
    "desktop/tauri/src-tauri/gen",
    "desktop/tauri/src-tauri/target",
)
BACKEND_RUNTIME_ROOT = "desktop/tauri/src-tauri/runtime/backend"
RECURSIVE_DIRECTORY_NAMES = (
    "__pycache__",
    "node_modules",
)
RECURSIVE_FILE_NAMES = (
    ".DS_Store",
    "Thumbs.db",
)
RECURSIVE_FILE_SUFFIXES = (
    ".pyc",
    ".pyo",
)
EXCLUDED_PARTS = {
    ".git",
}


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path

    @property
    def kind(self) -> str:
        if self.path.is_dir() and not self.path.is_symlink():
            return "dir"
        return "file"


def is_excluded(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in EXCLUDED_PARTS for part in relative.parts)


def existing(paths: Iterable[Path], *, root: Path) -> list[Path]:
    return [path for path in paths if path.exists() and not is_excluded(path, root=root)]


def recursive_directories(root: Path) -> list[Path]:
    found: list[Path] = []
    for name in RECURSIVE_DIRECTORY_NAMES:
        found.extend(path for path in root.rglob(name) if path.is_dir() and not is_excluded(path, root=root))
    return found


def recursive_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for name in RECURSIVE_FILE_NAMES:
        found.extend(path for path in root.rglob(name) if path.is_file() and not is_excluded(path, root=root))
    for suffix in RECURSIVE_FILE_SUFFIXES:
        found.extend(path for path in root.rglob(f"*{suffix}") if path.is_file() and not is_excluded(path, root=root))
    return found


def root_glob_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in ROOT_GLOBS:
        found.extend(path for path in root.glob(pattern) if path.exists() and not is_excluded(path, root=root))
    return found


def backend_runtime_outputs(root: Path) -> list[Path]:
    runtime_root = root / BACKEND_RUNTIME_ROOT
    if not runtime_root.is_dir():
        return []
    return sorted(path for path in runtime_root.iterdir() if path.name != ".gitkeep")


def is_inside_any(path: Path, parents: Sequence[Path]) -> bool:
    for parent in parents:
        if path == parent:
            continue
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            continue
    return False


def collect_candidates(*, root: Path = ROOT) -> list[CleanupCandidate]:
    root = root.resolve()
    raw_paths = [
        *existing((root / relative for relative in ROOT_DIRECTORIES), root=root),
        *existing((root / relative for relative in ROOT_FILES), root=root),
        *existing((root / relative for relative in KNOWN_GENERATED_DIRECTORIES), root=root),
        *existing(backend_runtime_outputs(root), root=root),
        *root_glob_paths(root),
        *recursive_directories(root),
        *recursive_files(root),
    ]
    unique = sorted({path.resolve() for path in raw_paths}, key=lambda item: (len(item.parts), item.as_posix()))
    directories = [path for path in unique if path.is_dir() and not path.is_symlink()]
    filtered = [path for path in unique if not is_inside_any(path, directories)]
    return [CleanupCandidate(path=path) for path in filtered]


def remove_candidate(candidate: CleanupCandidate) -> None:
    if candidate.path.is_dir() and not candidate.path.is_symlink():
        shutil.rmtree(candidate.path)
        return
    candidate.path.unlink(missing_ok=True)


def candidate_payload(candidate: CleanupCandidate, *, root: Path) -> dict:
    return {
        "path": candidate.path.relative_to(root).as_posix(),
        "kind": candidate.kind,
    }


def run_cleanup(*, root: Path = ROOT, apply: bool = False) -> dict:
    root = root.resolve()
    candidates = collect_candidates(root=root)
    removed: list[CleanupCandidate] = []
    if apply:
        for candidate in candidates:
            if candidate.path.exists():
                remove_candidate(candidate)
                removed.append(candidate)
    return {
        "ok": True,
        "applied": apply,
        "candidateCount": len(candidates),
        "removedCount": len(removed),
        "candidates": [candidate_payload(candidate, root=root) for candidate in candidates],
        "removed": [candidate_payload(candidate, root=root) for candidate in removed],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove generated runtime/build artifacts from the repository tree.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--apply", action="store_true", help="Delete candidates. Without this flag the command is dry-run."
    )
    parser.add_argument("--json", action="store_true")
    return parser


def print_text(payload: dict) -> None:
    action = "removed" if payload["applied"] else "would remove"
    print(
        f"{action} {payload['removedCount'] if payload['applied'] else payload['candidateCount']} runtime artifact(s)"
    )
    for item in payload["removed" if payload["applied"] else "candidates"]:
        print(f"- {item['kind']}: {item['path']}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_cleanup(root=args.root, apply=args.apply)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
