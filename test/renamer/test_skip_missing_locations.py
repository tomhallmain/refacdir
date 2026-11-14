"""``BatchRenamer(skip_missing_locations=...)``: whether a missing location root
fails the whole renamer group or is skipped while the other locations run."""

import pytest

from refacdir.batch import BatchArgs
from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.filename_ops import FilenameMappingDefinition


def _renamer(locations, skip_missing_locations):
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.txt", "rename_tag": "r_"}]
    )
    return BatchRenamer(
        "skip_missing",
        mappings,
        locations,
        test=False,
        skip_confirm=True,
        recursive=False,
        skip_missing_locations=skip_missing_locations,
    )


def test_missing_location_fails_group_by_default(tmp_path):
    present = tmp_path / "present"
    present.mkdir()
    (present / "a.txt").write_text("a", encoding="utf-8")
    missing = tmp_path / "missing"

    br = _renamer([Location(str(missing)), Location(str(present))], skip_missing_locations=False)
    with pytest.raises(Exception, match="Invalid root directory"):
        br.rename_by_mtime()
    assert (present / "a.txt").exists()


def test_missing_location_is_skipped_when_enabled(tmp_path):
    present = tmp_path / "present"
    present.mkdir()
    (present / "a.txt").write_text("a", encoding="utf-8")
    missing = tmp_path / "missing"

    br = _renamer([Location(str(missing)), Location(str(present))], skip_missing_locations=True)
    br.rename_by_mtime()

    assert not (present / "a.txt").exists()
    assert any(f.name.startswith("r_") for f in present.iterdir())
    assert [loc.root for loc in br.locations] == [Location(str(present)).root]


def test_all_locations_missing_still_fails_when_enabled(tmp_path):
    br = _renamer(
        [Location(str(tmp_path / "gone1")), Location(str(tmp_path / "gone2"))],
        skip_missing_locations=True,
    )
    with pytest.raises(Exception, match="None of the locations"):
        br.rename_by_mtime()


def test_missing_location_is_skipped_in_dry_run_when_enabled(tmp_path):
    present = tmp_path / "present"
    present.mkdir()
    (present / "a.txt").write_text("a", encoding="utf-8")

    br = _renamer([Location(str(tmp_path / "missing")), Location(str(present))], skip_missing_locations=True)
    br.test = True
    br.rename_by_mtime()
    assert (present / "a.txt").exists()


def test_batch_args_default_is_off():
    args = BatchArgs(configs={"configs/unused.yaml": True})
    assert args.skip_missing_locations is False
