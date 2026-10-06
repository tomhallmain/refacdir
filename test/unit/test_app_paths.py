"""Unit tests for the per-user app data dirs and the one-time move of repo files."""

import os

import pytest

from refacdir.utils import app_paths


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    """A fake repo and app data dir, with the per-process move state reset."""
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "refacdir" / "backup").mkdir(parents=True)
    data = tmp_path / "appdata"
    # conftest's session override disables the move this fixture exercises.
    monkeypatch.delenv("REFACDIR_APP_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths, "REPO_ROOT", str(repo))
    monkeypatch.setattr(app_paths, "LEGACY_REPO_CONFIGS_DIR", str(repo / "configs"))
    monkeypatch.setattr(app_paths, "app_data_dir", lambda: str(data))
    monkeypatch.setattr(app_paths, "_migrated", set())
    return repo, data


def test_configs_move_and_empty_legacy_dir_is_removed(fake_layout):
    repo, data = fake_layout
    for name in ("mine.yaml", "config.json", "master_config.yaml"):
        (repo / "configs" / name).write_text(name)

    configs_dir = app_paths.user_configs_dir()

    assert configs_dir == str(data / "configs")
    moved = sorted(p.name for p in (data / "configs").iterdir())
    assert moved == ["config.json", "master_config.yaml", "mine.yaml"]
    assert not (repo / "configs").exists()


def test_cache_files_move_from_package_dir(fake_layout):
    repo, data = fake_layout
    for rel in ("refacdir/app_info_cache.enc", "refacdir/app_info_cache.enc.bak2",
                "refacdir/filename_pattern_cache.enc",
                "refacdir/llm_prompt_response_history_x.json",
                "refacdir/unrelated.json"):
        (repo / rel).write_text(rel)

    app_paths.user_cache_dir()

    moved = sorted(p.name for p in (data / "cache").iterdir())
    assert moved == [
        "app_info_cache.enc",
        "app_info_cache.enc.bak2",
        "filename_pattern_cache.enc",
        "llm_prompt_response_history_x.json",
    ]
    assert (repo / "refacdir" / "unrelated.json").exists()


def test_existing_target_is_not_overwritten(fake_layout):
    repo, data = fake_layout
    (data / "configs").mkdir(parents=True)
    (data / "configs" / "mine.yaml").write_text("new")
    (repo / "configs" / "mine.yaml").write_text("old")

    app_paths.user_configs_dir()

    assert (data / "configs" / "mine.yaml").read_text() == "new"
    assert (repo / "configs" / "mine.yaml").read_text() == "old"


def test_move_runs_once_per_process(fake_layout):
    repo, data = fake_layout
    app_paths.user_configs_dir()
    (repo / "configs" / "later.yaml").write_text("x")

    app_paths.user_configs_dir()

    assert (repo / "configs" / "later.yaml").exists()
    assert not (data / "configs" / "later.yaml").exists()


def test_failed_move_leaves_source_and_continues(fake_layout, monkeypatch):
    repo, data = fake_layout
    (repo / "configs" / "a.yaml").write_text("a")
    (repo / "configs" / "b.yaml").write_text("b")
    real_move = app_paths.shutil.move

    def move(src, dest):
        if src.endswith("a.yaml"):
            raise OSError("locked")
        return real_move(src, dest)

    monkeypatch.setattr(app_paths.shutil, "move", move)

    app_paths.user_configs_dir()

    assert (repo / "configs" / "a.yaml").exists()
    assert (data / "configs" / "b.yaml").read_text() == "b"


def test_app_data_dir_on_windows_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("REFACDIR_APP_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert app_paths.app_data_dir() == str(tmp_path / "refacdir")


def test_app_data_dir_elsewhere_uses_local_share(monkeypatch):
    monkeypatch.delenv("REFACDIR_APP_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths.platform, "system", lambda: "Linux")
    expected = os.path.join(os.path.expanduser("~"), ".local", "share", "refacdir")
    assert app_paths.app_data_dir() == expected


def test_logs_dir_is_under_app_data_dir(fake_layout):
    from refacdir.utils.logger import get_log_directory

    _repo, data = fake_layout
    assert str(get_log_directory()) == str(data / "logs")
    assert (data / "logs").is_dir()


def test_cache_dir_env_override_is_created(tmp_path, monkeypatch):
    from refacdir.utils.cache_paths import refacdir_cache_dir

    target = tmp_path / "nested" / "cache"
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(target))
    assert refacdir_cache_dir() == str(target)
    assert target.is_dir()


def test_cache_dir_defaults_to_app_data_cache_and_migrates(fake_layout, monkeypatch):
    from refacdir.utils.cache_paths import refacdir_cache_dir, resolve_cache_file

    repo, data = fake_layout
    (repo / "refacdir" / "app_info_cache.enc").write_text("x")
    monkeypatch.delenv("REFACDIR_CACHE_DIR", raising=False)

    assert refacdir_cache_dir() == str(data / "cache")
    assert (data / "cache" / "app_info_cache.enc").exists()
    assert resolve_cache_file("f.json") == str(data / "cache" / "f.json")


def test_app_data_dir_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_APP_DATA_DIR", str(tmp_path))
    assert app_paths.app_data_dir() == str(tmp_path)


def test_app_data_dir_env_override_disables_move(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "mine.yaml").write_text("x")
    monkeypatch.setattr(app_paths, "LEGACY_REPO_CONFIGS_DIR", str(repo / "configs"))
    monkeypatch.setattr(app_paths, "_migrated", set())
    monkeypatch.setenv("REFACDIR_APP_DATA_DIR", str(tmp_path / "appdata"))

    assert app_paths.user_configs_dir() == str(tmp_path / "appdata" / "configs")
    assert (repo / "configs" / "mine.yaml").exists()
