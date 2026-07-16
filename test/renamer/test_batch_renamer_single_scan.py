"""
Regression tests: ``BatchRenamer.execute()`` must analyze each file against a
given renamer job mapping exactly once per real (non-test) run.

Before this fix, ``execute()`` called ``found_files()`` (a scan that stopped at
the first match) and then, if it returned ``True``, ran the real rename/move
operation, which always re-scanned every file from scratch and re-evaluated
every mapping's matcher again. For callable-based mappings (e.g. custom search
functions such as ``is_id_filename``, or any mapping with ``exclude_patterns``,
which are wrapped into a callable matcher) that meant a matcher already known
to be expensive could run twice over the same file.
"""

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.filename_ops import FilenameMappingDefinition


def _counting_matcher(matching_names):
    """Return a matcher that records every filename it's asked about."""
    calls = []

    def matcher(filename):
        calls.append(filename)
        return filename in matching_names

    matcher.calls = calls
    return matcher


def test_real_run_analyzes_each_file_once_per_mapping(tmp_path):
    names = [f"file_{i}.txt" for i in range(5)]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")

    # Only the last file matches, so a full directory scan is unavoidable either way.
    matcher = _counting_matcher({names[-1]})
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": matcher, "rename_tag": "seen_"}]
    )
    br = BatchRenamer(
        "unit", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    br.rename_by_ctime()

    # Exactly one analysis per file: 5 files -> 5 matcher calls total, not 10
    # (a found_files() pre-check plus a second full scan during the real operation).
    assert len(matcher.calls) == 5
    assert sorted(matcher.calls) == sorted(names)
    assert any(f.name.startswith("seen_") for f in tmp_path.iterdir())


def test_scan_is_a_public_read_only_preview_of_execute(tmp_path):
    """``scan()`` (extracted from ``execute()``'s single-scan pass so it can be
    called independently, e.g. by refacdir/llm/preview.py's Phase 4 preview)
    must find matches without moving/renaming anything, regardless of
    ``test``."""
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.doc").write_text("x", encoding="utf-8")
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.txt", "rename_tag": "seen_"}]
    )
    location = Location(str(tmp_path))
    br = BatchRenamer("scan-check", mappings, [location], test=True, skip_confirm=True, recursive=False)

    scanned = br.scan()

    assert set(scanned.keys()) == {location}
    matched_files = [files for files in scanned[location].values()]
    assert matched_files == [["a.txt"]]
    # Read-only: nothing renamed even though a match was found.
    assert (tmp_path / "a.txt").exists()
    assert not any(f.name.startswith("seen_") for f in tmp_path.iterdir())


def test_multi_location_any_found_across_locations(tmp_path):
    """A match in the second location must still trigger the run."""
    loc_a = tmp_path / "a"
    loc_b = tmp_path / "b"
    loc_a.mkdir()
    loc_b.mkdir()
    (loc_b / "only_here.txt").write_text("x", encoding="utf-8")

    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.txt", "rename_tag": "hit_"}]
    )
    br = BatchRenamer(
        "multi", mappings, [Location(str(loc_a)), Location(str(loc_b))],
        test=False, skip_confirm=True, recursive=False,
    )
    br.rename_by_ctime()

    assert any(f.name.startswith("hit_") for f in loc_b.iterdir())


def test_no_files_found_scans_once_and_does_not_prompt(tmp_path):
    (tmp_path / "unmatched.txt").write_text("x", encoding="utf-8")

    matcher = _counting_matcher(set())  # never matches
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": matcher, "rename_tag": "seen_"}]
    )
    br = BatchRenamer(
        "unit", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=False, recursive=False,
    )
    # skip_confirm=False would block on input() if execute() reached the
    # confirmation prompt; returning from this call at all (no hang, no
    # exception) confirms the "no files found" path returned before prompting.
    br.rename_by_ctime()

    assert len(matcher.calls) == 1
    assert not any(f.name.startswith("seen_") for f in tmp_path.iterdir())


def test_no_files_found_logs_warning_and_skips_started_message(tmp_path, caplog):
    matcher = _counting_matcher(set())
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": matcher, "rename_tag": "seen_"}]
    )
    br = BatchRenamer(
        "warn-check", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    with caplog.at_level("INFO"):
        br.rename_by_ctime()

    messages = [record.message for record in caplog.records]
    assert any("No files found" in m for m in messages)
    assert not any("BATCH RENAME PROCESS STARTED" in m for m in messages)


def test_files_found_logs_started_and_complete(tmp_path, caplog):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.txt", "rename_tag": "seen_"}]
    )
    br = BatchRenamer(
        "log-check", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    with caplog.at_level("INFO"):
        br.rename_by_ctime()

    messages = [record.message for record in caplog.records]
    assert any("BATCH RENAME PROCESS STARTED" in m for m in messages)
    assert any("BATCH RENAME PROCESS COMPLETE" in m for m in messages)
