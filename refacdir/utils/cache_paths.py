"""Resolve on-disk cache locations (overridable for tests)."""

import os
from typing import Optional


def refacdir_cache_dir() -> Optional[str]:
    return os.environ.get("REFACDIR_CACHE_DIR")


def resolve_cache_file(filename: str) -> str:
    """Return an absolute path for a cache file under the configured cache dir."""
    base = refacdir_cache_dir()
    if base:
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, filename)
    return filename
