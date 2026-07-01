"""
Pytest-wide isolation: keep tests off the user's persisted cache and config trees.

``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` makes ``AppInfoCache.load`` and
``AppInfoCache.store`` no-ops so tests do not read or write ``app_info_cache.enc``.
It must be set before ``encryptor`` is imported (see that module's oqs gate).

Per-test ``isolated_app_singletons`` sets ``REFACDIR_CACHE_DIR`` and
``REFACDIR_CONFIGS_DIR`` under ``tmp_path`` and patches module-level singletons
so imports bound at load time still see isolated instances.

**Conftest load order:** this file is loaded before nested ``test/*/conftest.py`` files.
``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` is set at the top of this module before any
``refacdir`` imports.

Unset ``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` in a test if you need to exercise
real cache persistence (with ``REFACDIR_CACHE_DIR`` pointing at ``tmp_path``).
"""
import importlib
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")

from refacdir.batch import BatchArgs
from refacdir.filename_ops import FiletypesDefinition, FilenameMappingDefinition

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_MINIMAL_TEST_CONFIG_JSON = {
    "foreground_color": "white",
    "background_color": "#000000",
    "server_port": 6001,
    "server_password": "<PASSWORD>",
    "debug": False,
}


def pytest_configure(config):
    os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")


def _patch_app_info_cache_singleton(monkeypatch, cache_instance) -> None:
    """Patch app_info_cache everywhere tests may hold a reference."""
    cache_module = importlib.import_module("refacdir.utils.app_info_cache")
    monkeypatch.setattr(cache_module, "app_info_cache", cache_instance)

    for module_name in (
        "refacdir.duplicate_remover",
        "app_qt",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if hasattr(module, "app_info_cache"):
            monkeypatch.setattr(module, "app_info_cache", cache_instance)


def _patch_config_singleton(monkeypatch, config_instance) -> None:
    """Patch config everywhere tests may hold a reference."""
    config_module = importlib.import_module("refacdir.config")
    monkeypatch.setattr(config_module, "config", config_instance)

    for module_name in (
        "app_qt",
        "extensions.refacdir_server",
        "refacdir.image_categorizer",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if hasattr(module, "config"):
            monkeypatch.setattr(module, "config", config_instance)
        if hasattr(module, "_config"):
            monkeypatch.setattr(module, "_config", config_instance)


@pytest.fixture
def restore_batch_configs():
    """Restore ``BatchArgs.configs`` after tests that call ``override_configs``."""
    prev = dict(BatchArgs.configs)
    yield
    BatchArgs.configs = prev


@pytest.fixture
def restore_filename_mapping_registry():
    """Isolate ``FilenameMappingDefinition.NAMED_FUNCTIONS`` from other tests."""
    prev = FilenameMappingDefinition.NAMED_FUNCTIONS.copy()
    yield
    FilenameMappingDefinition.NAMED_FUNCTIONS.clear()
    FilenameMappingDefinition.NAMED_FUNCTIONS.update(prev)


@pytest.fixture
def restore_batch_registries():
    """Isolate filetype and filename definition registries from other tests."""
    ft = FiletypesDefinition.NAMED_DEFINITIONS.copy()
    fn = FilenameMappingDefinition.NAMED_FUNCTIONS.copy()
    yield
    FiletypesDefinition.NAMED_DEFINITIONS.clear()
    FiletypesDefinition.NAMED_DEFINITIONS.update(ft)
    FilenameMappingDefinition.NAMED_FUNCTIONS.clear()
    FilenameMappingDefinition.NAMED_FUNCTIONS.update(fn)


@pytest.fixture(autouse=True)
def isolated_app_singletons(tmp_path, monkeypatch):
    """Point cache/config singletons at a fresh per-test temp directory."""
    from refacdir.utils.app_info_cache import AppInfoCache
    from refacdir.config import Config

    prev_configs = dict(BatchArgs.configs)

    cache_dir = tmp_path / "cache"
    configs_dir = tmp_path / "configs"
    cache_dir.mkdir()
    configs_dir.mkdir()

    (configs_dir / "config.json").write_text(
        json.dumps(_MINIMAL_TEST_CONFIG_JSON),
        encoding="utf-8",
    )

    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(configs_dir))

    new_cache = AppInfoCache()
    _patch_app_info_cache_singleton(monkeypatch, new_cache)

    config_instance = Config()
    _patch_config_singleton(monkeypatch, config_instance)

    yield

    BatchArgs.configs = prev_configs


@pytest.fixture(autouse=True)
def reset_batch_job_history(isolated_app_singletons):
    """Clear batch job history and the in-memory session on the isolated cache."""
    import refacdir.batch_job_history as batch_job_history
    import refacdir.utils.app_info_cache as cache_module

    batch_job_history._active_session = None
    cache_module.app_info_cache.set("batch_job_history", [])
    yield
    batch_job_history._active_session = None
    cache_module.app_info_cache.set("batch_job_history", [])
