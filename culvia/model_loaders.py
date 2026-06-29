from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download

from culvia.local_model_scoring import (
    CLIP_PROMPT_PAIRS,
    LoadedAestheticModel,
    LoadedClipReferenceModel,
    build_aesthetic_scorer,
    load_torch_object,
    normalize_torch_features,
    state_dict_from_loaded_object,
)
from culvia.model_files import (
    CLIP_REFERENCE_MODEL_ID,
    MODEL_ID,
    ensure_clip_reference_model_files,
    ensure_model_files,
    get_app_model_path,
    get_clip_reference_cache_status,
    get_model_assets_dir,
    sanitize_proxy_env_for_httpx,
)


def get_device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def move_model_to_device(model: object, device: str) -> str:
    try:
        model.to(device)
        return device
    except Exception:
        model.to("cpu")
        return "cpu"


def load_model(device: str | None = None) -> LoadedAestheticModel:
    import torch.nn as nn
    from transformers import CLIPImageProcessor, CLIPProcessor, CLIPTokenizerFast, CLIPVisionConfig, CLIPVisionModel

    sanitize_proxy_env_for_httpx()
    ensure_model_files()
    selected_device = device or get_device()
    model_assets_dir = get_model_assets_dir()
    image_processor = CLIPImageProcessor.from_pretrained(str(model_assets_dir), local_files_only=True)
    tokenizer = CLIPTokenizerFast.from_pretrained(str(model_assets_dir), local_files_only=True)
    processor = CLIPProcessor(image_processor=image_processor, tokenizer=tokenizer)
    app_model_path = get_app_model_path()
    if app_model_path.exists():
        model_path = str(app_model_path)
    else:
        model_path = hf_hub_download(repo_id=MODEL_ID, filename="model.pt", local_files_only=True)

    loaded = load_torch_object(model_path)
    if isinstance(loaded, nn.Module):
        model = loaded
    else:
        state_dict = state_dict_from_loaded_object(loaded)
        if state_dict is None:
            raise RuntimeError("无法识别 model.pt 的格式。")

        backbone = CLIPVisionModel(CLIPVisionConfig())
        model = build_aesthetic_scorer(backbone)
        try:
            model.load_state_dict(state_dict, strict=True)
        except RuntimeError as exc:
            missing = ", ".join(exc.args[:1])
            raise RuntimeError(f"加载模型权重失败：{missing}") from exc

    selected_device = move_model_to_device(model, selected_device)
    model.eval()
    return LoadedAestheticModel(processor=processor, model=model, device=selected_device)


def load_clip_reference_model(device: str | None = None) -> LoadedClipReferenceModel:
    import torch
    from transformers import CLIPModel, CLIPProcessor

    sanitize_proxy_env_for_httpx()
    ensure_clip_reference_model_files()
    selected_device = device or get_device()
    status = get_clip_reference_cache_status()
    snapshot_path = str(status.get("snapshot_path") or "")
    if not snapshot_path:
        raise RuntimeError("CLIP 参考模型配置文件未准备好，请先完成模型准备。")
    model_assets_dir = Path(snapshot_path)
    processor = CLIPProcessor.from_pretrained(str(model_assets_dir), local_files_only=True)
    model = CLIPModel.from_pretrained(str(model_assets_dir), local_files_only=True, use_safetensors=False)
    selected_device = move_model_to_device(model, selected_device)
    model.eval()

    text_features: dict[str, object] = {}
    with torch.no_grad():
        for field, prompts in CLIP_PROMPT_PAIRS.items():
            inputs = processor(text=list(prompts), return_tensors="pt", padding=True)
            inputs = {key: value.to(selected_device) for key, value in inputs.items()}
            features = model.get_text_features(**inputs)
            text_features[field] = normalize_torch_features(features)

    return LoadedClipReferenceModel(
        processor=processor,
        model=model,
        device=selected_device,
        text_features=text_features,
    )
