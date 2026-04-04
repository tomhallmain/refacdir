"""``rename_by_mtime`` / ``rename_by_ctime`` with user dry-run vs real renames."""

import os

import pytest

from refacdir.file_renamer import FileRenamer


@pytest.fixture
def restore_cwd(request):
    cwd = os.getcwd()
    yield
    try:
        os.chdir(cwd)
    except OSError:
        pass


def test_rename_by_mtime_user_dry_run_leaves_file_unchanged(tmp_path, restore_cwd):
    """``FileRenamer(test=True)`` is user dry-run: ``os.rename`` is not called."""
    root = str(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    fr = FileRenamer(root, test=True)
    fr.rename_by_mtime("*.txt", "pfx_", recursive=False)
    assert (tmp_path / "a.txt").exists()
    assert not any(p.name.startswith("pfx_") for p in tmp_path.iterdir())


def test_rename_by_mtime_renames_on_disk_when_not_dry_run(tmp_path, restore_cwd):
    """``test=False`` performs real renames under ``root``."""
    root = str(tmp_path)
    p = tmp_path / "b.txt"
    p.write_text("x", encoding="utf-8")
    fixed = 1_701_000_000.0
    os.utime(p, (fixed, fixed))
    fr = FileRenamer(root, test=False, preserve_alpha=False)
    fr.rename_by_mtime("*.txt", "out_", recursive=False)
    assert not p.exists()
    names = {x.name for x in tmp_path.iterdir()}
    assert any(n.startswith("out_") and n.endswith(".txt") for n in names)


def test_rename_by_ctime_matches_glob_non_recursive(tmp_path, restore_cwd):
    root = str(tmp_path)
    (tmp_path / "c.txt").write_text("z", encoding="utf-8")
    fr = FileRenamer(root, test=True)
    fr.rename_by_ctime("c.txt", "ct_", recursive=False)
    # Dry-run: original still present
    assert (tmp_path / "c.txt").exists()
