"""
Tests for refacdir/llm/preview.py — the Phase 4 match/affected-file preview
for a validated LLM-drafted action dict (docs/LLM_CONFIG_CHAT_SCOPE.md).

Each action type gets one real-directory case (confirming the preview
actually reuses that action type's own scan mechanism and finds real matches)
plus, where relevant, a "does not touch disk" or "nonexistent path is
reported gracefully" case.
"""

import pytest

from refacdir.batch import ActionType
from refacdir.llm.preview import preview_action

_NONEXISTENT_PATH = "/definitely/does/not/exist/anywhere/refacdir-llm-tests"


def test_preview_raises_for_image_categorizer():
    with pytest.raises(ValueError):
        preview_action(ActionType.IMAGE_CATEGORIZER, {"name": "x"})


def test_renamer_preview_finds_matching_files(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.doc").write_text("x", encoding="utf-8")
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": str(tmp_path)}],
    }
    result = preview_action(ActionType.RENAMER, action_dict)
    assert result.available is True
    location_key = str(tmp_path)
    rules = result.details[location_key]
    assert len(rules) == 1
    assert rules[0]["matched_files"] == ["a.txt"]
    # Read-only.
    assert (tmp_path / "a.txt").exists()


def test_renamer_preview_does_not_rename_anything(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": str(tmp_path)}],
    }
    preview_action(ActionType.RENAMER, action_dict)
    assert not any(f.name.startswith("renamed_") for f in tmp_path.iterdir())


def test_renamer_preview_on_nonexistent_location_is_unavailable_not_raised():
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    result = preview_action(ActionType.RENAMER, action_dict)
    assert result.available is False
    assert result.reason


def test_directory_flattener_preview_finds_nested_files(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "f.txt").write_text("x", encoding="utf-8")
    action_dict = {"name": "Test flattener", "location": {"root": str(tmp_path)}}
    result = preview_action(ActionType.DIRECTORY_FLATTENER, action_dict)
    assert result.available is True
    all_matched = [f for rules in result.details.values() for rule in rules for f in rule["matched_files"]]
    assert any(f.endswith("f.txt") for f in all_matched)
    # Read-only: file must still be in its original nested location.
    assert (nested / "f.txt").exists()


def test_backup_preview_reports_new_file(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    action_dict = {
        "name": "Test backup",
        "backup_mappings": [
            {"name": "Mapping 1", "source_dir": str(source), "target_dir": str(target), "file_types": [".txt"]}
        ],
    }
    result = preview_action(ActionType.BACKUP, action_dict)
    assert result.available is True
    changes = result.details["Mapping 1"]
    assert len(changes["to_add_or_update"]) == 1
    # Read-only.
    assert not (target / "a.txt").exists()


def test_duplicate_remover_preview_finds_duplicate_group(tmp_path):
    (tmp_path / "a.txt").write_text("same content", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same content", encoding="utf-8")
    # use_hash_cache=False: avoid touching the real cross-run app_info_cache
    # from a test, matching test/duplicate_remover/test_duplicate_remover.py's
    # own convention.
    action_dict = {"name": "Test dedup", "source_dirs": [str(tmp_path)], "use_hash_cache": False}
    result = preview_action(ActionType.DUPLICATE_REMOVER, action_dict)
    assert result.available is True
    assert result.details["total_duplicate_files"] == 1
    # Read-only.
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()


def test_directory_observer_preview_counts_files(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    action_dict = {"name": "Test observer", "extra_dirs": [str(tmp_path)], "file_types": [".txt"]}
    result = preview_action(ActionType.DIRECTORY_OBSERVER, action_dict)
    assert result.available is True
    counts = result.details[str(tmp_path)]
    assert counts[".txt"] == 1


def test_named_subdir_collector_preview_lists_work_items(tmp_path):
    root = tmp_path / "root"
    nested = root / "X" / "A"
    nested.mkdir(parents=True)
    f = nested / "keep.txt"
    f.write_text("data", encoding="utf-8")
    action_dict = {"name": "Test collector", "root": str(root), "subdir_names": ["A"]}
    result = preview_action(ActionType.NAMED_SUBDIR_COLLECTOR, action_dict)
    assert result.available is True
    assert result.details["work_items"] == [("A", str(f))]
    # Read-only.
    assert f.exists()
