from __future__ import annotations

import argparse
import json
import platform
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from culvia import secret_store


DEFAULT_SENTINEL_PREFIX = "culvia-keychain-smoke"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def masked(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return f"{text[:2]}****"
    return f"{text[:4]}****{text[-4:]}"


def make_sentinel() -> str:
    return f"{DEFAULT_SENTINEL_PREFIX}-{secrets.token_hex(12)}"


def safe_error(exc: Exception, *secrets_to_hide: str) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    for secret in secrets_to_hide:
        if secret:
            text = text.replace(secret, masked(secret))
    return text


def _backend_label(keyring_module: Any | None) -> str:
    if keyring_module is not None:
        return keyring_module.__class__.__name__
    try:
        keyring = secret_store._load_keyring()  # type: ignore[attr-defined]  # Internal read for diagnostics.
    except Exception as exc:  # noqa: BLE001
        return exc.__class__.__name__
    get_backend = getattr(keyring, "get_keyring", None)
    if callable(get_backend):
        try:
            return str(get_backend())
        except Exception as exc:  # noqa: BLE001
            return exc.__class__.__name__
    return getattr(keyring, "__name__", keyring.__class__.__name__)


def result_payload(
    checks: Sequence[CheckResult],
    *,
    seconds: float | None = None,
    restored: bool | None = None,
    original_label: str = "",
    backend: str = "",
) -> dict[str, Any]:
    failed = [item.name for item in checks if not item.ok]
    payload: dict[str, Any] = {
        "ok": not failed,
        "failed": failed,
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
        "service": secret_store.SERVICE_NAME,
        "username": secret_store.LLM_API_KEY_USERNAME,
        "platform": platform.system(),
    }
    if backend:
        payload["backend"] = backend
    if seconds is not None:
        payload["seconds"] = round(seconds, 3)
    if restored is not None:
        payload["restored"] = restored
    if original_label:
        payload["originalLabel"] = original_label
    return payload


def collect_checks(
    *,
    allow_write: bool,
    preserve_existing: bool = False,
    keyring_module: Any | None = None,
    sentinel: str | None = None,
) -> tuple[list[CheckResult], dict[str, Any]]:
    checks: list[CheckResult] = []
    metadata: dict[str, Any] = {
        "backend": _backend_label(keyring_module),
        "restored": False,
        "original_label": "",
    }

    if not allow_write:
        return [
            check(
                "keychain smoke requires explicit write consent",
                False,
                "pass --allow-write to save, read, delete, and restore a temporary sentinel secret",
            )
        ], metadata

    if not secret_store.keyring_available(keyring_module=keyring_module):
        return [
            check(
                "system keychain backend is unavailable",
                False,
                (
                    f"backend={metadata['backend']}; install the desktop extra, run inside a native desktop "
                    f"user session, and keep {secret_store.DISABLE_KEYCHAIN_ENV} unset"
                ),
            )
        ], metadata

    checks.append(check("system keychain backend is available", True, f"backend={metadata['backend']}"))

    original = ""
    original_loaded = False
    sentinel_written = False
    value = sentinel or make_sentinel()
    try:
        original = secret_store.load_llm_api_key(keyring_module=keyring_module)
        original_loaded = True
        metadata["original_label"] = masked(original)
        if original and not preserve_existing:
            checks.append(
                check(
                    "existing LLM API key requires preserve-existing mode",
                    False,
                    "existing secret detected; rerun with --preserve-existing to restore it after smoke",
                )
            )
            original_loaded = False
            return checks, metadata
        checks.append(
            check(
                "existing LLM API key can be read before smoke",
                True,
                "existing secret captured for restoration" if original else "no existing secret",
            )
        )

        secret_store.save_llm_api_key(value, keyring_module=keyring_module)
        sentinel_written = True
        loaded = secret_store.load_llm_api_key(keyring_module=keyring_module)
        save_ok = loaded == value
        checks.append(check("temporary sentinel can be saved and read", save_ok, f"loadedLabel={masked(loaded)}"))
        if not save_ok:
            checks.append(
                check(
                    "keychain slot still belongs to sentinel before cleanup",
                    False,
                    "concurrent modification detected before delete",
                )
            )
        else:
            secret_store.delete_llm_api_key(keyring_module=keyring_module)
            deleted_value = secret_store.load_llm_api_key(keyring_module=keyring_module)
            sentinel_written = False
            checks.append(
                check(
                    "temporary sentinel can be deleted",
                    deleted_value == "",
                    f"afterDeleteLabel={masked(deleted_value)}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("keychain smoke operation completed", False, safe_error(exc, value, original)))
    finally:
        if original_loaded:
            try:
                if sentinel_written:
                    current = secret_store.load_llm_api_key(keyring_module=keyring_module)
                    if current != value:
                        checks.append(
                            check(
                                "original keychain state restored",
                                False,
                                f"concurrent modification detected; currentLabel={masked(current)}",
                            )
                        )
                        return checks, metadata
                if original:
                    secret_store.save_llm_api_key(original, keyring_module=keyring_module)
                elif sentinel_written:
                    secret_store.delete_llm_api_key(keyring_module=keyring_module)
                metadata["restored"] = True
            except Exception as exc:  # noqa: BLE001
                metadata["restored"] = False
                checks.append(check("original keychain state restored", False, safe_error(exc, value, original)))
            else:
                checks.append(
                    check(
                        "original keychain state restored",
                        True,
                        "existing secret restored" if original else "smoke secret removed",
                    )
                )

    return checks, metadata


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify system keychain read/write/delete for the LLM API key slot.")
    parser.add_argument(
        "--allow-write", action="store_true", help="write a temporary sentinel secret and restore state"
    )
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help="allow the smoke to temporarily replace an existing key and restore it afterward",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    start = time.monotonic()
    checks, metadata = collect_checks(allow_write=args.allow_write, preserve_existing=args.preserve_existing)
    payload = result_payload(
        checks,
        seconds=time.monotonic() - start,
        restored=bool(metadata.get("restored")),
        original_label=str(metadata.get("original_label") or ""),
        backend=str(metadata.get("backend") or ""),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for item in checks:
            status = "OK" if item.ok else "FAIL"
            print(f"{status} {item.name}: {item.detail}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
