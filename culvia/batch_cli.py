from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


DESCRIPTION = "照片审美与技术评分命令行工具"

# scan_image_paths returns translatable text refs; render them for terminal output.
WARNING_TEMPLATES = {
    "warning.folderMissing": "目录不存在：{path}",
    "warning.unsupportedImage": "不是支持的图片格式：{path}",
    "warning.scanFailed": "扫描目录失败：{path} ({error})",
}


def format_warning(warning: Any) -> str:
    if isinstance(warning, dict):
        params = warning.get("params") or {}
        template = WARNING_TEMPLATES.get(str(warning.get("key")))
        if template:
            return template.format(**params)
        return " ".join([str(warning.get("key")), *map(str, params.values())]).strip()
    return str(warning)


def load_scoring_runtime() -> Any:
    from culvia import scoring

    return scoring


def help_parser(*, default_output: str = "", default_cache: str = "") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("folders", nargs="*", help="要递归扫描的照片目录。为空时使用默认目录。")
    parser.add_argument("--out", default=default_output, help="输出 CSV 路径。")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--cache",
        default=default_cache,
        help="SQLite 缓存路径，用于增量保存和复用评分结果。",
    )
    cache_group.add_argument(
        "--no-cache",
        action="store_const",
        const="",
        dest="cache",
        help="本次不读取或保存评分缓存，强制重新评分。",
    )
    return parser


def parse_args(argv: list[str] | None = None, *, runtime: Any | None = None) -> argparse.Namespace:
    scoring = runtime or load_scoring_runtime()
    return help_parser(
        default_output=scoring.DEFAULT_OUTPUT_PATH,
        default_cache=scoring.DEFAULT_CACHE_PATH,
    ).parse_args(argv)


def print_top_scores(df: Any, limit: int = 20, *, runtime: Any | None = None) -> None:
    scoring = runtime or load_scoring_runtime()
    if df.empty:
        print("没有可展示的评分结果。")
        return

    working = scoring.normalize_score_dataframe(df)
    successful = working[working["error"].eq("")].copy()
    successful["overall_0_10"] = scoring.pd.to_numeric(successful["overall_0_10"], errors="coerce")
    successful = successful.dropna(subset=["overall_0_10"]).sort_values("overall_0_10", ascending=False)

    if successful.empty:
        print("没有成功评分的图片。")
        return

    columns = [
        "overall_0_10",
        "quality_0_10",
        "composition_0_10",
        "lighting_0_10",
        "color_0_10",
        "filename",
        "path",
    ]
    print(successful.head(limit)[columns].to_string(index=False))


def refresh_cache_llm_config(cache_path: str, *, runtime: Any) -> None:
    if not cache_path:
        return
    config = runtime.load_llm_config_from_sqlite(cache_path)
    runtime.set_persisted_llm_config(config)


def main(argv: list[str] | None = None, *, runtime: Any | None = None) -> int:
    scoring = runtime or load_scoring_runtime()
    args = parse_args(argv, runtime=scoring)
    try:
        refresh_cache_llm_config(args.cache, runtime=scoring)
    except Exception:
        print("Error: failed to read LLM configuration from the cache; scoring was not started.", file=sys.stderr)
        return 2
    folders = args.folders or scoring.DEFAULT_PHOTO_DIRS

    paths, warnings = scoring.scan_image_paths(folders)
    for warning in warnings:
        print(f"Warning: {format_warning(warning)}", file=sys.stderr)

    print(f"Using device: {scoring.get_device()}")
    print(f"Scanned images: {len(paths)}")

    if not scoring.HEIF_AVAILABLE:
        print("Warning: HEIC/HEIF support is unavailable. Try: pip install pillow-heif", file=sys.stderr)

    if not paths:
        scoring.write_csv(scoring.pd.DataFrame(columns=scoring.CSV_COLUMNS), args.out)
        print(f"Saved empty CSV: {args.out}")
        return 0

    from tqdm import tqdm

    progress_bar = tqdm(total=len(paths), unit="img")

    def update_progress(done: int, total: int, path: Path, status: str) -> None:
        progress_bar.n = done
        progress_bar.set_postfix_str(f"{status}: {path.name[:40]}")
        progress_bar.refresh()

    try:
        df, _device = scoring.score_image_paths(
            paths,
            cache_path=args.cache or None,
            use_cache=bool(args.cache),
            progress_callback=update_progress,
        )
    finally:
        progress_bar.close()

    scoring.write_csv(df, args.out)
    print(f"Saved CSV: {args.out}")
    print_top_scores(df, limit=20, runtime=scoring)
    return 0
