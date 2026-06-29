from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

MACOS_APP_GENERATED_DIRECTORIES = (
    "desktop/tauri/src-tauri/gen",
    "desktop/tauri/src-tauri/target",
)
BACKEND_RUNTIME_ROOT = "desktop/tauri/src-tauri/runtime/backend"


@dataclass(frozen=True)
class MacosAppCleanupCandidate:
    path: Path

    @property
    def kind(self) -> str:
        if self.path.is_dir() and not self.path.is_symlink():
            return "dir"
        return "file"


def existing(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def backend_runtime_outputs(root: Path) -> list[Path]:
    runtime_root = root / BACKEND_RUNTIME_ROOT
    if not runtime_root.is_dir():
        return []
    return sorted(path for path in runtime_root.iterdir() if path.name != ".gitkeep")


def collect_candidates(*, root: Path = ROOT) -> list[MacosAppCleanupCandidate]:
    root = root.resolve()
    raw_paths = [
        *existing(root / relative for relative in MACOS_APP_GENERATED_DIRECTORIES),
        *backend_runtime_outputs(root),
    ]
    return [MacosAppCleanupCandidate(path=path.resolve()) for path in sorted(raw_paths)]


def remove_candidate(candidate: MacosAppCleanupCandidate) -> None:
    if candidate.path.is_dir() and not candidate.path.is_symlink():
        shutil.rmtree(candidate.path)
        return
    candidate.path.unlink(missing_ok=True)


def candidate_payload(candidate: MacosAppCleanupCandidate, *, root: Path) -> dict:
    return {
        "path": candidate.path.relative_to(root).as_posix(),
        "kind": candidate.kind,
    }


def run_cleanup(*, root: Path = ROOT, apply: bool = False) -> dict:
    root = root.resolve()
    candidates = collect_candidates(root=root)
    removed: list[MacosAppCleanupCandidate] = []
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
    parser = argparse.ArgumentParser(description="Remove generated local macOS desktop app artifacts.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--apply", action="store_true", help="Delete candidates. Without this flag the command is dry-run."
    )
    parser.add_argument("--json", action="store_true")
    return parser


def print_text(payload: dict) -> None:
    action = "removed" if payload["applied"] else "would remove"
    print(
        f"{action} {payload['removedCount'] if payload['applied'] else payload['candidateCount']} macOS app artifact(s)"
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
