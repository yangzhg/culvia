from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from culvia.llm_config_requests import llm_config_update_from_payload
from culvia.secret_store import SecretStoreError, SecretStoreUnavailable

from culvia.job_text import TranslatableValueError


@dataclass(frozen=True)
class LLMConfigServiceDependencies:
    prompt_presets: Mapping[str, object]
    default_prompt_preset: str
    load_persisted_config: Callable[[str | Path], Mapping[str, object]]
    save_persisted_config: Callable[[Mapping[str, object], str | Path], Mapping[str, str]]
    set_persisted_config: Callable[[Mapping[str, object] | None], Mapping[str, str]]
    set_session_config: Callable[[Mapping[str, object] | None], Mapping[str, str]]
    clear_session_config: Callable[..., None]
    set_secure_config: Callable[[Mapping[str, object] | None], Mapping[str, str]]
    clear_secure_config: Callable[..., None]
    load_api_key: Callable[[], str]
    save_api_key: Callable[[str], None]
    delete_api_key: Callable[[], None]


def refresh_persisted_llm_config_action(
    cache_path: str | Path,
    dependencies: LLMConfigServiceDependencies,
) -> None:
    try:
        dependencies.set_persisted_config(dependencies.load_persisted_config(cache_path))
    except Exception:
        dependencies.set_persisted_config({})

    try:
        dependencies.set_secure_config({"api_key": dependencies.load_api_key()})
    except SecretStoreUnavailable:
        dependencies.set_secure_config({})
    except SecretStoreError:
        dependencies.set_secure_config({})


def apply_llm_config_action(
    payload: Mapping[str, object],
    cache_path: str | Path,
    dependencies: LLMConfigServiceDependencies,
) -> None:
    update = llm_config_update_from_payload(
        payload,
        prompt_presets=dependencies.prompt_presets,
        default_prompt_preset=dependencies.default_prompt_preset,
    )

    if update.clear_api_key:
        dependencies.clear_session_config("api_key")
        dependencies.clear_secure_config("api_key")
        try:
            dependencies.delete_api_key()
        except SecretStoreUnavailable:
            pass
        except SecretStoreError as exc:
            raise TranslatableValueError(
                "error.keychainClearFailed", fallback=f"系统钥匙串清除失败：{exc}", reason=str(exc)
            ) from exc

    dependencies.set_session_config(update.config)

    if update.persist:
        api_key = update.config.get("api_key")
        if api_key:
            try:
                dependencies.save_api_key(api_key)
                dependencies.set_secure_config({"api_key": api_key})
            except SecretStoreUnavailable:
                dependencies.clear_secure_config("api_key")
            except SecretStoreError as exc:
                raise TranslatableValueError(
                    "error.keychainSaveFailed", fallback=f"系统钥匙串保存失败：{exc}", reason=str(exc)
                ) from exc
        persisted = dependencies.save_persisted_config(update.config, cache_path)
        dependencies.set_persisted_config(persisted)
