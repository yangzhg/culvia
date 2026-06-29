from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024


def default_checksum_path(artifact: Path) -> Path:
    return Path(str(artifact) + ".sha256")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_text(*, digest: str, artifact: Path) -> str:
    return f"{digest}  {artifact.name}\n"


def write_checksum(*, artifact: Path, output: Path | None = None) -> dict[str, Any]:
    artifact = artifact.resolve()
    checksum_path = default_checksum_path(artifact) if output is None else output.resolve()
    issues: list[str] = []
    if not artifact.is_file():
        issues.append(f"missing artifact: {artifact}")
    if checksum_path == artifact:
        issues.append("checksum output must not overwrite the artifact")
    if issues:
        return {
            "ok": False,
            "issues": issues,
            "artifact": str(artifact),
            "checksumPath": str(checksum_path),
        }

    digest = sha256_file(artifact)
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text(checksum_text(digest=digest, artifact=artifact), encoding="utf-8")
    return {
        "ok": True,
        "issues": [],
        "algorithm": "sha256",
        "artifact": str(artifact),
        "artifactName": artifact.name,
        "checksumPath": str(checksum_path),
        "checksumName": checksum_path.name,
        "sha256": digest,
        "sizeBytes": artifact.stat().st_size,
        "writtenAt": int(time.time()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a SHA-256 checksum sidecar for a release artifact.")
    parser.add_argument("artifact", type=Path, help="Release artifact to hash.")
    parser.add_argument(
        "--output", type=Path, default=None, help="Checksum output path. Defaults to <artifact>.sha256."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = write_checksum(artifact=args.artifact, output=args.output)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        status = "OK" if payload["ok"] else "FAIL"
        print(f"{status} release checksum: {payload['checksumPath']}")
        for issue in payload["issues"]:
            print(f"FAIL {issue}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
