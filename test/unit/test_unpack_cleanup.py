"""refacdir/utils/unpack_cleanup.py, run as if this were a build unpacked
under tmp_path. The process list is stubbed; every file operation stays in
tmp_path."""

import importlib.util
import os

import pytest

from refacdir.utils import app_paths, unpack_cleanup

CURRENT = "refacdir-20261009-120000"


def in_build(monkeypatch, folder):
    monkeypatch.setattr(unpack_cleanup, "IS_BUILD", True)
    monkeypatch.setattr(unpack_cleanup, "RESOURCE_ROOT", str(folder))


def running(monkeypatch, executables):
    """Stub the running processes' executables (None: cannot be listed)."""
    value = None if executables is None else {unpack_cleanup._normalize(str(e)) for e in executables}
    monkeypatch.setattr(unpack_cleanup, "_running_executables", lambda: value)


def _build_folder(root, name):
    folder = root / name
    (folder / "locale").mkdir(parents=True)
    (folder / "locale" / "base.mo").write_bytes(b"x")
    (folder / "RefacDir").write_bytes(b"exe")
    return folder


@pytest.fixture
def unpacked(monkeypatch, tmp_path):
    """An unpacked/ dir holding the running GUI build's folder, with no other
    processes running from it; returns the dir."""
    root = tmp_path / "unpacked"
    (root / CURRENT / "refacdir").mkdir(parents=True)
    in_build(monkeypatch, root / CURRENT)
    running(monkeypatch, set())
    return root


@pytest.fixture(params=[True, False], ids=["windows", "macos-linux"])
def platform(request, monkeypatch):
    monkeypatch.setattr(unpack_cleanup, "_IS_WINDOWS", request.param)
    return request.param


class TestRemoveStaleUnpackDirs:
    def test_removes_older_builds_and_keeps_the_running_one(self, unpacked, platform):
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        removed = unpack_cleanup.remove_stale_unpack_dirs()
        assert not old.exists()
        assert not os.path.exists(str(old) + ".removing")
        assert (unpacked / CURRENT).is_dir()
        assert len(removed) == 1

    def test_skips_a_folder_a_running_process_executes_from(self, unpacked, platform, monkeypatch):
        in_use = _build_folder(unpacked, "refacdir-20261005-100000")
        idle = _build_folder(unpacked, "refacdir-20261001-090000")
        running(monkeypatch, {in_use / "RefacDir"})
        unpack_cleanup.remove_stale_unpack_dirs()
        assert in_use.is_dir()
        assert not idle.exists()

    def test_a_similar_folder_name_is_not_mistaken_for_in_use(self, unpacked, platform, monkeypatch):
        old = _build_folder(unpacked, "refacdir-20261001-09")
        _build_folder(unpacked, "refacdir-20261001-0900")
        running(monkeypatch, {unpacked / "refacdir-20261001-0900" / "RefacDir"})
        unpack_cleanup.remove_stale_unpack_dirs()
        assert not old.exists()

    def test_leaves_other_entries_alone(self, unpacked, platform):
        other = _build_folder(unpacked, "something-else")
        stray_file = unpacked / "refacdir-notes.txt"
        stray_file.write_text("keep", encoding="utf-8")
        unpack_cleanup.remove_stale_unpack_dirs()
        assert other.is_dir()
        assert stray_file.is_file()

    def test_skips_a_folder_that_cannot_be_renamed(self, unpacked, platform, monkeypatch):
        locked = _build_folder(unpacked, "refacdir-20261005-100000")
        real_rename = os.rename

        def rename(src, dst):
            if os.path.basename(src) == locked.name:
                raise PermissionError("in use")
            real_rename(src, dst)

        monkeypatch.setattr(unpack_cleanup.os, "rename", rename)
        assert unpack_cleanup.remove_stale_unpack_dirs() == []
        assert locked.is_dir()

    def test_finishes_a_folder_renamed_at_an_earlier_start(self, unpacked, platform):
        leftover = _build_folder(unpacked, "refacdir-20261001-090000.removing")
        unpack_cleanup.remove_stale_unpack_dirs()
        assert not leftover.exists()

    def test_without_a_process_list_windows_relies_on_the_rename(self, unpacked, monkeypatch):
        monkeypatch.setattr(unpack_cleanup, "_IS_WINDOWS", True)
        running(monkeypatch, None)
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        unpack_cleanup.remove_stale_unpack_dirs()
        assert not old.exists()

    def test_without_a_process_list_other_platforms_remove_nothing(self, unpacked, monkeypatch):
        monkeypatch.setattr(unpack_cleanup, "_IS_WINDOWS", False)
        running(monkeypatch, None)
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        assert unpack_cleanup.remove_stale_unpack_dirs() == []
        assert old.is_dir()

    def test_does_nothing_in_a_checkout(self, unpacked, platform, monkeypatch):
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        monkeypatch.setattr(unpack_cleanup, "IS_BUILD", False)
        assert unpack_cleanup.remove_stale_unpack_dirs() == []
        assert old.is_dir()

    def test_does_nothing_outside_an_unpack_folder(self, unpacked, platform, monkeypatch, tmp_path):
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        monkeypatch.setattr(unpack_cleanup, "RESOURCE_ROOT", str(tmp_path / "repo"))
        assert unpack_cleanup.remove_stale_unpack_dirs() == []
        assert old.is_dir()

    def test_the_running_folder_under_its_short_name_is_kept(self, unpacked, monkeypatch):
        """On Windows a build can see its folder as REFACD~1 while listdir
        returns the long name."""
        monkeypatch.setattr(unpack_cleanup, "_IS_WINDOWS", True)
        short = str(unpacked / "REFACD~1")
        monkeypatch.setattr(unpack_cleanup, "RESOURCE_ROOT", short)
        monkeypatch.setattr(unpack_cleanup, "_long_path",
                            lambda path: str(unpacked / CURRENT) if path == short else path)
        old = _build_folder(unpacked, "refacdir-20261001-090000")
        unpack_cleanup.remove_stale_unpack_dirs()
        assert (unpacked / CURRENT).is_dir()
        assert not old.exists()


class TestBuildKinds:
    """The GUI and headless builds share unpacked/; each cleans up only its own folders."""

    def test_the_gui_leaves_headless_folders_alone(self, unpacked, platform):
        headless = _build_folder(unpacked, "refacdir-headless-20261001-090000")
        old_gui = _build_folder(unpacked, "refacdir-20261001-090000")
        unpack_cleanup.remove_stale_unpack_dirs()
        assert headless.is_dir()
        assert not old_gui.exists()

    def test_the_headless_build_removes_only_headless_folders(self, unpacked, platform, monkeypatch):
        current = _build_folder(unpacked, "refacdir-headless-20261009-120000")
        in_build(monkeypatch, current)
        old_headless = _build_folder(unpacked, "refacdir-headless-20261001-090000")
        unpack_cleanup.remove_stale_unpack_dirs(unpack_cleanup.HEADLESS_UNPACK_DIR_PREFIX)
        assert current.is_dir()
        assert not old_headless.exists()
        assert (unpacked / CURRENT).is_dir()

    def test_a_prefix_that_does_not_match_the_running_folder_removes_nothing(self, unpacked, platform):
        headless = _build_folder(unpacked, "refacdir-headless-20261001-090000")
        # The running folder is a GUI one.
        assert unpack_cleanup.remove_stale_unpack_dirs(unpack_cleanup.HEADLESS_UNPACK_DIR_PREFIX) == []
        assert headless.is_dir()


_BUILD_EXE = os.path.join(app_paths.REPO_ROOT, "build_exe.py")


@pytest.mark.skipif(not os.path.isfile(_BUILD_EXE), reason="needs a source checkout")
@pytest.mark.parametrize("base_name, expected_prefix", [
    ("RefacDir", "UNPACK_DIR_PREFIX"),
    ("RefacDirHeadless", "HEADLESS_UNPACK_DIR_PREFIX"),
])
def test_build_exe_unpacks_to_folders_this_module_recognizes(base_name, expected_prefix):
    spec = importlib.util.spec_from_file_location("build_exe_for_cleanup_test", _BUILD_EXE)
    build_exe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_exe)
    (_base, _entry, unpack_prefix, _target_args), = [t for t in build_exe.TARGETS if t[0] == base_name]
    args = build_exe._common_args(base_name, unpack_prefix, "1.2.3", "20261015-120000")
    parent, folder = build_exe._pop_option(args, "--onefile-tempdir-spec").split("/")[-2:]
    assert parent == unpack_cleanup.UNPACK_PARENT_NAME
    assert unpack_cleanup._unpack_dir_kind(folder) == getattr(unpack_cleanup, expected_prefix)


class TestRunningExecutables:
    def test_lists_this_process(self):
        psutil = pytest.importorskip("psutil")
        executables = unpack_cleanup._running_executables()
        assert unpack_cleanup._normalize(psutil.Process().exe()) in executables

    def test_none_without_psutil(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_psutil(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_psutil)
        assert unpack_cleanup._running_executables() is None
