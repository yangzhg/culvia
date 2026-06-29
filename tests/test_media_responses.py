from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from culvia.media_responses import (
    accepts_json,
    image_media_response,
    thumbnail_media_response,
    unavailable_media_response,
)


class MediaResponseTests(unittest.TestCase):
    def test_accepts_json_requires_explicit_json_media_type(self) -> None:
        self.assertTrue(accepts_json("application/json"))
        self.assertTrue(accepts_json("application/problem+json; q=0.9, image/*"))
        self.assertFalse(accepts_json("application/json;q=0, image/*;q=1"))
        self.assertFalse(accepts_json("image/avif,image/webp,image/*,*/*;q=0.8"))
        self.assertFalse(accepts_json("*/*"))

    def test_unavailable_media_response_uses_route_copy(self) -> None:
        image_denied = unavailable_media_response("image", 403)
        thumb_denied = unavailable_media_response("thumbnail", 403)
        missing = unavailable_media_response("image", 404)

        self.assertEqual(image_denied.status_code, 403)
        self.assertEqual(image_denied.body, b"image access denied")
        self.assertEqual(image_denied.headers["vary"], "Accept")
        self.assertEqual(thumb_denied.body, b"thumbnail access denied")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.body, b"image not found")

    def test_unavailable_media_response_can_return_structured_api_errors(self) -> None:
        image_denied = unavailable_media_response("image", 403, wants_json=True)
        thumb_denied = unavailable_media_response("thumbnail", 403, wants_json=True)
        missing = unavailable_media_response("thumbnail", 404, wants_json=True)

        self.assertEqual(image_denied.status_code, 403)
        self.assertEqual(image_denied.media_type, "application/json")
        self.assertEqual(image_denied.headers["vary"], "Accept")
        self.assertEqual(json.loads(image_denied.body)["errorCode"], "imageAccessDenied")
        self.assertEqual(json.loads(thumb_denied.body)["errorCode"], "thumbnailAccessDenied")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(json.loads(missing.body)["errorCode"], "mediaNotFound")

    def test_image_media_response_returns_jpeg_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "photo.png"
            Image.new("RGB", (32, 32), color=(90, 120, 180)).save(image_path)

            response = image_media_response(image_path, 200, 80, wants_json=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertTrue(response.body.startswith(b"\xff\xd8"))

    def test_image_media_response_reports_generation_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_image_path = Path(temp_dir) / "broken.jpg"
            bad_image_path.write_text("not an image", encoding="utf-8")

            text_response = image_media_response(bad_image_path, 200, 120)
            json_response = image_media_response(bad_image_path, 200, 120, wants_json=True)

        self.assertEqual(text_response.status_code, 500)
        self.assertEqual(text_response.headers["vary"], "Accept")
        self.assertIn(b"image failed", text_response.body)
        self.assertEqual(json_response.status_code, 500)
        body = json.loads(json_response.body)
        self.assertEqual(body["errorCode"], "imageGenerationFailed")
        self.assertEqual(body["errorParams"]["kind"], "image")

    def test_thumbnail_media_response_reports_generation_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_image_path = Path(temp_dir) / "broken.jpg"
            bad_image_path.write_text("not an image", encoding="utf-8")

            response = thumbnail_media_response(
                bad_image_path,
                200,
                120,
                cache_dir=Path(temp_dir) / "thumbs",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["vary"], "Accept")
        self.assertIn(b"thumbnail failed", response.body)

    def test_thumbnail_media_response_can_report_generation_failures_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_image_path = Path(temp_dir) / "broken.jpg"
            bad_image_path.write_text("not an image", encoding="utf-8")

            response = thumbnail_media_response(
                bad_image_path,
                200,
                120,
                cache_dir=Path(temp_dir) / "thumbs",
                wants_json=True,
            )

        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body)
        self.assertEqual(body["errorCode"], "thumbnailGenerationFailed")
        self.assertEqual(body["errorParams"]["kind"], "thumbnail")


if __name__ == "__main__":
    unittest.main()
