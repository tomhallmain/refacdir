"""
Pytest-wide defaults: keep automated tests off the user's persisted app cache.

``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` makes ``AppInfoCache.load`` and
``AppInfoCache.store`` no-ops so tests do not read or write ``app_info_cache.enc``.
It must also be set before ``encryptor`` is imported (see that module's oqs gate).

**Why module-level, not only** ``pytest_configure``: child conftests (e.g.
``test/renamer/conftest.py``) import ``refacdir.batch`` at import time. Those
imports run before ``pytest_configure``, so the variable must be set as soon as
this file is loaded (parent conftest loads before children).

Unset in the environment if you need a test to exercise real cache persistence.
"""
import os

os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")


def pytest_configure(config):
    os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")
