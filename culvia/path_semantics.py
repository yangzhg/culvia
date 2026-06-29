from __future__ import annotations

import os
import sys
from pathlib import Path


def stable_path(value: str | Path) -> Path:
    """Return an absolute, normalized path without resolving symlink aliases."""
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    return Path(os.path.abspath(os.path.normpath(expanded)))


def path_identity_key(value: str | Path) -> str:
    """Return a key for equality/deduplication; never persist this as a display path."""
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    try:
        text = str(path.resolve(strict=False))
    except OSError:
        text = str(stable_path(path))
    if sys.platform == "darwin" or os.name == "nt":
        return text.casefold()
    return text


def is_same_or_child_path(child: str | Path, parent: str | Path) -> bool:
    child_key = path_identity_key(child)
    parent_key = path_identity_key(parent)
    if child_key == parent_key:
        return True
    try:
        Path(child_key).relative_to(Path(parent_key))
        return True
    except ValueError:
        return child_key.startswith(parent_key.rstrip(os.sep) + os.sep)
