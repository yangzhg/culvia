from __future__ import annotations

import unittest
from types import SimpleNamespace

import torch

from culvia.local_model_scoring import (
    LoadedAestheticModel,
    aesthetic_output_values,
    normalize_torch_features,
    score_aesthetic_image,
    state_dict_from_loaded_object,
    torch_feature_tensor,
)


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


if __name__ == "__main__":
    unittest.main()
