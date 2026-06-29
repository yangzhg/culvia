from __future__ import annotations

import json
from collections.abc import Iterable as IterableABC, Mapping
from typing import Iterable


DEFAULT_OVERALL_AESTHETIC_WEIGHT = 0.75
DEFAULT_OVERALL_TECHNICAL_WEIGHT = 0.25


def clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 10.0))


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_json_mapping(text: str) -> dict[str, object]:
    candidate = strip_json_fence(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("大模型没有返回可解析的 JSON。") from None
        parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("大模型返回内容不是 JSON 对象。")
    return parsed


def first_text_choice(payload: Mapping[str, object]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, Mapping):
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                            parts.append(str(item["text"]))
                    if parts:
                        return "\n".join(parts)
            text = choice.get("text")
            if isinstance(text, str):
                return text
    raise RuntimeError("大模型响应中没有文本内容。")


def llm_float(raw: object, fallback: float | None = None) -> float | None:
    try:
        value = float(raw)
    except Exception:
        return fallback
    return value


def nested_value(raw: Mapping[str, object], path: tuple[str, ...]) -> object:
    current: object = raw
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def llm_score_from_paths(
    raw: Mapping[str, object],
    paths: Iterable[tuple[str, ...]],
    fallback: float | None = None,
) -> float | None:
    for path in paths:
        value = nested_value(raw, path)
        if value is None:
            continue
        parsed = llm_float(value)
        if parsed is not None:
            return clamp_score(parsed)
    return fallback


def average_scores(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return clamp_score(sum(usable) / len(usable))


def string_list(raw: object, limit: int = 3) -> tuple[str, ...]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, IterableABC) and not isinstance(raw, (bytes, bytearray, Mapping)):
        values = [str(item) for item in raw]
    else:
        values = []
    return tuple(item.strip() for item in values if item.strip())[:limit]


def llm_suggestions(raw: Mapping[str, object]) -> tuple[str, ...]:
    suggestions: list[str] = []
    for item in string_list(raw.get("photography_suggestions")):
        suggestions.append(f"拍摄：{item}")
    for item in string_list(raw.get("retouching_suggestions")):
        suggestions.append(f"修图：{item}")
    if not suggestions:
        suggestions.extend(string_list(raw.get("suggestions"), limit=6))
    return tuple(suggestions[:6])


def llm_review_scores(
    raw: Mapping[str, object],
    *,
    aesthetic_weight: float = DEFAULT_OVERALL_AESTHETIC_WEIGHT,
    technical_weight: float = DEFAULT_OVERALL_TECHNICAL_WEIGHT,
) -> dict[str, float]:
    aesthetic_values = {
        "llm_aesthetic_overall": llm_score_from_paths(
            raw,
            (
                ("scores", "aesthetic", "overall"),
                ("aesthetic", "overall"),
                ("aesthetic_score",),
                ("llm_aesthetic_overall",),
            ),
        ),
        "llm_quality": llm_score_from_paths(raw, (("scores", "aesthetic", "quality"), ("aesthetic", "quality"))),
        "llm_composition": llm_score_from_paths(
            raw,
            (("scores", "aesthetic", "composition"), ("aesthetic", "composition")),
        ),
        "llm_lighting": llm_score_from_paths(raw, (("scores", "aesthetic", "lighting"), ("aesthetic", "lighting"))),
        "llm_color": llm_score_from_paths(raw, (("scores", "aesthetic", "color"), ("aesthetic", "color"))),
        "llm_depth_of_field": llm_score_from_paths(
            raw,
            (("scores", "aesthetic", "depth_of_field"), ("aesthetic", "depth_of_field")),
        ),
        "llm_content": llm_score_from_paths(raw, (("scores", "aesthetic", "content"), ("aesthetic", "content"))),
    }
    technical_values = {
        "llm_technical_overall": llm_score_from_paths(
            raw,
            (
                ("scores", "technical", "overall"),
                ("technical", "overall"),
                ("technical_score",),
                ("llm_technical_overall",),
            ),
        ),
        "llm_sharpness": llm_score_from_paths(raw, (("scores", "technical", "sharpness"), ("technical", "sharpness"))),
        "llm_exposure": llm_score_from_paths(raw, (("scores", "technical", "exposure"), ("technical", "exposure"))),
        "llm_contrast": llm_score_from_paths(raw, (("scores", "technical", "contrast"), ("technical", "contrast"))),
        "llm_cleanliness": llm_score_from_paths(
            raw,
            (("scores", "technical", "cleanliness"), ("technical", "cleanliness")),
        ),
    }

    if aesthetic_values["llm_aesthetic_overall"] is None:
        aesthetic_values["llm_aesthetic_overall"] = average_scores(
            value for key, value in aesthetic_values.items() if key != "llm_aesthetic_overall"
        )
    if technical_values["llm_technical_overall"] is None:
        technical_values["llm_technical_overall"] = average_scores(
            value for key, value in technical_values.items() if key != "llm_technical_overall"
        )

    overall = llm_score_from_paths(raw, (("scores", "overall"), ("overall_score",), ("llm_review_overall",)))
    if overall is None:
        aesthetic = aesthetic_values["llm_aesthetic_overall"]
        technical = technical_values["llm_technical_overall"]
        if aesthetic is not None and technical is not None:
            overall = clamp_score(aesthetic * aesthetic_weight + technical * technical_weight)
        else:
            overall = average_scores((aesthetic, technical))

    scores = {
        "llm_review_overall": overall,
        **aesthetic_values,
        **technical_values,
    }
    return {key: round(float(value), 4) for key, value in scores.items() if value is not None}
