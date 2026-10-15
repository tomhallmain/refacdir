"""Helpers and Nuitka arguments of build_exe.py, loaded by file path; nothing
is installed or compiled."""

import importlib.util
import os
import sys

import pytest

from refacdir.utils import app_paths

_BUILD_EXE = os.path.join(app_paths.REPO_ROOT, "build_exe.py")

# The test tree ships in the GUI build, build_exe.py does not.
pytestmark = pytest.mark.skipif(not os.path.isfile(_BUILD_EXE), reason="needs a source checkout")

BUILD_ID = "20261015-120000"


@pytest.fixture(scope="module")
def build_exe():
    spec = importlib.util.spec_from_file_location("build_exe_under_test", _BUILD_EXE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _target(build_exe, base_name):
    (target,) = [t for t in build_exe.TARGETS if t[0] == base_name]
    return target


def test_common_args(build_exe):
    args = build_exe._common_args("RefacDir.exe", "refacdir", "1.2.3", BUILD_ID)
    assert "--onefile" in args and "--standalone" not in args
    assert "--output-filename=RefacDir.exe" in args
    assert "--include-distribution-metadata=keyring" in args
    assert "--include-distribution-metadata=mcp" in args
    assert "--include-package=uvicorn" in args
    assert "--product-version=1.2.3" in args
    assert "--file-version=1.2.3" in args
    assert any(BUILD_ID in a for a in args if a.startswith("--file-description="))
    assert f"--include-data-files={build_exe.BUILD_INFO_PATH}=build_info.json" in args
    assert f"--include-data-files={build_exe.VERSION_FILE}={build_exe.VERSION_FILE}" in args


@pytest.mark.parametrize("base_name", ["RefacDir", "RefacDirHeadless"])
def test_each_build_unpacks_to_its_own_folder_in_the_app_data_dir(build_exe, base_name):
    _base, _entry, unpack_prefix, _target_args = _target(build_exe, base_name)
    args = build_exe._common_args(base_name, unpack_prefix, "1.2.3", BUILD_ID)
    spec = build_exe._pop_option(args, "--onefile-tempdir-spec")
    assert spec == f"{build_exe.APP_DATA_SPEC}/unpacked/{unpack_prefix}-{BUILD_ID}"
    assert build_exe.APP_DATA_SPEC.endswith("/" + app_paths.APP_DIR_NAME)


def test_unpack_prefixes_differ(build_exe):
    prefixes = [t[2] for t in build_exe.TARGETS]
    assert len(set(prefixes)) == len(prefixes)


def test_headless_target_is_built_only_on_request(build_exe):
    assert [t[0] for t in build_exe._targets(with_headless=False)] == ["RefacDir"]
    assert [t[0] for t in build_exe._targets(with_headless=True)] == ["RefacDir", "RefacDirHeadless"]


def test_package_release_finds_the_headless_option(build_exe):
    """scripts/package_release.py looks for this literal to rebuild RefacDirHeadless."""
    with open(_BUILD_EXE, "r", encoding="utf-8") as f:
        assert '"--with-headless"' in f.read()


def test_entry_scripts_exist(build_exe):
    for _base, entry, _prefix, _target_args in build_exe.TARGETS:
        assert os.path.isfile(os.path.join(build_exe.REPO_ROOT, entry))


def test_only_the_gui_target_bundles_qt(build_exe):
    assert "--enable-plugin=pyside6" in build_exe._gui_args()
    headless = build_exe._headless_args()
    assert "--nofollow-import-to=PySide6" in headless
    assert not any("pyside6" in a.lower() and a != "--nofollow-import-to=PySide6" for a in headless)


def test_gui_target_bundles_the_test_tree(build_exe):
    args = build_exe._gui_args()
    conftest = os.path.join("test", "conftest.py")
    assert f"--include-data-files={conftest}={conftest}" in args
    assert not any("__pycache__" in a for a in args)


def test_build_without_oqs_leaves_it_out(build_exe):
    assert build_exe._oqs_args(sys.executable, with_oqs=False) == ["--nofollow-import-to=oqs"]


def test_app_version_is_numeric(build_exe):
    assert build_exe._app_version().replace(".", "").isdigit()


def test_bad_version_stops_the_build(build_exe, monkeypatch, tmp_path):
    (tmp_path / build_exe.VERSION_FILE).write_text("1.0-beta\n", encoding="utf-8")
    monkeypatch.setattr(build_exe, "REPO_ROOT", str(tmp_path))
    with pytest.raises(SystemExit):
        build_exe._app_version()


def test_version_module_loads_without_the_app(build_exe):
    module = build_exe._version_module()
    assert callable(module["source_state"])
    assert module["VERSION_FILE"] == build_exe.VERSION_FILE
    assert module["BUILD_INFO_FILE"] == os.path.basename(build_exe.BUILD_INFO_PATH)


def test_lock_has(build_exe, tmp_path):
    lock = tmp_path / "lock.txt"
    lock.write_text("PySide6==6.11.2\nliboqs-python @ git+https://example.invalid/liboqs-python.git\n",
                    encoding="utf-8")
    assert build_exe._lock_has(str(lock), "pyside6")
    assert build_exe._lock_has(str(lock), "liboqs_python")
    assert not build_exe._lock_has(str(lock), "mcp")


def test_smoke_test_env_overrides_shell_values(build_exe, monkeypatch, tmp_path):
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", "/real/configs")
    monkeypatch.setenv("REFACDIR_CACHE_DIR", "/real/cache")
    monkeypatch.setenv("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")
    env = build_exe._smoke_test_env(str(tmp_path))
    assert env["REFACDIR_APP_DATA_DIR"] == str(tmp_path)
    assert env["REFACDIR_CONFIGS_DIR"] == os.path.join(str(tmp_path), "configs")
    assert env["REFACDIR_CACHE_DIR"] == os.path.join(str(tmp_path), "cache")
    assert "REFACDIR_DISABLE_APP_INFO_CACHE_LOAD" not in env


def test_copy_to_dist_replaces_a_folder_build(build_exe, monkeypatch, tmp_path):
    build_dir, dist_dir = tmp_path / "build", tmp_path / "dist"
    build_dir.mkdir()
    (build_dir / "RefacDir").write_bytes(b"exe")
    (dist_dir / "RefacDir").mkdir(parents=True)
    monkeypatch.setattr(build_exe, "BUILD_DIR", str(build_dir))
    monkeypatch.setattr(build_exe, "DIST_DIR", str(dist_dir))
    path = build_exe._copy_to_dist("RefacDir")
    assert os.path.isfile(path)


def test_memory_wait_plugin_is_loaded(build_exe):
    args = build_exe._common_args("RefacDir.exe", "refacdir", "1.2.3", BUILD_ID)
    plugin = build_exe._pop_option(args, "--user-plugin")
    assert plugin == build_exe.MEMORY_WAIT_PLUGIN
    assert os.path.isfile(plugin)


def test_min_free_memory_reaches_nuitka(build_exe, monkeypatch):
    monkeypatch.delenv(build_exe.MIN_FREE_MEMORY_ENV, raising=False)
    assert build_exe._nuitka_env("12")[build_exe.MIN_FREE_MEMORY_ENV] == "12"
    assert build_exe.MIN_FREE_MEMORY_ENV not in build_exe._nuitka_env(None)


@pytest.mark.parametrize("value", ["0", "12", "2.5"])
def test_min_free_memory_accepts_gib(build_exe, value):
    assert build_exe._min_free_memory(value) == value


@pytest.mark.parametrize("value", ["-1", "lots", ""])
def test_min_free_memory_refuses_other_values(build_exe, value):
    with pytest.raises(SystemExit):
        build_exe._min_free_memory(value)


def test_min_free_memory_variable_matches_the_plugin(build_exe):
    with open(build_exe.MEMORY_WAIT_PLUGIN, "r", encoding="utf-8") as f:
        assert f'MIN_FREE_ENV = "{build_exe.MIN_FREE_MEMORY_ENV}"' in f.read()


@pytest.mark.parametrize("seconds, text", [
    (0, "0s"), (59.6, "1m 00s"), (125, "2m 05s"), (2 * 3600 + 5, "2h 00m 05s"),
])
def test_duration(build_exe, seconds, text):
    assert build_exe._duration(seconds) == text


def test_timed_logs_the_duration_of_a_step(build_exe, caplog):
    with caplog.at_level("INFO", logger="build_exe"):
        with build_exe._timed("Compiling"):
            pass
    assert caplog.messages[0] == "Compiling..."
    assert caplog.messages[-1].startswith("Compiling done in ")


def test_timed_logs_a_failed_step(build_exe, caplog):
    with caplog.at_level("INFO", logger="build_exe"):
        with pytest.raises(SystemExit):
            with build_exe._timed("Compiling"):
                raise SystemExit("broken")
    assert caplog.messages[-1].startswith("Compiling failed after ")
