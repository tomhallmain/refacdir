"""
Unit tests for ``FileRenamer.find_matches`` / ``scan_mappings`` and the optional
pre-scanned ``filenames`` / ``scanned`` passthrough on the rename/move methods.

These back the single-scan guarantee exercised at the ``BatchRenamer`` level in
``test_batch_renamer_single_scan.py``: a mapping's matcher must not be
re-consulted once its matches have already been found.
"""

import os

import pytest

from refacdir.file_renamer import FileRenamer


@pytest.fixture
def restore_cwd():
    cwd = os.getcwd()
    yield
    try:
        os.chdir(cwd)
    except OSError:
        pass


def test_find_matches_filters_directories_and_applies_test_func(tmp_path, restore_cwd):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "subdir").mkdir()

    fr = FileRenamer(str(tmp_path))
    matches = fr.find_matches("*.txt", recursive=False)
    assert sorted(matches) == ["a.txt", "b.txt"]

    def only_a(filename):
        return filename == "a.txt"

    matches = fr.find_matches(only_a, recursive=False)
    assert matches == ["a.txt"]


def test_scan_mappings_returns_matches_per_pattern(tmp_path, restore_cwd):
    (tmp_path / "one.txt").write_text("x", encoding="utf-8")
    (tmp_path / "two.md").write_text("x", encoding="utf-8")

    fr = FileRenamer(str(tmp_path))
    scanned = fr.scan_mappings({"*.txt": "t_", "*.md": "m_"}, recursive=False)
    assert scanned["*.txt"] == ["one.txt"]
    assert scanned["*.md"] == ["two.md"]


def test_rename_by_ctime_with_precomputed_filenames_skips_rescan(tmp_path, restore_cwd):
    """Passing ``filenames=`` must be used as-is, with no additional matcher calls."""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    calls = []

    def matcher(filename):
        calls.append(filename)
        return True

    fr = FileRenamer(str(tmp_path), test=False, preserve_alpha=False)
    # Pre-scan restricted to just "a.txt"; the matcher itself is never consulted
    # because an explicit ``filenames`` list is supplied.
    fr.rename_by_ctime(matcher, "ct_", recursive=False, filenames=["a.txt"])

    assert calls == []
    names = {p.name for p in tmp_path.iterdir()}
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()
    assert any(n.startswith("ct_") for n in names)


def test_batch_rename_by_ctime_uses_scanned_dict_per_pattern(tmp_path, restore_cwd):
    (tmp_path / "one.txt").write_text("x", encoding="utf-8")
    (tmp_path / "two.md").write_text("x", encoding="utf-8")

    fr = FileRenamer(str(tmp_path), test=False, preserve_alpha=False)
    mappings = {"*.txt": "t_", "*.md": "m_"}
    scanned = fr.scan_mappings(mappings, recursive=False)
    fr.batch_rename_by_ctime(mappings, recursive=False, scanned=scanned)

    names = {p.name for p in tmp_path.iterdir()}
    assert any(n.startswith("t_") and n.endswith(".txt") for n in names)
    assert any(n.startswith("m_") and n.endswith(".md") for n in names)
