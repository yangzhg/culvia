from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import torch

from culvia import model_loaders
from culvia.local_model_scoring import LoadedAestheticModel, LoadedClipReferenceModel


class FakeImageProcessor:
    @classmethod
    def from_pretrained(cls, _path: str, local_files_only: bool = True) -> str:
        return "image-processor"


class FakeTokenizer:
    @classmethod
    def from_pretrained(cls, _path: str, local_files_only: bool = True) -> str:
        return "tokenizer"


class FakeProcessor:
    def __init__(self, image_processor: object | None = None, tokenizer: object | None = None) -> None:
        self.image_processor = image_processor
        self.tokenizer = tokenizer

    @classmethod
    def from_pretrained(cls, _path: str, local_files_only: bool = True) -> "FakeProcessor":
        return cls(image_processor="clip-image-processor", tokenizer="clip-tokenizer")

    def __call__(self, **_kwargs: object) -> dict[str, torch.Tensor]:
        return {"input_ids": torch.ones((2, 3))}


class FakeVisionConfig:
    pass


class FakeVisionModel:
    def __init__(self, _config: object) -> None:
        self.config = types.SimpleNamespace(hidden_size=3)


class FakeWrappedVisionModel:
    last_backbone: object | None = None

    def __init__(self, _config: object) -> None:
        self.vision_model = types.SimpleNamespace(config=types.SimpleNamespace(hidden_size=3))
        type(self).last_backbone = self.vision_model


class FakeClipModel:
    last_use_safetensors: bool | None = None

    @classmethod
    def from_pretrained(
        cls,
        _path: str,
        local_files_only: bool = True,
        use_safetensors: bool = False,
    ) -> "FakeClipModel":
        cls.last_use_safetensors = use_safetensors
        return cls()

    def __init__(self) -> None:
        self.device = ""
        self.did_eval = False

    def to(self, device: str) -> None:
        self.device = device

    def eval(self) -> None:
        self.did_eval = True

    def get_text_features(self, **_kwargs: object) -> torch.Tensor:
        return torch.ones((2, 3))


class FallbackModel:
    def __init__(self) -> None:
        self.devices: list[str] = []

    def to(self, device: str) -> None:
        self.devices.append(device)
        if device == "mps":
            raise RuntimeError("no mps")


def fake_transformers_module() -> types.ModuleType:
    module = types.ModuleType("transformers")
    module.CLIPImageProcessor = FakeImageProcessor
    module.CLIPProcessor = FakeProcessor
    module.CLIPTokenizerFast = FakeTokenizer
    module.CLIPVisionConfig = FakeVisionConfig
    module.CLIPVisionModel = FakeVisionModel
    module.CLIPModel = FakeClipModel
    return module


class ModelLoaderTests(unittest.TestCase):
    def test_get_device_returns_supported_device_label(self) -> None:
        self.assertIn(model_loaders.get_device(), {"cpu", "mps"})

    def test_move_model_to_device_falls_back_to_cpu(self) -> None:
        model = FallbackModel()

        selected = model_loaders.move_model_to_device(model, "mps")

        self.assertEqual(selected, "cpu")
        self.assertEqual(model.devices, ["mps", "cpu"])

    def test_load_model_uses_prepared_assets_and_returns_loaded_aesthetic_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"model")
            loaded_model = torch.nn.Identity()
            with (
                patch.dict(sys.modules, {"transformers": fake_transformers_module()}),
                patch("culvia.model_loaders.ensure_model_files") as ensure_files,
                patch(
                    "culvia.model_loaders.get_model_assets_dir",
                    return_value=Path(tmp),
                ),
                patch(
                    "culvia.model_loaders.get_model_cache_status",
                    return_value={"model_file": str(model_path)},
                ),
                patch(
                    "culvia.model_loaders.load_torch_object",
                    return_value=loaded_model,
                ) as load_object,
            ):
                loaded = model_loaders.load_model("cpu")

        self.assertIsInstance(loaded, LoadedAestheticModel)
        self.assertIs(loaded.model, loaded_model)
        self.assertEqual(loaded.device, "cpu")
        ensure_files.assert_called_once()
        load_object.assert_called_once_with(str(model_path))

    def test_load_model_accepts_transformers_four_wrapped_vision_backbone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"model")
            transformers_module = fake_transformers_module()
            transformers_module.CLIPVisionModel = FakeWrappedVisionModel
            scorer = Mock()
            with (
                patch.dict(sys.modules, {"transformers": transformers_module}),
                patch("culvia.model_loaders.ensure_model_files"),
                patch("culvia.model_loaders.get_model_assets_dir", return_value=Path(tmp)),
                patch(
                    "culvia.model_loaders.get_model_cache_status",
                    return_value={"model_file": str(model_path)},
                ),
                patch(
                    "culvia.model_loaders.load_torch_object",
                    return_value={"backbone.weight": torch.ones(1)},
                ),
                patch("culvia.model_loaders.build_aesthetic_scorer", return_value=scorer) as build_scorer,
            ):
                loaded = model_loaders.load_model("cpu")

        build_scorer.assert_called_once_with(FakeWrappedVisionModel.last_backbone)
        state_dict = scorer.load_state_dict.call_args.args[0]
        self.assertEqual(set(state_dict), {"backbone.weight"})
        self.assertTrue(torch.equal(state_dict["backbone.weight"], torch.ones(1)))
        self.assertEqual(scorer.load_state_dict.call_args.kwargs, {"strict": True})
        self.assertIs(loaded.model, scorer)

    def test_load_clip_reference_model_precomputes_prompt_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(sys.modules, {"transformers": fake_transformers_module()}),
                patch("culvia.model_loaders.ensure_clip_reference_model_files") as ensure_files,
                patch(
                    "culvia.model_loaders.get_clip_reference_cache_status",
                    return_value={"snapshot_path": tmp},
                ),
                patch("culvia.model_loaders.verify_file_sha256") as verify_weight,
            ):
                loaded = model_loaders.load_clip_reference_model("cpu")

        self.assertIsInstance(loaded, LoadedClipReferenceModel)
        self.assertEqual(set(loaded.text_features), set(model_loaders.CLIP_PROMPT_PAIRS))
        self.assertEqual(loaded.device, "cpu")
        ensure_files.assert_called_once()
        self.assertTrue(FakeClipModel.last_use_safetensors)
        verify_weight.assert_called_once_with(
            Path(tmp) / model_loaders.CLIP_REFERENCE_WEIGHT_FILENAME,
            model_loaders.CLIP_REFERENCE_WEIGHT_SHA256,
            filename=model_loaders.CLIP_REFERENCE_WEIGHT_FILENAME,
            revision=model_loaders.CLIP_REFERENCE_MODEL_REVISION,
        )


if __name__ == "__main__":
    unittest.main()
