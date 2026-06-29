from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Sequence

from PIL import Image
from PIL import ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "assets" / "brand" / "culvia-icon.svg"
DEFAULT_ICON_DIR = ROOT / "desktop" / "tauri" / "src-tauri" / "icons"
DEFAULT_WEB_FAVICON = ROOT / "web" / "favicon.svg"
DEFAULT_SPLASH_HTML = ROOT / "desktop" / "tauri" / "src-tauri" / "assets" / "splash.html"
PNG_OUTPUTS = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 1024,
}
ICNS_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def require_tool(name: str) -> None:
    if shutil.which(name):
        return
    raise RuntimeError(f"{name} is required to generate app icons on macOS.")


def sized_svg(source: Path, destination: Path, size: int) -> None:
    text = source.read_text(encoding="utf-8")
    if "<svg" not in text:
        raise RuntimeError(f"{source} does not look like an SVG file.")
    text = re.sub(r'\s(width|height)="[^"]*"', "", text, count=2)
    text = text.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
    destination.write_text(text, encoding="utf-8")


def run_command(command: Sequence[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(output or f"{command[0]} failed with exit code {result.returncode}.")


def render_base_png(source: Path, destination: Path, *, size: int = 1024) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sized_source = Path(tmp) / "culvia-icon.svg"
        sized_svg(source, sized_source, size)
        run_command(["sips", "-s", "format", "png", str(sized_source), "--out", str(destination)])
    apply_rounded_alpha(destination, radius=size * 16 // 64)


def resize_png(source: Path, destination: Path, size: int) -> None:
    image = Image.open(source).convert("RGBA")
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    image.resize((size, size), resampling).save(destination)


def apply_rounded_alpha(path: Path, *, radius: int) -> None:
    image = Image.open(path).convert("RGBA")
    scale = 4
    mask = Image.new("L", (image.width * scale, image.height * scale), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, mask.width, mask.height), radius=radius * scale, fill=255)
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    mask = mask.resize(image.size, resampling)
    image.putalpha(mask)
    image.save(path)


def generate_icns(base_png: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for name, size in ICNS_SIZES:
            resize_png(base_png, iconset / name, size)
        run_command(["iconutil", "-c", "icns", str(iconset), "-o", str(destination)])


def generate_ico(base_png: Path, destination: Path) -> None:
    image = Image.open(base_png).convert("RGBA")
    image.save(destination, format="ICO", sizes=ICO_SIZES)


def sync_web_favicon(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def splash_svg_markup(source: Path) -> str:
    text = source.read_text(encoding="utf-8").strip()
    match = re.search(r"<svg\b(?P<attrs>[^>]*)>(?P<body>.*)</svg>\s*$", text, re.DOTALL)
    if match is None:
        raise RuntimeError(f"{source} does not look like an SVG file.")
    attrs = re.sub(r'\s(?:id|width|height)="[^"]*"', "", match.group("attrs"))
    body = splash_mark_body(match.group("body"))
    body = "\n".join(f"  {line}" if line else line for line in body.splitlines())
    return f'<svg id="mark"{attrs}>\n{body}\n</svg>'


def splash_mark_body(svg_body: str) -> str:
    body = textwrap.dedent(svg_body.strip("\n")).strip()
    body = re.sub(
        r'\n?[ \t]*<rect\b(?=[^>]*\bwidth="64")(?=[^>]*\bheight="64")(?=[^>]*\brx="16")[^>]*/>\n?',
        "\n",
        body,
    )
    if "url(#culvia-bg)" not in body:
        body = re.sub(
            r'\n?[ \t]*<linearGradient\b(?=[^>]*\bid="culvia-bg")[\s\S]*?</linearGradient>\n?',
            "\n",
            body,
        )
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def indent_block(text: str, indent: str) -> str:
    return "\n".join(f"{indent}{line}" if line else line for line in text.splitlines())


def sync_splash_icon(source: Path, splash_html: Path) -> None:
    text = splash_html.read_text(encoding="utf-8")
    pattern = re.compile(r"(?P<indent>[ \t]*)<svg id=\"mark\"(?=[\s>]).*?</svg>", re.DOTALL)
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(f"Could not find splash SVG mark in {splash_html}.")
    replacement = indent_block(splash_svg_markup(source), match.group("indent"))
    splash_html.write_text(text[: match.start()] + replacement + text[match.end() :], encoding="utf-8")


def generate_icons(*, source: Path, icon_dir: Path, web_favicon: Path, splash_html: Path) -> dict:
    require_tool("sips")
    require_tool("iconutil")
    if not source.exists():
        raise RuntimeError(f"Missing icon source: {source}")

    sync_web_favicon(source, web_favicon)
    sync_splash_icon(source, splash_html)
    icon_dir.mkdir(parents=True, exist_ok=True)
    base_png = icon_dir / "icon.png"
    render_base_png(source, base_png)
    for name, size in PNG_OUTPUTS.items():
        destination = icon_dir / name
        if destination == base_png:
            continue
        resize_png(base_png, destination, size)
    generate_icns(base_png, icon_dir / "icon.icns")
    generate_ico(base_png, icon_dir / "icon.ico")

    outputs = [
        web_favicon,
        splash_html,
        icon_dir / "icon.icns",
        icon_dir / "icon.ico",
        *(icon_dir / name for name in PNG_OUTPUTS),
    ]
    return {
        "ok": True,
        "source": str(source),
        "iconDir": str(icon_dir),
        "webFavicon": str(web_favicon),
        "splashHtml": str(splash_html),
        "outputs": [str(path) for path in sorted(outputs)],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync Culvia web favicon, desktop app icons, and splash mark from the brand SVG."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--icon-dir", type=Path, default=DEFAULT_ICON_DIR)
    parser.add_argument("--web-favicon", type=Path, default=DEFAULT_WEB_FAVICON)
    parser.add_argument("--splash-html", type=Path, default=DEFAULT_SPLASH_HTML)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = generate_icons(
            source=args.source.resolve(),
            icon_dir=args.icon_dir.resolve(),
            web_favicon=args.web_favicon.resolve(),
            splash_html=args.splash_html.resolve(),
        )
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL app icon generation: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("OK app icon generation")
        for path in payload["outputs"]:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
