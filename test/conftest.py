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

UI tests live under ``test/ui/``; general unit tests under ``test/unit/``.
Shared helpers (``test/test_utils.py``) and fixtures (``test/fixtures/``) stay at the ``test/`` root.
Use pytest-qt's ``qtbot`` fixture (see ``test/ui/conftest.py``).
Install ``pytest-qt``; ``qt_api = pyside6`` is set in ``pytest.ini``. Only ``test/ui/`` tests
should request ``qtbot``; other suites are unaffected.
``repoint_singleton_bindings`` below sweeps ``sys.modules`` by object identity, so a
module binding ``app_info_cache`` or ``config`` at import time is isolated without being
named anywhere here.
"""
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


def repoint_singleton_bindings(monkeypatch, attr_name, old_obj, new_obj) -> None:
    """Repoint every imported module's module-level binding of *old_obj* to
    *new_obj* (undone automatically by monkeypatch at test teardown).

    Modules that do e.g. ``from refacdir.utils.app_info_cache import app_info_cache``
    at module level hold their own reference to the singleton, so patching only
    the source module leaves those bindings stale — historically handled by a
    per-module patch list that had to be extended every time a new module
    adopted the import style. Sweeping sys.modules retires that whack-a-mole:
    the identity comparison guarantees only bindings to the exact old object
    are touched, and modules imported later get the new object naturally via
    the patched source module.

    Call it once per attribute name a singleton is bound under — ``app_qt``
    imports the config singleton as ``_config``, so ``config`` alone would
    leave that binding stale.
    """
    for module in list(sys.modules.values()):
        try:
            if getattr(module, attr_name, None) is old_obj:
                monkeypatch.setattr(module, attr_name, new_obj)
        except Exception:
            continue

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
    """Provide a fresh ``BatchArgs`` and restore its configs after the test."""
    batch_args = BatchArgs(recache_configs=False, configs={})
    prev = dict(batch_args.configs)
    yield batch_args
    batch_args.configs = prev


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
    import refacdir.config as config_module
    import refacdir.utils.app_info_cache as cache_module

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

    # Each sweep repoints the source module itself plus every imported module
    # holding a module-level binding of that singleton.
    old_cache = cache_module.app_info_cache
    repoint_singleton_bindings(
        monkeypatch, "app_info_cache", old_cache, cache_module.AppInfoCache()
    )

    old_config = config_module.config
    config_instance = config_module.Config()
    repoint_singleton_bindings(monkeypatch, "config", old_config, config_instance)
    repoint_singleton_bindings(monkeypatch, "_config", old_config, config_instance)

    yield


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
