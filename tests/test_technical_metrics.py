from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from culvia.technical_metrics import (
    analyze_technical_quality,
    exposure_score,
    sharpness_score,
    technical_analysis_array,
)


def make_checkerboard(path: Path, size: int = 128, block: int = 8) -> Path:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            value = 245 if ((x // block) + (y // block)) % 2 == 0 else 20
            pixels[x, y] = (value, value, value)
    image.save(path, format="JPEG", quality=95)
    return path


class TechnicalMetricsTests(unittest.TestCase):
    def test_technical_analysis_array_returns_rgb_and_luminance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mid.jpg"
            Image.new("RGB", (64, 40), (128, 128, 128)).save(path)

            rgb, luminance = technical_analysis_array(path)

        self.assertEqual(rgb.shape[2], 3)
        self.assertEqual(luminance.shape, rgb.shape[:2])

    def test_analyze_technical_quality_returns_bounded_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_checkerboard(Path(tmp) / "sharp.jpg")

            scores = analyze_technical_quality(path)

        self.assertEqual(set(scores), {"technical_overall", "sharpness", "exposure", "contrast", "cleanliness"})
        for value in scores.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 10.0)

    def test_sharp_checkerboard_scores_sharper_than_flat_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sharp_path = make_checkerboard(Path(tmp) / "sharp.jpg")
            flat_path = Path(tmp) / "flat.jpg"
            Image.new("RGB", (128, 128), (128, 128, 128)).save(flat_path)

            _sharp_rgb, sharp_luminance = technical_analysis_array(sharp_path)
            _flat_rgb, flat_luminance = technical_analysis_array(flat_path)

        self.assertGreater(sharpness_score(sharp_luminance), sharpness_score(flat_luminance))

    def test_mid_exposure_scores_better_than_clipped_black(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mid_path = Path(tmp) / "mid.jpg"
            black_path = Path(tmp) / "black.jpg"
            Image.new("RGB", (128, 128), (118, 118, 118)).save(mid_path)
            Image.new("RGB", (128, 128), (0, 0, 0)).save(black_path)

            _mid_rgb, mid_luminance = technical_analysis_array(mid_path)
            _black_rgb, black_luminance = technical_analysis_array(black_path)

        self.assertGreater(exposure_score(mid_luminance), exposure_score(black_luminance))


if __name__ == "__main__":
    unittest.main()
