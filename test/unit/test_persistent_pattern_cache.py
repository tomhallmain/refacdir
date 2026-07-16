"""
Unit tests for ``PersistentPatternCache`` / ``persistent_cache`` — cross-session
(disk-backed, encrypted) memoization for filename-classification functions like
``is_id``.

``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` is set for the whole test session (see
``test/conftest.py``) so nothing here touches disk by default; tests that need
to exercise real persistence explicitly unset it, same convention as AppInfoCache.

The passphrase behind the encryption is normally keyring-backed (same as
AppInfoCache's keys). No test in this suite exercises the real OS keyring — that
convention already holds for AppInfoCache itself (nothing here unsets the disable
flag without also stubbing ``PassphraseManager.get_passphrase``), since keyring
availability varies across dev/CI machines. The real ``SymmetricEncryptor``
encrypt/decrypt round trip is still exercised for real, just with a fixed
test-only passphrase instead of one fetched from the OS keyring.

Note: the module-level ``persistent_pattern_cache`` singleton is constructed once
at import time, before any per-test ``REFACDIR_CACHE_DIR`` override takes effect.
Tests that simulate a session restart explicitly swap in a fresh, freshly-pathed
instance via monkeypatch rather than relying on that singleton directly.
"""

from __future__ import annotations

import pytest

import refacdir.utils.persistent_pattern_cache as pattern_cache_module
from refacdir.utils.persistent_pattern_cache import PersistentPatternCache, persistent_cache


@pytest.fixture
def enable_real_persistence(tmp_path, monkeypatch):
    """
    Unset the test-isolation flag, point the cache dir at a fresh tmp_path, and
    stub the passphrase lookup so tests never touch the real OS keyring while
    still exercising the real encrypt/decrypt file round trip.
    """
    monkeypatch.delenv("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", raising=False)
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        pattern_cache_module.PassphraseManager,
        "get_passphrase",
        staticmethod(lambda *args, **kwargs: "test-only-passphrase"),
    )
    return tmp_path


def test_disabled_by_default_never_touches_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))

    cache = PersistentPatternCache()
    cache.set("k", True)
    cache.flush()

    # Don't assert tmp_path is entirely empty: the autouse isolated_app_singletons
    # fixture (test/conftest.py) creates its own cache/configs subdirs there for
    # unrelated reasons. Only this cache's own file must be absent.
    assert not (tmp_path / "filename_pattern_cache.enc").exists()


def test_get_set_roundtrip_in_memory(enable_real_persistence):
    cache = PersistentPatternCache()
    assert cache.get("missing") is None
    cache.set("k", True)
    assert cache.get("k") is True


def test_set_does_not_overwrite_an_existing_key(enable_real_persistence):
    cache = PersistentPatternCache()
    cache.set("k", True)
    cache.set("k", False)  # should be ignored; first write wins
    assert cache.get("k") is True


def test_cache_file_on_disk_is_not_plaintext(enable_real_persistence, tmp_path):
    """The whole point of this change: the file must actually be encrypted."""
    cache = PersistentPatternCache()
    cache.set("report.pdf", False)
    cache.flush()

    cache_files = list(tmp_path.glob("filename_pattern_cache.enc"))
    assert len(cache_files) == 1
    raw_bytes = cache_files[0].read_bytes()
    assert b"report.pdf" not in raw_bytes
    # Plain JSON would start with '{'; encrypted output must not parse as JSON at all.
    with pytest.raises(Exception):
        import json

        json.loads(raw_bytes.decode("utf-8"))


def test_flush_then_fresh_instance_sees_persisted_entries(enable_real_persistence):
    """The core requirement: results must survive across sessions (process restarts)."""
    first_session = PersistentPatternCache()
    first_session.set("report.pdf", False)
    first_session.set("a1b2c3d4e5f6a1b2c3d4e5", True)
    first_session.flush()

    second_session = PersistentPatternCache()
    assert second_session.get("report.pdf") is False
    assert second_session.get("a1b2c3d4e5f6a1b2c3d4e5") is True


def test_flush_is_a_noop_when_nothing_changed(enable_real_persistence, tmp_path):
    cache = PersistentPatternCache()
    cache.flush()  # nothing set yet
    assert not any(tmp_path.glob("filename_pattern_cache.enc"))


def test_eviction_drops_oldest_entries_once_over_capacity(enable_real_persistence, monkeypatch):
    monkeypatch.setattr(pattern_cache_module, "MAX_ENTRIES", 5)
    monkeypatch.setattr(pattern_cache_module, "_EVICT_BATCH", 2)

    cache = PersistentPatternCache()
    for i in range(6):
        cache.set(f"key{i}", i)

    # Oldest two (key0, key1) should have been evicted once the cache passed capacity.
    assert cache.get("key0") is None
    assert cache.get("key1") is None
    assert cache.get("key5") == 5


def test_persistent_cache_decorator_memoizes_within_a_session(enable_real_persistence):
    calls = []

    @persistent_cache
    def classify(value):
        calls.append(value)
        return value == "id-like"

    assert classify("id-like") is True
    assert classify("id-like") is True
    assert calls == ["id-like"]  # second call was served from cache, not recomputed


def test_persistent_cache_decorator_survives_a_simulated_restart(enable_real_persistence, monkeypatch):
    calls = []

    @persistent_cache
    def classify(value):
        calls.append(value)
        return value == "id-like"

    # First "session": swap in an instance whose path matches this test's tmp_path
    # (the module singleton was constructed at import time, before that was set).
    monkeypatch.setattr(pattern_cache_module, "persistent_pattern_cache", PersistentPatternCache())

    assert classify("id-like") is True
    pattern_cache_module.persistent_pattern_cache.flush()

    # Second "session": a fresh instance loaded from the same on-disk file.
    monkeypatch.setattr(pattern_cache_module, "persistent_pattern_cache", PersistentPatternCache())

    assert classify("id-like") is True
    assert calls == ["id-like"]  # still only one real computation, across the "restart"


def test_is_id_result_persists_across_a_simulated_restart(enable_real_persistence, monkeypatch):
    """Integration check with the actual production consumer of this cache."""
    import custom_file_name_search_funcs as funcs

    monkeypatch.setattr(pattern_cache_module, "persistent_pattern_cache", PersistentPatternCache())

    test_string = "a1b2c3d4e5f6a1b2c3d4e5"
    assert funcs.is_id(test_string) is True
    pattern_cache_module.persistent_pattern_cache.flush()

    fresh = PersistentPatternCache()
    monkeypatch.setattr(pattern_cache_module, "persistent_pattern_cache", fresh)

    # The result must already be present in the freshly-loaded instance, proving
    # it survived the "restart" without is_id needing to run again.
    matching_entries = [v for k, v in fresh._cache.items() if test_string in k]
    assert matching_entries == [True]
