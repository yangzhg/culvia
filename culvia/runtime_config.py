from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from culvia import settings

DEFAULT_THUMBNAIL_MAX_SIZE = 420
DEFAULT_THUMBNAIL_CACHE_MAX_BYTES = settings.DEFAULT_THUMBNAIL_CACHE_MAX_BYTES
DEFAULT_THUMBNAIL_CACHE_MAX_FILES = settings.DEFAULT_THUMBNAIL_CACHE_MAX_FILES


@dataclass(frozen=True)
class RuntimeConfig:
    web_dir: Path
    upload_cache_dir: Path
    thumbnail_cache_dir: Path
    default_cache_path: str
    default_photo_dirs: tuple[str, ...]
    thumbnail_max_size: int = DEFAULT_THUMBNAIL_MAX_SIZE
    thumbnail_cache_max_bytes: int = DEFAULT_THUMBNAIL_CACHE_MAX_BYTES
    thumbnail_cache_max_files: int = DEFAULT_THUMBNAIL_CACHE_MAX_FILES
    export_receipts_path: Path | None = None

    def __post_init__(self) -> None:
        if self.thumbnail_cache_max_bytes < 0:
            raise ValueError("Thumbnail cache byte limit cannot be negative")
        if self.thumbnail_cache_max_files < 0:
            raise ValueError("Thumbnail cache file limit cannot be negative")

    @property
    def resolved_export_receipts_path(self) -> Path:
        return self.export_receipts_path or Path(self.default_cache_path).parent / "culvia_export_receipts.sqlite"

    @classmethod
    def from_settings(cls) -> "RuntimeConfig":
        return cls(
            web_dir=settings.resolve_web_dir(),
            upload_cache_dir=settings.upload_cache_dir(),
            thumbnail_cache_dir=settings.thumbnail_cache_dir(),
            default_cache_path=settings.default_cache_path(),
            default_photo_dirs=tuple(settings.default_photo_dirs()),
            thumbnail_cache_max_bytes=settings.thumbnail_cache_max_bytes(),
            thumbnail_cache_max_files=settings.thumbnail_cache_max_files(),
            export_receipts_path=settings.export_receipts_path(),
        )

    def with_paths(
        self,
        *,
        web_dir: str | Path | None = None,
        upload_cache_dir: str | Path | None = None,
        thumbnail_cache_dir: str | Path | None = None,
        default_cache_path: str | Path | None = None,
        default_photo_dirs: tuple[str, ...] | list[str] | None = None,
        thumbnail_max_size: int | None = None,
        thumbnail_cache_max_bytes: int | None = None,
        thumbnail_cache_max_files: int | None = None,
        export_receipts_path: str | Path | None = None,
    ) -> "RuntimeConfig":
        return RuntimeConfig(
            web_dir=Path(web_dir) if web_dir is not None else self.web_dir,
            upload_cache_dir=Path(upload_cache_dir) if upload_cache_dir is not None else self.upload_cache_dir,
            thumbnail_cache_dir=Path(thumbnail_cache_dir)
            if thumbnail_cache_dir is not None
            else self.thumbnail_cache_dir,
            default_cache_path=str(default_cache_path) if default_cache_path is not None else self.default_cache_path,
            default_photo_dirs=tuple(default_photo_dirs) if default_photo_dirs is not None else self.default_photo_dirs,
            thumbnail_max_size=thumbnail_max_size if thumbnail_max_size is not None else self.thumbnail_max_size,
            thumbnail_cache_max_bytes=thumbnail_cache_max_bytes
            if thumbnail_cache_max_bytes is not None
            else self.thumbnail_cache_max_bytes,
            thumbnail_cache_max_files=thumbnail_cache_max_files
            if thumbnail_cache_max_files is not None
            else self.thumbnail_cache_max_files,
            export_receipts_path=Path(export_receipts_path)
            if export_receipts_path is not None
            else self.export_receipts_path,
        )
