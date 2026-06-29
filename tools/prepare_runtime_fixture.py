from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import pandas as pd
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from culvia import scoring
from culvia.curation import save_photo_mark
from culvia.insight_store import AnalysisInsight
from culvia.photo_scan import build_file_id


DEFAULT_COUNT = 12
DEFAULT_ROOT = (
    Path("/private/tmp/culvia-runtime-fixture")
    if Path("/private/tmp").exists()
    else Path("/tmp/culvia-runtime-fixture")
)
MARKER_NAME = ".culvia-runtime-fixture"
LONG_FILENAME_STEM = (
    "editorial-portrait-client-delivery-candidate-with-extra-long-filename-for-tooltip-and-layout-validation"
)
LONG_INSIGHT_TITLE = "Quiet portrait with a layered natural rhythm and a long editorial delivery context"
LONG_INSIGHT_SUMMARY = (
    "The frame keeps a calm subject presence while the surrounding foliage, vertical tree line, and soft foreground "
    "shape a stronger editorial mood than a simple snapshot; the long filename fixture exists to verify that review "
    "surfaces can preserve context without pushing controls out of alignment."
)
LONG_INSIGHT_EXPLANATION = (
    "The composition benefits from a stable vertical anchor and a relaxed pose, but the brighter greens compete with "
    "the face in small viewing surfaces. Keep the atmospheric environment, reduce the most saturated highlights near "
    "skin tones, and preserve enough shadow depth so the final edit still feels photographic rather than over-polished."
)
LONG_RETOUCH_SUGGESTION = (
    "Retouch: lower the saturation and luminance of the brightest greens around the face, add a restrained local "
    "contrast lift to the eyes, and avoid flattening the background because the layered foliage is part of the image mood."
)
LONG_SHOOT_SUGGESTION = (
    "Shoot: keep this distance and seated posture, then wait for a cleaner patch of background behind the shoulders "
    "or rotate slightly so the tree line supports the subject instead of visually cutting through the portrait."
)


def score_value(index: int, offset: float = 0.0) -> float:
    value = 5.4 + ((index * 0.37 + offset) % 3.9)
    return round(max(0.0, min(10.0, value)), 2)


def image_size(index: int) -> tuple[int, int]:
    sizes = (
        (1200, 800),
        (800, 1200),
        (1000, 1000),
        (1400, 780),
        (780, 1400),
        (1280, 900),
    )
    return sizes[index % len(sizes)]


def image_colors(index: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    palettes = (
        ((64, 86, 112), (214, 185, 122)),
        ((91, 111, 85), (218, 207, 176)),
        ((115, 82, 91), (194, 164, 151)),
        ((54, 69, 83), (138, 169, 188)),
        ((117, 101, 74), (216, 199, 159)),
        ((83, 70, 104), (190, 177, 214)),
    )
    return palettes[index % len(palettes)]


def create_fixture_image(path: Path, *, index: int) -> None:
    width, height = image_size(index)
    base, accent = image_colors(index)
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image, "RGBA")
    steps = 28
    for step in range(steps):
        ratio = step / max(1, steps - 1)
        color = tuple(int(base[channel] * (1 - ratio) + accent[channel] * ratio) for channel in range(3))
        y0 = int(height * step / steps)
        y1 = int(height * (step + 1) / steps)
        draw.rectangle((0, y0, width, y1), fill=(*color, 255))
    horizon = int(height * (0.42 + 0.16 * math.sin(index)))
    draw.ellipse(
        (
            int(width * 0.08),
            int(height * 0.08),
            int(width * 0.48),
            int(height * 0.58),
        ),
        fill=(255, 255, 255, 32),
    )
    draw.rectangle((0, horizon, width, height), fill=(28, 31, 34, 42))
    draw.line(
        (int(width * 0.1), int(height * 0.82), int(width * 0.88), int(height * 0.18)),
        fill=(255, 255, 255, 54),
        width=max(3, width // 180),
    )
    draw.rounded_rectangle(
        (
            int(width * 0.58),
            int(height * 0.58),
            int(width * 0.86),
            int(height * 0.88),
        ),
        radius=max(18, min(width, height) // 18),
        fill=(255, 255, 255, 36),
        outline=(255, 255, 255, 96),
        width=max(2, width // 260),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=90)


def fixture_filename(index: int) -> str:
    if index % 5 == 0:
        return f"{LONG_FILENAME_STEM}-{index + 1:02d}-retouch-v02-final-review-select.jpg"
    return f"runtime-fixture-{index + 1:02d}.jpg"


def score_record(path: Path, *, index: int) -> dict[str, object]:
    record = {column: pd.NA for column in scoring.CSV_COLUMNS}
    record.update(
        {
            "file_id": build_file_id(path),
            "path": str(path),
            "folder": str(path.parent),
            "filename": path.name,
            "error": "",
            "recommendation_0_10": score_value(index, 1.1),
            "overall_0_10": score_value(index, 0.4),
            "composition_0_10": score_value(index, 0.2),
            "lighting_0_10": score_value(index, 0.8),
            "color_0_10": score_value(index, 1.3),
            "depth_of_field_0_10": score_value(index, 0.6),
            "content_0_10": score_value(index, 1.6),
            "technical_overall_0_10": score_value(index, 1.9),
            "sharpness_0_10": score_value(index, 2.1),
            "exposure_0_10": score_value(index, 0.9),
            "contrast_0_10": score_value(index, 1.5),
            "cleanliness_0_10": score_value(index, 2.4),
            "clip_aesthetic_0_10": score_value(index, 1.2),
            "clip_iqa_overall_0_10": score_value(index, 1.7),
            "llm_review_overall_0_10": score_value(index, 2.0),
            "llm_aesthetic_overall_0_10": score_value(index, 2.3),
            "llm_technical_overall_0_10": score_value(index, 1.4),
        }
    )
    return record


def write_fixture(root: Path, *, count: int = DEFAULT_COUNT, force: bool = False) -> dict[str, object]:
    if root.exists() and force:
        assert_safe_force_root(root)
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER_NAME).write_text("culvia runtime fixture\n", encoding="utf-8")
    photo_dir = root / "photos"
    state_dir = root / "state"
    cache_dir = root / "cache"
    cache_path = state_dir / "culvia_scores.sqlite"
    photo_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    for index in range(count):
        path = photo_dir / fixture_filename(index)
        create_fixture_image(path, index=index)
        records.append(score_record(path, index=index))

    df = pd.DataFrame(records, columns=scoring.CSV_COLUMNS)
    scoring.save_cache_records(df, cache_path)
    scoring.save_analysis_insights(runtime_insights(records), cache_path)

    statuses = ("pick", "hold", "reject", "")
    colors = ("red", "yellow", "green", "blue", "purple", "")
    for index, record in enumerate(records):
        status = statuses[index % len(statuses)]
        save_photo_mark(
            cache_path,
            str(record["file_id"]),
            rating=(index % 5) + 1,
            status=status,
            color_label=colors[index % len(colors)],
            source="manual",
        )

    env = {
        "CULVIA_STATE_DIR": str(state_dir),
        "CULVIA_DATA_DIR": str(state_dir),
        "CULVIA_CACHE_DIR": str(cache_dir),
        "CULVIA_CACHE_PATH": str(cache_path),
        "CULVIA_PHOTO_DIRS": str(photo_dir),
        "CULVIA_THUMBNAIL_CACHE_DIR": str(cache_dir / "thumbnails"),
        "CULVIA_UPLOAD_DIR": str(cache_dir / "uploads"),
    }
    return {
        "ok": True,
        "root": str(root),
        "photoDir": str(photo_dir),
        "stateDir": str(state_dir),
        "cacheDir": str(cache_dir),
        "cachePath": str(cache_path),
        "count": len(records),
        "env": env,
    }


def runtime_insights(records: Sequence[dict[str, object]]) -> list[AnalysisInsight]:
    insights: list[AnalysisInsight] = []
    for index, record in enumerate(records):
        score = round(7.2 + (index % 4) * 0.2, 1)
        long_text = index % 4 == 0
        insights.append(
            AnalysisInsight(
                file_id=str(record["file_id"]),
                analyzer_key=scoring.MODEL_LLM_REVIEW,
                provider="runtime-fixture",
                model="fixture-vision-reviewer",
                model_version="fixture-vision-reviewer",
                prompt_version=scoring.LLM_REVIEW_PROMPT_VERSION,
                score=score,
                confidence=0.86,
                title=LONG_INSIGHT_TITLE if long_text else "Quiet portrait with a clean natural rhythm",
                summary=LONG_INSIGHT_SUMMARY
                if long_text
                else "The image has a calm subject presence, gentle color separation, and enough environmental context to feel editorial rather than purely documentary.",
                explanation=LONG_INSIGHT_EXPLANATION
                if long_text
                else "The composition benefits from a stable vertical anchor and soft background structure, while the brighter foliage can be held back slightly to keep attention on the face.",
                suggestions=(
                    LONG_RETOUCH_SUGGESTION
                    if long_text
                    else "Retouch: reduce green highlights around the face and add subtle local contrast to the eyes.",
                    LONG_SHOOT_SUGGESTION
                    if long_text
                    else "Shoot: keep this distance, but wait for a cleaner patch of background behind the shoulders.",
                ),
                raw_json={
                    "photography_suggestions": [
                        LONG_SHOOT_SUGGESTION
                        if long_text
                        else "Keep the relaxed seated pose and rotate slightly until the background line no longer cuts through the head.",
                        "Expose for the face first, then let the background sit a little brighter if it supports the mood.",
                    ],
                    "retouching_suggestions": [
                        LONG_RETOUCH_SUGGESTION
                        if long_text
                        else "Lower the saturation of the brightest greens and add a soft vignette from the edges.",
                        "Use selective sharpening on the eyes and leave the surrounding foliage softer.",
                    ],
                },
            )
        )
    return insights


def assert_safe_force_root(root: Path) -> None:
    resolved = root.expanduser().resolve()
    forbidden_roots = {
        Path("/").resolve(),
        Path(tempfile.gettempdir()).resolve(),
        ROOT.resolve(),
        ROOT.parent.resolve(),
        Path.home().resolve(),
    }
    private_tmp = Path("/private/tmp")
    if private_tmp.exists():
        forbidden_roots.add(private_tmp.resolve())
    if resolved in forbidden_roots:
        raise ValueError(f"Refusing to delete unsafe runtime fixture root: {resolved}")
    marker = resolved / MARKER_NAME
    if not marker.exists():
        raise ValueError(f"Refusing to delete {resolved}; missing {MARKER_NAME} marker.")


def shell_exports(env: dict[str, str]) -> str:
    return "\n".join(f"export {name}={sh_quote(value)}" for name, value in env.items())


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a deterministic photo fixture for runtime smoke tests.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--force", action="store_true", help="Delete the target fixture directory before writing.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--shell", action="store_true", help="Print shell export commands instead of JSON/text.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = write_fixture(args.root, count=max(1, args.count), force=args.force)
    if args.shell:
        print(shell_exports(payload["env"]))  # type: ignore[arg-type]
    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"OK runtime fixture: {payload['count']} photos at {payload['photoDir']}")
        print(f"Cache: {payload['cachePath']}")
        print("Use --shell for export commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
