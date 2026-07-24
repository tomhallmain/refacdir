"""
Tests for the fix to a file-not-found race: ``BatchRenamer.execute()`` scans
every pattern in a mapping exactly once, up front, before any rename runs.
If two patterns in the same mapping both match the same file, the first
pattern to be processed renames it away, and the next pattern would then try
to act on a name that no longer exists — raising and aborting the whole
action (see ``refacdir.batch``'s "renamer ... failed: [WinError 2]" log).

Covered here:
  - ``BatchRenamer._dedupe_cross_pattern_matches`` assigns each matched file
    to only the first pattern (in mapping order) that claimed it.
  - End-to-end: a mapping with two overlapping patterns renames the shared
    file exactly once instead of raising.
  - ``FileRenamer.rename_by_func``'s reactive fallback: a pre-scanned
    ``filenames`` entry that's already gone by the time its pattern's turn
    comes up is skipped, not raised.
"""

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.file_renamer import FileRenamer
from refacdir.filename_ops import FilenameMappingDefinition


def test_dedupe_keeps_a_shared_match_under_the_first_pattern_only():
    scanned_by_location = {
        "loc": {
            "report*": ["report.pdf", "report_final.pdf"],
            "report.pdf": ["report.pdf"],
        }
    }
    BatchRenamer._dedupe_cross_pattern_matches(scanned_by_location)
    assert scanned_by_location["loc"]["report*"] == ["report.pdf", "report_final.pdf"]
    assert scanned_by_location["loc"]["report.pdf"] == []


def test_dedupe_is_a_no_op_when_patterns_dont_overlap():
    scanned_by_location = {
        "loc": {
            "a*": ["a1.txt"],
            "b*": ["b1.txt"],
        }
    }
    BatchRenamer._dedupe_cross_pattern_matches(scanned_by_location)
    assert scanned_by_location["loc"]["a*"] == ["a1.txt"]
    assert scanned_by_location["loc"]["b*"] == ["b1.txt"]


def test_overlapping_patterns_in_one_mapping_rename_the_shared_file_once(tmp_path):
    (tmp_path / "report.pdf").write_text("a", encoding="utf-8")

    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {"search_patterns": "report", "rename_tag": "broad_"},
            {"search_patterns": "report.pdf", "rename_tag": "specific_"},
        ]
    )
    br = BatchRenamer(
        "unit", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    br.rename_by_ctime()

    names = {p.name for p in tmp_path.iterdir()}
    renamed = [n for n in names if n.startswith("broad_") or n.startswith("specific_")]
    assert len(renamed) == 1
    assert not (tmp_path / "report.pdf").exists()


def test_rename_by_func_skips_a_prescanned_file_that_no_longer_exists(tmp_path):
    """
    ``filenames`` here stands in for a stale pre-scanned list (e.g. from
    BatchRenamer.execute()'s single upfront scan) where "gone_already.txt"
    was already renamed/removed by something else before this call runs.
    Processing it should not raise — it should just be skipped, leaving the
    still-present file to be renamed normally.
    """
    (tmp_path / "still_here.txt").write_text("a", encoding="utf-8")
    fr = FileRenamer(root=str(tmp_path), test=False)

    fr.rename_by_mtime(
        "*.txt", "renamed_", filenames=["gone_already.txt", "still_here.txt"],
    )

    names = {p.name for p in tmp_path.iterdir()}
    assert "gone_already.txt" not in names
    assert not (tmp_path / "still_here.txt").exists()
    assert any(n.startswith("renamed_") for n in names)
