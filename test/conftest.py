"""
Pytest-wide isolation: keep tests off the user's persisted cache and config trees.

``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` makes ``AppInfoCache.load`` and
``AppInfoCache.store`` no-ops so tests do not read or write ``app_info_cache.enc``.
It must be set before ``encryptor`` is imported (see that module's oqs gate).

Per-test ``isolated_app_singletons`` sets ``REFACDIR_CACHE_DIR`` and
``REFACDIR_CONFIGS_DIR`` under ``tmp_path`` and patches module-level singletons
so imports bound at load time still see isolated instances.

**Conftest load order:** this file is loaded before nested ``test/*/conftest.py`` files.
``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD``, ``REFACDIR_CONFIGS_DIR``, and ``REFACDIR_CACHE_DIR``
are set at the top of this module **before any** ``refacdir`` imports so collection never
reads the repo ``configs/`` tree or user cache.

Unset ``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` in a test if you need to exercise
real cache persistence (with ``REFACDIR_CACHE_DIR`` pointing at ``tmp_path``).

UI tests live under ``test/ui/``. Use pytest-qt's ``qtbot`` fixture (see ``test/ui/conftest.py``).
Install ``pytest-qt``; ``qt_api = pyside6`` is set in ``pytest.ini``. Only ``test/ui/`` tests
should request ``qtbot``; other suites are unaffected.
Singleton patches below include UI modules that bind ``app_info_cache`` or ``config`` at
import time so isolated instances are visible after those imports.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_TEST_ROOT = Path(__file__).resolve().parent
_FIXTURE_CONFIGS = _TEST_ROOT / "fixtures" / "configs"
_FIXTURE_CACHE = _TEST_ROOT / "fixtures" / "cache"

os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")
os.environ.setdefault("REFACDIR_CONFIGS_DIR", str(_FIXTURE_CONFIGS))
os.environ.setdefault("REFACDIR_CACHE_DIR", str(_FIXTURE_CACHE))

from refacdir.batch import BatchArgs
from refacdir.filename_ops import FiletypesDefinition, FilenameMappingDefinition

_PROJECT_ROOT = _TEST_ROOT.parent

# Modules that may hold a module-level ``app_info_cache`` reference after import.
_APP_INFO_CACHE_PATCH_MODULES = (
    "refacdir.duplicate_remover",
    "app_qt",
)

# Modules that may hold module-level ``config`` / ``_config`` references after import.
_CONFIG_PATCH_MODULES = (
    "app_qt",
    "extensions.refacdir_server",
    "refacdir.image_categorizer",
    "ui.app_style",
)


def _import_module(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _patch_app_info_cache_singleton(monkeypatch, cache_instance) -> None:
    """Patch app_info_cache everywhere tests may hold a reference."""
    cache_module = importlib.import_module("refacdir.utils.app_info_cache")
    monkeypatch.setattr(cache_module, "app_info_cache", cache_instance)

    for module_name in _APP_INFO_CACHE_PATCH_MODULES:
        module = _import_module(module_name)
        if module is not None and hasattr(module, "app_info_cache"):
            monkeypatch.setattr(module, "app_info_cache", cache_instance)


def _patch_config_singleton(monkeypatch, config_instance) -> None:
    """Patch config everywhere tests may hold a reference."""
    config_module = importlib.import_module("refacdir.config")
    monkeypatch.setattr(config_module, "config", config_instance)

    for module_name in _CONFIG_PATCH_MODULES:
        module = _import_module(module_name)
        if module is None:
            continue
        if hasattr(module, "config"):
            monkeypatch.setattr(module, "config", config_instance)
        if hasattr(module, "_config"):
            monkeypatch.setattr(module, "_config", config_instance)

_MINIMAL_TEST_CONFIG_JSON = {
    "foreground_color": "white",
    "background_color": "#000000",
    "server_port": 6001,
    "server_password": "<PASSWORD>",
    "debug": False,
}


def pytest_configure(config):
    os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
    batch_job_history._recording_context = None
    cache_module.app_info_cache.set("batch_job_history", [])
    yield
    batch_job_history._active_session = None
    batch_job_history._recording_context = None
    cache_module.app_info_cache.set("batch_job_history", [])
