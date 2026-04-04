"""``BatchRenamer`` with temp roots and user dry-run (``test=True`` on the renamer)."""

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.filename_ops import FilenameMappingDefinition


def test_batch_renamer_rename_by_mtime_dry_run_does_not_rename(tmp_path):
    """``BatchRenamer(test=True)`` mirrors user dry-run: no on-disk renames."""
    (tmp_path / "one.txt").write_text("a", encoding="utf-8")
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.txt", "rename_tag": "batch_"}]
    )
    br = BatchRenamer(
        "unit",
        mappings,
        [Location(str(tmp_path))],
        test=True,
        skip_confirm=True,
        recursive=False,
    )
    br.rename_by_mtime()
    assert (tmp_path / "one.txt").exists()
    assert not any(f.name.startswith("batch_") for f in tmp_path.iterdir())


def test_batch_renamer_rename_by_ctime_runs_without_confirm_when_skip_confirm(tmp_path):
    """``skip_confirm=True`` avoids blocking on input; real renames use ``test=False``."""
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "*.md", "rename_tag": "c_"}]
    )
    br = BatchRenamer(
        "unit2",
        mappings,
        [Location(str(tmp_path))],
        test=False,
        skip_confirm=True,
        recursive=False,
    )
    br.rename_by_ctime()
    assert not (tmp_path / "note.md").exists()
    assert any(f.name.startswith("c_") and f.suffix == ".md" for f in tmp_path.iterdir())
