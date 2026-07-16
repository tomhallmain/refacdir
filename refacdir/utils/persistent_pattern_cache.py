"""
Disk-backed memoization for filename-classification functions (``is_id``,
``is_id_filename``, etc.) so cached results survive across app sessions —
``functools.lru_cache`` alone only lasts for one process's lifetime.

Deliberately separate from ``AppInfoCache``: this data can grow much larger
than the small settings ``AppInfoCache`` holds, and re-encrypting/rewriting
that whole blob on every save would slow down unrelated UI settings
persistence. It's still encrypted, though — filenames can incidentally carry
sensitive information — via the same symmetric passphrase-based encryptor
used elsewhere in ``refacdir.utils.encryptor``, keyed off the same
(service, app identifier) pair as ``AppInfoCache``. Flushed explicitly rather
than on every write (batch renamer scans can test thousands of files per run).
"""

import functools
import json
import os
import threading

from refacdir.utils.cache_paths import refacdir_cache_dir
from refacdir.utils.constants import AppInfo
from refacdir.utils.encryptor import (
    PassphraseManager,
    symmetric_decrypt_data_from_file,
    symmetric_encrypt_data_to_file,
)
from refacdir.utils.logger import setup_logger

logger = setup_logger("persistent_pattern_cache")

_CACHE_FILE = "filename_pattern_cache.enc"
# Absolute, cwd-independent default location — sibling to AppInfoCache.CACHE_LOC.
# NOT resolve_cache_file()'s bare-filename fallback: FileRenamer chdirs into a
# renamer's root directory during scans and doesn't always restore it, so a
# relative path here could scatter this file into whatever user directory the
# last renamer touched instead of one stable, findable location.
_DEFAULT_CACHE_LOC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _CACHE_FILE
)
MAX_ENTRIES = 50000
_EVICT_BATCH = max(1, int(MAX_ENTRIES * 0.1))


class PersistentPatternCache:
    def __init__(self):
        self._lock = threading.RLock()
        self._cache: dict = {}
        self._dirty = False
        _override = refacdir_cache_dir()
        if _override:
            os.makedirs(_override, exist_ok=True)
            self._path = os.path.join(_override, _CACHE_FILE)
        else:
            self._path = _DEFAULT_CACHE_LOC
        self._passphrase = None
        self._load()

    @staticmethod
    def _disabled() -> bool:
        # Reuses the same test-isolation flag AppInfoCache checks, so this
        # cache never touches disk (or the keyring, for the passphrase) during
        # the test suite either.
        return bool(os.environ.get("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD"))

    def _get_passphrase(self) -> bytes:
        """Lazily fetch (and cache) the symmetric passphrase, keyring-backed like AppInfoCache's keys."""
        if self._passphrase is None:
            passphrase = PassphraseManager.get_passphrase(
                AppInfo.SERVICE_NAME, AppInfo.APP_IDENTIFIER
            )
            self._passphrase = passphrase.encode("utf-8")
        return self._passphrase

    def _load(self):
        if self._disabled():
            return
        try:
            if os.path.isfile(self._path):
                decrypted = symmetric_decrypt_data_from_file(self._path, self._get_passphrase())
                self._cache = json.loads(decrypted.decode("utf-8"))
        except Exception as exc:
            logger.warning(f"Could not load persistent pattern cache, starting fresh: {exc}")
            self._cache = {}

    def get(self, key: str):
        """Returns the cached value, or ``None`` on a miss (callers here never cache None itself)."""
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value) -> None:
        with self._lock:
            if key in self._cache:
                return
            self._cache[key] = value
            self._dirty = True
            if len(self._cache) > MAX_ENTRIES:
                self._evict_oldest(_EVICT_BATCH)

    def _evict_oldest(self, count: int) -> None:
        # Dicts preserve insertion order; oldest-first is a reasonable proxy for
        # "least likely to be looked up again" without tracking access times.
        for _ in range(count):
            try:
                oldest_key = next(iter(self._cache))
            except StopIteration:
                break
            del self._cache[oldest_key]

    def flush(self) -> None:
        """Persist accumulated entries to disk (encrypted). No-op if nothing changed since the last flush."""
        with self._lock:
            if not self._dirty or self._disabled():
                return
            try:
                tmp_path = f"{self._path}.tmp"
                data = json.dumps(self._cache).encode("utf-8")
                symmetric_encrypt_data_to_file(data, tmp_path, self._get_passphrase())
                os.replace(tmp_path, self._path)
                self._dirty = False
            except Exception as exc:
                logger.warning(f"Could not flush persistent pattern cache: {exc}")


persistent_pattern_cache = PersistentPatternCache()


def persistent_cache(func):
    """
    Memoize a pure, boolean-returning function across sessions via ``persistent_pattern_cache``.

    Like ``functools.lru_cache``, but survives process restarts. Callers (e.g.
    a batch job finishing) must call ``persistent_pattern_cache.flush()`` to
    write newly computed entries to disk — this decorator only updates the
    in-memory cache, to avoid a disk write on every call during a large scan.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = f"{func.__module__}.{func.__qualname__}:{args!r}:{sorted(kwargs.items())!r}"
        cached = persistent_pattern_cache.get(key)
        if cached is not None:
            return cached
        result = func(*args, **kwargs)
        persistent_pattern_cache.set(key, result)
        return result
    return wrapper
