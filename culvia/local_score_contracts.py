from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


MODEL_ANALYSIS_CACHE_PROFILE = "rgb-jpeg-progressive-v1"
MODEL_ANALYSIS_MAX_SIZE = 768
MODEL_ANALYSIS_MIN_SIZE = 224
MODEL_ANALYSIS_SIZE_LIMIT = 1600
MODEL_ANALYSIS_JPEG_QUALITY = 90
CORE_SCORE_MULTIPLIER = 2.0
CLIP_LOGIT_SCALE = 100.0
CLIP_SCORE_SCALE = 10.0


CLIP_PROMPT_PAIRS = {
    "clip_iqa_overall": (
        "a high quality photo",
        "a low quality photo",
    ),
    "clip_iqa_sharpness": (
        "a sharp clear photo",
        "a blurry out of focus photo",
    ),
    "clip_iqa_exposure": (
        "a well exposed photo",
        "an overexposed or underexposed photo",
    ),
    "clip_iqa_cleanliness": (
        "a clean photo with little noise",
        "a noisy grainy photo",
    ),
    "clip_aesthetic": (
        "a beautiful aesthetically pleasing photograph",
        "an unattractive poorly composed photograph",
    ),
}


def model_analysis_input_contract() -> dict[str, Any]:
    return {
        "cacheProfile": MODEL_ANALYSIS_CACHE_PROFILE,
        "colorMode": "RGB",
        "jpegQuality": MODEL_ANALYSIS_JPEG_QUALITY,
        "maximumSize": MODEL_ANALYSIS_SIZE_LIMIT,
        "minimumSize": MODEL_ANALYSIS_MIN_SIZE,
        "requestedSize": MODEL_ANALYSIS_MAX_SIZE,
    }


MODEL_ANALYSIS_CACHE_VARIANT = (
    "model-input-v1:"
    + hashlib.sha256(
        json.dumps(
            model_analysis_input_contract(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
)


def canonical_result_version(
    *,
    capability_key: str,
    model_id: str,
    model_version: str,
    weight_sha256: str,
    score_contract: Mapping[str, Any],
) -> str:
    payload = json.dumps(
        {
            "capability": capability_key,
            "model": model_id,
            "modelVersion": model_version,
            "scoreContract": score_contract,
            "weightSha256": weight_sha256,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"score-v1:{hashlib.sha256(payload).hexdigest()}"


def core_aesthetic_score_contract(fields: Iterable[str]) -> dict[str, Any]:
    return {
        "algorithm": "clip-vision-seven-linear-heads-v1",
        "fields": list(fields),
        "input": model_analysis_input_contract(),
        "sourceScale": "0_5",
        "targetScale": "0_10",
        "multiplier": CORE_SCORE_MULTIPLIER,
    }


def clip_score_contract(fields: Iterable[str]) -> dict[str, Any]:
    selected_fields = list(fields)
    return {
        "algorithm": "normalized-cosine-softmax-positive-v1",
        "fields": selected_fields,
        "input": model_analysis_input_contract(),
        "logitScale": CLIP_LOGIT_SCALE,
        "outputScale": CLIP_SCORE_SCALE,
        "prompts": {field: list(CLIP_PROMPT_PAIRS[field]) for field in selected_fields},
    }
