from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


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


def load_torch_object(model_path: str) -> object:
    import torch

    try:
        return torch.load(model_path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(model_path, map_location="cpu")
    except Exception:
        return torch.load(model_path, map_location="cpu", weights_only=False)


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
        logits = 100.0 * image_features @ text_features.T
        probability = torch.softmax(logits, dim=-1)[0, 0].item()
        scores[field] = clamp_score(probability * 10.0)
    return scores
