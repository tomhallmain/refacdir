"""Resolve on-disk cache locations (overridable for tests)."""

import os

from refacdir.utils.app_paths import user_cache_dir


def refacdir_cache_dir() -> str:
    """``REFACDIR_CACHE_DIR`` when set, else the per-user cache directory. Created if missing."""
    override = os.environ.get("REFACDIR_CACHE_DIR")
    if not override:
        return user_cache_dir()
    os.makedirs(override, exist_ok=True)
    return override


def resolve_cache_file(filename: str) -> str:
    """Return an absolute path for a cache file under the cache dir."""
    return os.path.join(refacdir_cache_dir(), filename)
