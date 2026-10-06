"""AppInfoCache persistence: atomic writes, unreadable caches, JSON migration.

Real encryption against the per-test in-memory keyring (``isolated_keyring``).
"""

from __future__ import annotations

import json

import pytest

import refacdir.utils.app_info_cache as cache_module
from refacdir.utils.app_info_cache import AppInfoCache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", raising=False)
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    return tmp_path


def _stored_cache(cache_dir, **values):
    cache = AppInfoCache()
    for key, value in values.items():
        cache.set(key, value)
    assert cache.store() is True
    return cache_dir / "app_info_cache.enc"


def test_store_returns_false_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    assert AppInfoCache().store() is False
    assert not (tmp_path / "app_info_cache.enc").exists()


def test_round_trip(cache_dir):
    _stored_cache(cache_dir, probe="value")
    assert AppInfoCache().get("probe") == "value"


def test_failed_encryption_keeps_previous_file_and_falls_back_to_json(cache_dir, monkeypatch):
    enc = _stored_cache(cache_dir, probe="old")
    before = enc.read_bytes()

    def failing_encrypt(data, service, app, output_path):
        with open(output_path, "wb") as handle:
            handle.write(b"partial")
        raise RuntimeError("disk full")

    monkeypatch.setattr(cache_module, "encrypt_data_to_file", failing_encrypt)
    cache = AppInfoCache()
    cache.set("probe", "new")

    assert cache.store() is False
    assert enc.read_bytes() == before
    assert not list(cache_dir.glob(".app_info_cache_*.tmp"))
    saved = json.loads((cache_dir / "app_info_cache.json").read_text(encoding="utf-8"))
    assert saved["info"]["probe"] == "new"


def test_json_fallback_is_loaded_and_removed_after_encrypted_store(cache_dir, monkeypatch):
    _stored_cache(cache_dir, probe="old")
    real_encrypt = cache_module.encrypt_data_to_file

    def failing_encrypt(*args, **kwargs):
        raise RuntimeError("keyring locked")

    monkeypatch.setattr(cache_module, "encrypt_data_to_file", failing_encrypt)
    cache = AppInfoCache()
    cache.set("probe", "new")
    assert cache.store() is False

    monkeypatch.setattr(cache_module, "encrypt_data_to_file", real_encrypt)
    reloaded = AppInfoCache()  # prefers the JSON file and migrates it

    assert reloaded.get("probe") == "new"
    assert not (cache_dir / "app_info_cache.json").exists()
    assert AppInfoCache().get("probe") == "new"


def test_store_raises_when_json_fallback_fails_too(cache_dir, monkeypatch):
    def failing_encrypt(*args, **kwargs):
        raise RuntimeError("keyring locked")

    monkeypatch.setattr(cache_module, "encrypt_data_to_file", failing_encrypt)
    cache = AppInfoCache()
    # Created after load, which would otherwise try to read it. A file cannot
    # be renamed over a directory, so the fallback write fails.
    (cache_dir / "app_info_cache.json").mkdir()

    with pytest.raises(Exception, match="Error storing app info cache"):
        cache.store()
    assert not list(cache_dir.glob(".app_info_cache_*.tmp"))


def test_unreadable_cache_starts_empty_and_refuses_to_store(cache_dir):
    enc = cache_dir / "app_info_cache.enc"
    enc.write_bytes(b"not an encrypted cache")

    cache = AppInfoCache()  # must not raise

    assert cache.get("probe") is None
    cache.set("probe", "value")
    assert cache.store() is False
    assert enc.read_bytes() == b"not an encrypted cache"
    assert not (cache_dir / "app_info_cache.json").exists()


def test_corrupt_main_file_loads_from_backup(cache_dir):
    enc = _stored_cache(cache_dir, probe="kept")
    (cache_dir / "app_info_cache.enc.bak").write_bytes(enc.read_bytes())
    enc.write_bytes(b"truncated")

    cache = AppInfoCache()

    assert cache.get("probe") == "kept"
    assert cache.store() is True
    assert AppInfoCache().get("probe") == "kept"


def test_json_cache_migrates_to_encrypted(cache_dir):
    json_path = cache_dir / "app_info_cache.json"
    json_path.write_text(
        json.dumps({"info": {"probe": "from json"}, "directories": {}}), encoding="utf-8"
    )

    assert AppInfoCache().get("probe") == "from json"
    assert not json_path.exists()
    assert AppInfoCache().get("probe") == "from json"


def test_json_cache_kept_until_a_store_succeeds(cache_dir, monkeypatch):
    json_path = cache_dir / "app_info_cache.json"
    json_path.write_text(
        json.dumps({"info": {"probe": "from json"}, "directories": {}}), encoding="utf-8"
    )
    real_encrypt = cache_module.encrypt_data_to_file
    calls = []

    def first_call_cred_error(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise Exception("(1168, 'CredRead', 'Element not found.')")
        return real_encrypt(*args, **kwargs)

    monkeypatch.setattr(cache_module, "encrypt_data_to_file", first_call_cred_error)

    cache = AppInfoCache()
    assert json_path.exists()

    cache.set("probe", "newer")
    assert cache.store() is True
    assert not json_path.exists()
    assert AppInfoCache().get("probe") == "newer"
