from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import generate_app_icons


class AppIconGenerationTests(unittest.TestCase):
    def test_splash_svg_markup_uses_frameless_brand_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "brand.svg"
            source.write_text(
                """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Culvia">
  <title>Culvia</title>
  <defs>
    <linearGradient id="culvia-bg"><stop stop-color="#111317"/></linearGradient>
    <linearGradient id="culvia-ring"><stop stop-color="#65d8c9"/></linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="url(#culvia-bg)"/>
  <circle cx="32" cy="32" r="20.5" fill="none" stroke="url(#culvia-ring)"/>
</svg>
""".strip(),
                encoding="utf-8",
            )

            markup = generate_app_icons.splash_svg_markup(source)

        self.assertIn('<svg id="mark" xmlns="http://www.w3.org/2000/svg"', markup)
        self.assertIn("<title>Culvia</title>", markup)
        self.assertIn('id="culvia-ring"', markup)
        self.assertIn('<circle cx="32" cy="32"', markup)
        self.assertNotIn('id="culvia-bg"', markup)
        self.assertNotIn("<rect", markup)

    def test_sync_splash_icon_replaces_existing_splash_svg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "brand.svg"
            splash_html = Path(tmp) / "splash.html"
            source.write_text(
                """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Culvia">
  <path d="M1 2 3 4"/>
</svg>
""".strip(),
                encoding="utf-8",
            )
            splash_html.write_text(
                """
<!doctype html>
<html>
  <svg id="mark" viewBox="0 0 64 64">
    <path d="old"/>
  </svg>
</html>
""".strip(),
                encoding="utf-8",
            )

            generate_app_icons.sync_splash_icon(source, splash_html)
            updated = splash_html.read_text(encoding="utf-8")

        self.assertIn('<svg id="mark" xmlns="http://www.w3.org/2000/svg"', updated)
        self.assertIn('<path d="M1 2 3 4"/>', updated)
        self.assertNotIn('d="old"', updated)


if __name__ == "__main__":
    unittest.main()
