"""
Regression tests: ``FileRenamer.find_matches`` must apply a case-sensitive glob
recheck for plain-string patterns, not rely solely on ``glob.glob``'s OS-level
enumeration.

On a case-insensitive filesystem (e.g. Windows/NTFS), ``glob.glob("default*")``
also returns "DEFAULT_x.jpg" for a file actually named that way. Before the fix,
a plain-string search pattern with no ``exclude_patterns``/``chain_parenthetical_indices``
(the common/default case for a mapping) had no ``test_func`` at all in
``find_matches``, so that OS-level case-insensitive match went straight through
uncorrected: a file already renamed to "DEFAULT_1.jpg" kept popping up as a
fresh rename candidate for a "default" pattern on every subsequent run, even
though the two names differ only in case.

This repo's test/CI filesystem is case-sensitive, so ``glob.glob`` itself won't
reproduce the OS-level case-insensitive behavior here — it's stubbed out below
to simulate what a case-insensitive filesystem's scan would return.

Note: on a real case-insensitive filesystem, "default_1.jpg" and "DEFAULT_1.jpg"
can never coexist as two separate directory entries — writing the second just
overwrites the first (same underlying file). Each test below therefore only
ever creates ONE real on-disk file and uses the stub to make ``glob.glob``
additionally *report* a case-variant name for it, mirroring what a real
case-insensitive scan does: it resolves the same file under multiple cased
patterns without there being multiple files.
"""

import os

import pytest

import refacdir.file_renamer as file_renamer_module
from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.file_renamer import FileRenamer
from refacdir.filename_ops import FilenameMappingDefinition


@pytest.fixture
def restore_cwd():
    cwd = os.getcwd()
    yield
    try:
        os.chdir(cwd)
    except OSError:
        pass


class _StubGlobModule:
    """Stands in for a case-insensitive OS-level glob scan (e.g. Windows/NTFS)."""

    def __init__(self, filenames):
        self._filenames = filenames

    def glob(self, pattern, **kwargs):
        return list(self._filenames)


def test_find_matches_rejects_case_mismatched_glob_result(tmp_path, restore_cwd, monkeypatch):
    # Only ONE real file — "DEFAULT_1.jpg" — already renamed to the target case.
    (tmp_path / "DEFAULT_1.jpg").write_text("a", encoding="utf-8")

    # Simulate a case-insensitive OS-level scan for "default*" surfacing that
    # same file under its real (differently-cased) name.
    monkeypatch.setattr(
        file_renamer_module, "glob", _StubGlobModule(["DEFAULT_1.jpg"])
    )

    fr = FileRenamer(str(tmp_path))
    matches = fr.find_matches("default", recursive=False)

    assert matches == []


def test_find_matches_still_accepts_correctly_cased_match(tmp_path, restore_cwd, monkeypatch):
    (tmp_path / "default_1.jpg").write_text("a", encoding="utf-8")

    monkeypatch.setattr(
        file_renamer_module, "glob", _StubGlobModule(["default_1.jpg"])
    )

    fr = FileRenamer(str(tmp_path))
    matches = fr.find_matches("default", recursive=False)

    assert matches == ["default_1.jpg"]


def test_find_matches_case_check_is_prefix_based_like_get_glob_pattern(tmp_path, restore_cwd, monkeypatch):
    """The case-sensitive recheck must still allow the implied trailing '*' (any suffix)."""
    (tmp_path / "default_17271447710100000.jpg").write_text("a", encoding="utf-8")

    monkeypatch.setattr(
        file_renamer_module, "glob", _StubGlobModule(["default_17271447710100000.jpg"])
    )

    fr = FileRenamer(str(tmp_path))
    matches = fr.find_matches("default", recursive=False)

    assert matches == ["default_17271447710100000.jpg"]


def test_construct_mappings_plain_pattern_stays_unwrapped_string(tmp_path, restore_cwd):
    """
    A mapping with only a plain ``search_patterns`` string (no exclude_patterns,
    no chain_parenthetical_indices — the common/default case) is intentionally
    kept as a raw string key by ``construct_mappings`` (see auto rename-tag
    derivation), not wrapped in a callable. The case-sensitivity fix therefore
    has to live in ``FileRenamer.find_matches`` itself, not in a matcher wrapper.
    """
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "default", "rename_tag": "DEFAULT_"}]
    )
    assert mappings == {"default": "DEFAULT_"}


def test_batch_renamer_does_not_reprocess_case_mismatched_already_renamed_file(
    tmp_path, restore_cwd, monkeypatch
):
    """
    End-to-end guard for the reported bug: a file already renamed to the target
    case ("DEFAULT_1.jpg") must not keep matching a mapping meant for the
    pre-rename case ("default") just because the OS-level scan is case-insensitive.
    """
    (tmp_path / "DEFAULT_1.jpg").write_text("a", encoding="utf-8")

    monkeypatch.setattr(
        file_renamer_module, "glob", _StubGlobModule(["DEFAULT_1.jpg"])
    )

    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "default", "rename_tag": "DEFAULT_"}]
    )
    br = BatchRenamer(
        "unit",
        mappings,
        [Location(str(tmp_path))],
        test=False,
        skip_confirm=True,
        recursive=False,
    )
    br.rename_by_ctime()

    # No match, no rename: the file is left exactly as it was, not re-stamped
    # with a fresh timestamp under a "new" DEFAULT_<ctime>.jpg name. (tmp_path
    # also holds "cache"/"configs" dirs from the autouse isolated_app_singletons
    # fixture, so scope this to just the .jpg files.)
    jpg_names = {p.name for p in tmp_path.iterdir() if p.suffix == ".jpg"}
    assert jpg_names == {"DEFAULT_1.jpg"}
