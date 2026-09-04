from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

from culvia.local_model_scoring import (
    LoadedAestheticModel,
    aesthetic_output_values,
    load_torch_object,
    normalize_torch_features,
    score_aesthetic_image,
    state_dict_from_loaded_object,
    torch_feature_tensor,
)
from culvia.job_text import TranslatableRuntimeError


class FakeProcessor:
    def __call__(self, **_kwargs: object) -> dict[str, torch.Tensor]:
        return {"pixel_values": torch.ones((1, 3, 2, 2))}


class FakeAestheticModel:
    def __call__(self, _pixel_values: torch.Tensor) -> tuple[torch.Tensor, ...]:
        return (torch.tensor([[1.0]]), torch.tensor([[2.5]]), torch.tensor([[4.0]]))


class LocalModelScoringTests(unittest.TestCase):
    def test_aesthetic_output_values_accepts_tensor_and_tuple_outputs(self) -> None:
        self.assertEqual(aesthetic_output_values(torch.tensor([[1.0, 2.0, 3.0]])), [1.0, 2.0, 3.0])
        self.assertEqual(
            aesthetic_output_values((torch.tensor([[1.5]]), torch.tensor([[2.5]]))),
            [1.5, 2.5],
        )

    def test_score_aesthetic_image_maps_outputs_to_fields(self) -> None:
        loaded = LoadedAestheticModel(processor=FakeProcessor(), model=FakeAestheticModel(), device="cpu")

        scores = score_aesthetic_image(
            "/tmp/image.jpg",
            loaded,
            score_fields=("overall", "quality", "composition"),
            image_opener=lambda _path: object(),
        )

        self.assertEqual(scores, {"overall": 1.0, "quality": 2.5, "composition": 4.0})

    def test_torch_feature_tensor_extracts_common_transformer_outputs(self) -> None:
        tensor = torch.ones((2, 3))

        self.assertIs(torch_feature_tensor(tensor), tensor)
        self.assertIs(torch_feature_tensor(SimpleNamespace(image_embeds=tensor)), tensor)
        self.assertIs(torch_feature_tensor((torch.ones(1), tensor)), tensor)

        hidden = torch.ones((2, 4, 3))
        pooled = torch_feature_tensor(SimpleNamespace(last_hidden_state=hidden))
        self.assertEqual(tuple(pooled.shape), (2, 3))

    def test_normalize_torch_features_returns_unit_vectors(self) -> None:
        normalized = normalize_torch_features(SimpleNamespace(pooler_output=torch.ones((2, 3))))

        norms = torch.linalg.vector_norm(normalized, dim=-1)
        self.assertTrue(torch.allclose(norms, torch.ones_like(norms)))

    def test_state_dict_from_loaded_object_strips_common_prefixes(self) -> None:
        state = state_dict_from_loaded_object(
            {
                "state_dict": {
                    "module.backbone.weight": torch.ones(1),
                    "model.head.bias": torch.zeros(1),
                    "metadata": "ignored",
                }
            }
        )

        self.assertEqual(set(state or {}), {"backbone.weight", "head.bias"})

    def test_torch_loader_uses_restricted_weights_only_mode(self) -> None:
        payload = b"audited model bytes"
        loaded_object = object()
        observed: dict[str, object] = {}

        def safe_load(model_file: object, **kwargs: object) -> object:
            observed["payload"] = model_file.read()
            observed["kwargs"] = kwargs
            return loaded_object

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(payload)
            with (
                patch("torch.load", side_effect=safe_load) as torch_load,
                patch(
                    "culvia.local_model_scoring.MODEL_PT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                loaded = load_torch_object(str(model_path))

        self.assertIs(loaded, loaded_object)
        self.assertEqual(observed["payload"], payload)
        self.assertEqual(observed["kwargs"], {"map_location": "cpu", "weights_only": True})
        torch_load.assert_called_once()

    def test_torch_loader_fails_closed_when_restricted_load_fails(self) -> None:
        payload = b"audited model bytes"
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(payload)
            with (
                patch("torch.load", side_effect=RuntimeError("restricted loader rejected it")) as torch_load,
                patch(
                    "culvia.local_model_scoring.MODEL_PT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                with self.assertRaises(TranslatableRuntimeError) as caught:
                    load_torch_object(str(model_path))

        self.assertEqual(caught.exception.text, {"key": "error.modelSafeLoadFailed"})
        self.assertTrue(torch_load.call_args.args[0].closed)
        self.assertEqual(torch_load.call_args.kwargs, {"map_location": "cpu", "weights_only": True})

    def test_torch_loader_fails_closed_when_weights_only_is_unavailable(self) -> None:
        payload = b"audited model bytes"
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(payload)
            with (
                patch("torch.load", side_effect=TypeError("unknown argument")) as torch_load,
                patch(
                    "culvia.local_model_scoring.MODEL_PT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                with self.assertRaises(TranslatableRuntimeError) as caught:
                    load_torch_object(str(model_path))

        self.assertEqual(caught.exception.text, {"key": "error.modelSafeLoadFailed"})
        self.assertEqual(torch_load.call_count, 1)
        self.assertEqual(torch_load.call_args.kwargs, {"map_location": "cpu", "weights_only": True})

    def test_torch_loader_rejects_file_changed_during_deserialization(self) -> None:
        payload = b"audited model bytes"

        def mutate_file(model_file: object, **_kwargs: object) -> object:
            Path(model_file.name).write_bytes(b"changed while loading")
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(payload)
            with (
                patch("torch.load", side_effect=mutate_file) as torch_load,
                patch(
                    "culvia.local_model_scoring.MODEL_PT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                with self.assertRaises(TranslatableRuntimeError) as caught:
                    load_torch_object(str(model_path))

        self.assertEqual(caught.exception.text["key"], "error.modelIntegrityFailed")
        torch_load.assert_called_once()

    def test_torch_loader_rejects_hash_mismatch_before_deserialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"tampered")
            with patch("torch.load") as torch_load:
                with self.assertRaises(TranslatableRuntimeError) as caught:
                    load_torch_object(str(model_path))

        self.assertEqual(caught.exception.text["key"], "error.modelIntegrityFailed")
        torch_load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
