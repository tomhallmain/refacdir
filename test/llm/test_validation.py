"""
Tests for ``refacdir/llm/validation.py`` — the "dry construct" harness that
validates an LLM-drafted action dict by running it through the real
``BatchJob.construct_*`` method (Phase 2, docs/LLM_CONFIG_CHAT_SCOPE.md).

Covers, per supported action type: a valid draft with a NONEXISTENT path
(confirming construction doesn't require the real world to already match —
most action types resolve paths lazily, at execution time, not construction
time) and at least one genuinely structural error. Two action types
(DUPLICATE_REMOVER, DIRECTORY_OBSERVER) DO check some paths eagerly; those are
covered separately to confirm they're classified as warnings, not errors.
"""

import pytest

from refacdir.batch import ActionType
from refacdir.batch_renamer import BatchRenamer
from refacdir.llm.validation import ValidationResult, construct_for_action_type, validate_action

_NONEXISTENT_PATH = "/definitely/does/not/exist/anywhere/refacdir-llm-tests"


# ---------------------------------------------------------------------------
# IMAGE_CATEGORIZER exclusion
# ---------------------------------------------------------------------------

def test_validate_action_raises_for_image_categorizer():
    with pytest.raises(ValueError):
        validate_action(ActionType.IMAGE_CATEGORIZER, {"name": "x"})


# ---------------------------------------------------------------------------
# RENAMER
# ---------------------------------------------------------------------------

def test_renamer_valid_draft_does_not_require_real_paths():
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    result = validate_action(ActionType.RENAMER, action_dict)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_renamer_missing_name_is_a_structural_error():
    action_dict = {
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    result = validate_action(ActionType.RENAMER, action_dict)
    assert result.valid is False
    assert len(result.errors) == 1
    assert "name" in result.errors[0]
    assert result.error_summary() == result.errors[0]


def test_renamer_missing_rename_tag_in_nested_rule_is_a_structural_error():
    """Errors from the nested pattern-rule dicts (FilenameMappingDefinition.
    construct_mappings) must propagate up through construct_batch_renamer."""
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt"}],  # missing rename_tag
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    result = validate_action(ActionType.RENAMER, action_dict)
    assert result.valid is False
    assert "rename_tag" in result.errors[0]


def test_renamer_invalid_search_pattern_type_is_a_structural_error():
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": 12345, "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    result = validate_action(ActionType.RENAMER, action_dict)
    assert result.valid is False
    assert result.errors  # non-empty; exact message comes from filename_ops.py


# ---------------------------------------------------------------------------
# BACKUP
# ---------------------------------------------------------------------------

def test_backup_valid_draft_does_not_require_real_paths():
    action_dict = {
        "name": "Test backup",
        "backup_mappings": [
            {
                "name": "Mapping 1",
                "source_dir": _NONEXISTENT_PATH + "/source",
                "target_dir": _NONEXISTENT_PATH + "/target",
                "file_types": [".txt"],
            }
        ],
    }
    result = validate_action(ActionType.BACKUP, action_dict)
    assert result.valid is True
    assert result.errors == []


def test_backup_invalid_mode_is_a_structural_error():
    action_dict = {
        "name": "Test backup",
        "backup_mappings": [
            {
                "name": "Mapping 1",
                "source_dir": _NONEXISTENT_PATH + "/source",
                "target_dir": _NONEXISTENT_PATH + "/target",
                "file_types": [".txt"],
                "mode": "NOT_A_REAL_MODE",
            }
        ],
    }
    result = validate_action(ActionType.BACKUP, action_dict)
    assert result.valid is False
    assert result.errors


def test_backup_missing_backup_mappings_is_a_structural_error():
    result = validate_action(ActionType.BACKUP, {"name": "Test backup"})
    assert result.valid is False
    assert "backup_mappings" in result.errors[0]


# ---------------------------------------------------------------------------
# DUPLICATE_REMOVER — source_dirs isn't checked eagerly, exclude_dirs/
# preferred_delete_dirs are (and become warnings, not errors).
# ---------------------------------------------------------------------------

def test_duplicate_remover_valid_draft_does_not_require_real_source_dirs():
    action_dict = {"name": "Test dedup", "source_dirs": [_NONEXISTENT_PATH]}
    result = validate_action(ActionType.DUPLICATE_REMOVER, action_dict)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_duplicate_remover_nonexistent_exclude_dir_is_a_warning_not_an_error(tmp_path):
    action_dict = {
        "name": "Test dedup",
        "source_dirs": [str(tmp_path)],
        "exclude_dirs": [_NONEXISTENT_PATH],
    }
    result = validate_action(ActionType.DUPLICATE_REMOVER, action_dict)
    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "exclude directory" in result.warnings[0].lower()


def test_duplicate_remover_missing_source_dirs_is_a_structural_error():
    result = validate_action(ActionType.DUPLICATE_REMOVER, {"name": "Test dedup"})
    assert result.valid is False
    assert "source_dirs" in result.errors[0]


# ---------------------------------------------------------------------------
# DIRECTORY_OBSERVER — every directory list IS checked eagerly.
# ---------------------------------------------------------------------------

def test_directory_observer_valid_draft_with_real_dir(tmp_path):
    action_dict = {"name": "Test observer", "extra_dirs": [str(tmp_path)]}
    result = validate_action(ActionType.DIRECTORY_OBSERVER, action_dict)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_directory_observer_nonexistent_dir_is_a_warning_not_an_error():
    action_dict = {"name": "Test observer", "extra_dirs": [_NONEXISTENT_PATH]}
    result = validate_action(ActionType.DIRECTORY_OBSERVER, action_dict)
    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "invalid directory provided" in result.warnings[0].lower()


# ---------------------------------------------------------------------------
# DIRECTORY_FLATTENER
# ---------------------------------------------------------------------------

def test_directory_flattener_valid_draft_does_not_require_real_paths():
    action_dict = {
        "name": "Test flattener",
        "location": {"root": _NONEXISTENT_PATH},
    }
    result = validate_action(ActionType.DIRECTORY_FLATTENER, action_dict)
    assert result.valid is True
    assert result.errors == []


def test_directory_flattener_missing_location_is_a_structural_error():
    result = validate_action(ActionType.DIRECTORY_FLATTENER, {"name": "Test flattener"})
    assert result.valid is False
    assert result.errors


# ---------------------------------------------------------------------------
# NAMED_SUBDIR_COLLECTOR
# ---------------------------------------------------------------------------

def test_named_subdir_collector_valid_draft_does_not_require_real_paths():
    action_dict = {
        "name": "Test collector",
        "root": _NONEXISTENT_PATH,
        "subdir_names": ["A", "B"],
    }
    result = validate_action(ActionType.NAMED_SUBDIR_COLLECTOR, action_dict)
    assert result.valid is True
    assert result.errors == []


def test_named_subdir_collector_empty_subdir_names_is_a_structural_error():
    action_dict = {
        "name": "Test collector",
        "root": _NONEXISTENT_PATH,
        "subdir_names": [],
    }
    result = validate_action(ActionType.NAMED_SUBDIR_COLLECTOR, action_dict)
    assert result.valid is False
    assert result.errors


# ---------------------------------------------------------------------------
# construct_for_action_type — shared building block also used by
# refacdir/llm/preview.py (Phase 4) to get the actual constructed object.
# ---------------------------------------------------------------------------

def test_construct_for_action_type_returns_the_real_constructed_object():
    action_dict = {
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    }
    renamer, renamer_function = construct_for_action_type(ActionType.RENAMER, action_dict)
    assert isinstance(renamer, BatchRenamer)
    assert renamer_function == "rename_by_ctime"


def test_construct_for_action_type_raises_for_image_categorizer():
    with pytest.raises(ValueError):
        construct_for_action_type(ActionType.IMAGE_CATEGORIZER, {"name": "x"})


def test_construct_for_action_type_lets_construction_errors_propagate():
    with pytest.raises(KeyError):
        construct_for_action_type(ActionType.RENAMER, {})


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

def test_validation_result_error_summary_joins_multiple_errors():
    result = ValidationResult(
        action_type=ActionType.RENAMER, valid=False, errors=["first", "second"]
    )
    assert result.error_summary() == "first\nsecond"
