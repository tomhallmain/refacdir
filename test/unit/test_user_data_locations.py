"""Where user configs, the example configs and cache files resolve to."""

from __future__ import annotations

import json
import os

import yaml

import refacdir
import refacdir.config as config_module
from refacdir.batch import BatchJob
from refacdir.config import Config
from refacdir.utils import app_paths
from refacdir.utils.app_info_cache import AppInfoCache


def test_configs_dir_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(tmp_path))
    assert Config.configs_dir() == str(tmp_path)


def test_configs_dir_defaults_to_user_configs_dir(monkeypatch):
    monkeypatch.delenv("REFACDIR_CONFIGS_DIR", raising=False)
    monkeypatch.setattr(config_module, "user_configs_dir", lambda: "/fake/appdata/configs")
    assert Config.configs_dir() == "/fake/appdata/configs"


def test_resolve_config_path_prefers_config_json():
    # isolated_app_singletons writes config.json into the per-test configs dir.
    assert Config.resolve_config_path() == os.path.join(Config.configs_dir(), "config.json")


def test_resolve_config_path_uses_other_json_without_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(tmp_path))
    (tmp_path / "mine.json").write_text("{}", encoding="utf-8")
    assert Config.resolve_config_path() == str(tmp_path / "mine.json")


def test_resolve_config_path_falls_back_to_example_when_no_json(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(tmp_path))
    (tmp_path / "config_example.json").write_text("{}", encoding="utf-8")
    assert Config.resolve_config_path() == Config.EXAMPLE_CONFIG_JSON


def test_resolve_config_path_falls_back_to_example_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(tmp_path / "missing"))
    assert Config.resolve_config_path() == Config.EXAMPLE_CONFIG_JSON


def test_example_configs_ship_in_examples_dir():
    assert os.path.dirname(Config.EXAMPLE_CONFIG_JSON) == app_paths.EXAMPLES_DIR
    with open(Config.EXAMPLE_CONFIG_JSON, encoding="utf-8") as handle:
        assert isinstance(json.load(handle), dict)
    with open(os.path.join(app_paths.EXAMPLES_DIR, "config_example.yaml"), encoding="utf-8") as handle:
        assert isinstance(yaml.safe_load(handle), dict)


def test_example_config_loads_when_no_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(tmp_path))
    loaded = Config()
    assert loaded.config_path == Config.EXAMPLE_CONFIG_JSON
    assert loaded.dict


# Read at collection, before the autouse fixture points BASE_DIR at tmp_path.
_IMPORT_TIME_BASE_DIR = BatchJob.BASE_DIR


def test_batch_job_base_dir_is_app_data_dir():
    """``configs/<name>.yaml`` keys must land in the default user configs dir."""
    assert _IMPORT_TIME_BASE_DIR == app_paths.app_data_dir()


def test_app_info_cache_defaults_to_package_dir(monkeypatch):
    monkeypatch.delenv("REFACDIR_CACHE_DIR", raising=False)
    cache = AppInfoCache()  # load is a no-op under the test-wide disable flag
    package_dir = os.path.dirname(os.path.abspath(refacdir.__file__))
    assert cache._cache_loc == os.path.join(package_dir, "app_info_cache.enc")


def test_app_info_cache_files_live_in_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    cache = AppInfoCache()
    assert cache._cache_loc == str(tmp_path / "app_info_cache.enc")
    assert cache._json_loc == str(tmp_path / "app_info_cache.json")


def test_tests_resolve_config_keys_to_one_dir():
    """Both halves of config-key resolution agree under the autouse isolation."""
    assert os.path.join(BatchJob.BASE_DIR, "configs") == Config.configs_dir()


def test_tests_log_to_session_app_data_dir():
    """The app's own log file handler, if installed, writes under the session dir.

    The root logger also carries pytest's logging-plugin handlers (its
    ``log_file`` handler targets ``os.devnull`` when unset), so only handlers
    for the app's ``refacdir_*.log`` files are checked.
    """
    import logging

    from refacdir.utils.logger import get_log_directory

    def norm(path):
        return os.path.normcase(os.path.realpath(path))

    session_dir = norm(os.environ["REFACDIR_APP_DATA_DIR"])
    assert norm(get_log_directory()).startswith(session_dir)

    app_log_files = [
        handler.baseFilename
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.FileHandler)
        and os.path.basename(handler.baseFilename).startswith("refacdir_")
    ]
    assert all(norm(path).startswith(session_dir) for path in app_log_files)
