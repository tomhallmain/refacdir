"""Tests run against an in-memory keyring, never the OS one."""

from __future__ import annotations

import os

import keyring

from refacdir.utils.app_info_cache import AppInfoCache
from refacdir.utils.constants import AppInfo
from refacdir.utils.encryptor import KEY_STORE_DIR_ENV_VAR, PassphraseManager, key_store_path


def test_keyring_backend_is_per_test_in_memory(isolated_keyring):
    assert keyring.get_keyring() is isolated_keyring
    assert isolated_keyring.secrets == {}


def test_passphrase_lookup_is_stubbed():
    assert PassphraseManager.get_passphrase(AppInfo.SERVICE_NAME, AppInfo.APP_IDENTIFIER) == (
        "test-only-passphrase"
    )


def test_app_info_cache_round_trip_keeps_keys_in_memory(isolated_keyring, tmp_path, monkeypatch):
    monkeypatch.delenv("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", raising=False)
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))

    cache = AppInfoCache()
    cache.set("probe", "value")
    cache.store()

    assert (tmp_path / "app_info_cache.enc").exists()
    # Key material goes to the per-test key store; the stubbed passphrase
    # lookup writes nothing, so the keyring holds nothing for another service.
    assert {service for service, _ in isolated_keyring.secrets} <= {AppInfo.SERVICE_NAME}
    store_path = key_store_path(AppInfo.SERVICE_NAME, AppInfo.APP_IDENTIFIER)
    assert os.path.exists(store_path)
    assert store_path.startswith(os.environ[KEY_STORE_DIR_ENV_VAR])
    assert AppInfoCache().get("probe") == "value"
