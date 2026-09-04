from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from culvia.job_text import TranslatableRuntimeError
from culvia.local_score_contracts import CLIP_LOGIT_SCALE, CLIP_PROMPT_PAIRS, CLIP_SCORE_SCALE
from culvia.model_files import MODEL_PT_SHA256


@dataclass
class LoadedAestheticModel:
    processor: object
    model: object
    device: str


@dataclass
class LoadedClipReferenceModel:
    processor: object
    model: object
    device: str
    text_features: dict[str, object]


def load_torch_object(model_path: str) -> object:
    import torch

    label = Path(model_path).name
    digest = hashlib.sha256()
    try:
        with Path(model_path).open("rb") as model_file:
            before = os.fstat(model_file.fileno())
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
            after_hash = os.fstat(model_file.fileno())
            fingerprint_fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_ino")
            if any(getattr(before, field) != getattr(after_hash, field) for field in fingerprint_fields):
                raise TranslatableRuntimeError(
                    "error.modelIntegrityFailed",
                    fallback=f"模型文件完整性校验失败：{label}",
                    filename=label,
                )
            if not hmac.compare_digest(digest.hexdigest(), MODEL_PT_SHA256):
                raise TranslatableRuntimeError(
                    "error.modelIntegrityFailed",
                    fallback=f"模型文件完整性校验失败：{label}",
                    filename=label,
                )

            model_file.seek(0)
            try:
                loaded = torch.load(model_file, map_location="cpu", weights_only=True)
            except Exception as safe_error:
                raise TranslatableRuntimeError(
                    "error.modelSafeLoadFailed",
                    fallback="模型无法安全加载，请检查运行环境或重新准备模型。",
                ) from safe_error
            after_load = os.fstat(model_file.fileno())
            if any(getattr(after_hash, field) != getattr(after_load, field) for field in fingerprint_fields):
                raise TranslatableRuntimeError(
                    "error.modelIntegrityFailed",
                    fallback=f"模型文件完整性校验失败：{label}",
                    filename=label,
                )
            return loaded
    except OSError as exc:
        raise TranslatableRuntimeError(
            "error.modelIntegrityFailed",
            fallback=f"模型文件完整性校验失败：{label}",
            filename=label,
        ) from exc


def state_dict_from_loaded_object(loaded: object) -> dict[str, object] | None:
    import torch
    import torch.nn as nn

    if isinstance(loaded, nn.Module):
        return loaded.state_dict()
    if not isinstance(loaded, dict):
        return None

    state = loaded
    for key in ("state_dict", "model_state_dict"):
        if key in state and isinstance(state[key], dict):
            state = state[key]
            break

    if not all(isinstance(key, str) for key in state.keys()):
        return None

    cleaned: dict[str, object] = {}
    for key, value in state.items():
        if not torch.is_tensor(value):
            continue
        cleaned_key = key
        for prefix in ("module.", "model."):
            if cleaned_key.startswith(prefix):
                cleaned_key = cleaned_key[len(prefix) :]
        cleaned[cleaned_key] = value

    return cleaned


def build_aesthetic_scorer(backbone: object) -> object:
    import torch
    import torch.nn as nn

    class AestheticScorer(nn.Module):
        """CLIP vision backbone plus seven linear aesthetic scoring heads."""

        def __init__(self, vision_backbone: object):
            super().__init__()
            self.backbone = vision_backbone
            hidden_dim = vision_backbone.config.hidden_size
            self.aesthetic_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.quality_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.composition_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.light_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.color_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.dof_head = nn.Sequential(nn.Linear(hidden_dim, 1))
            self.content_head = nn.Sequential(nn.Linear(hidden_dim, 1))

        def forward(self, pixel_values: torch.Tensor) -> tuple[torch.Tensor, ...]:
            features = self.backbone(pixel_values).pooler_output
            return (
                self.aesthetic_head(features),
                self.quality_head(features),
                self.composition_head(features),
                self.light_head(features),
                self.color_head(features),
                self.dof_head(features),
                self.content_head(features),
            )

    return AestheticScorer(backbone)


def score_aesthetic_image(
    path: str | Path,
    loaded_model: LoadedAestheticModel,
    *,
    score_fields: Iterable[str],
    image_opener: Callable[[str | Path], object],
) -> dict[str, float]:
    import torch

    image = image_opener(path)
    inputs = loaded_model.processor(images=image, return_tensors="pt")
    pixel_values = inputs["pixel_values"].to(loaded_model.device)

    with torch.no_grad():
        outputs = loaded_model.model(pixel_values)

    values = aesthetic_output_values(outputs)
    fields = list(score_fields)
    if len(values) < len(fields):
        raise RuntimeError(f"模型输出维度不足：expected {len(fields)}, got {len(values)}")

    return {field: float(value) for field, value in zip(fields, values)}


def aesthetic_output_values(outputs: object) -> list[float]:
    import torch

    if torch.is_tensor(outputs):
        return [float(value) for value in outputs.detach().cpu().reshape(-1).tolist()]
    return [float(tensor.detach().cpu().reshape(-1)[0].item()) for tensor in outputs]


def torch_feature_tensor(features: object) -> object:
    import torch

    if torch.is_tensor(features):
        return features

    for attribute in ("image_embeds", "text_embeds", "pooler_output"):
        value = getattr(features, attribute, None)
        if torch.is_tensor(value):
            return value

    if isinstance(features, (tuple, list)):
        for value in features:
            if torch.is_tensor(value) and value.ndim >= 2:
                return value

    last_hidden_state = getattr(features, "last_hidden_state", None)
    if torch.is_tensor(last_hidden_state):
        return last_hidden_state.mean(dim=1)

    raise TypeError(f"无法从模型输出中提取特征张量：{type(features).__name__}")


def normalize_torch_features(features: object) -> object:
    import torch

    tensor = torch_feature_tensor(features)
    return tensor / torch.linalg.vector_norm(tensor, dim=-1, keepdim=True).clamp_min(1e-12)


def score_clip_reference_image(
    path: str | Path,
    loaded_model: LoadedClipReferenceModel,
    *,
    image_opener: Callable[[str | Path], object],
    clamp_score: Callable[[float], float],
) -> dict[str, float]:
    import torch

    image = image_opener(path)
    inputs = loaded_model.processor(images=image, return_tensors="pt")
    pixel_values = inputs["pixel_values"].to(loaded_model.device)

    with torch.no_grad():
        image_features = loaded_model.model.get_image_features(pixel_values=pixel_values)
        image_features = normalize_torch_features(image_features)

    scores: dict[str, float] = {}
    for field, text_features in loaded_model.text_features.items():
        logits = CLIP_LOGIT_SCALE * image_features @ text_features.T
        probability = torch.softmax(logits, dim=-1)[0, 0].item()
        scores[field] = clamp_score(probability * CLIP_SCORE_SCALE)
    return scores
