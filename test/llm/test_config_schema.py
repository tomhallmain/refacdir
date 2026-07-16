"""
Tests for ``refacdir/llm/config_schema.py`` — the prompt-facing schema
description assembled from ``BatchJob.construct_*`` docstrings (Phase 1,
docs/LLM_CONFIG_CHAT_SCOPE.md).

These double as a staleness tripwire: if a construct_* docstring gets gutted
or a schema keyword renamed without updating it, the keyword-presence checks
below should catch it, since they read from the SAME docstrings a real prompt
would use, not a separately hand-maintained copy.
"""

import pytest

from refacdir.batch import ActionType
from refacdir.llm.config_schema import (
    get_full_schema_description,
    get_schema_description,
    get_shared_vocabulary_description,
    supported_action_types,
)

_EXPECTED_SUPPORTED = {
    ActionType.RENAMER,
    ActionType.BACKUP,
    ActionType.DUPLICATE_REMOVER,
    ActionType.DIRECTORY_OBSERVER,
    ActionType.DIRECTORY_FLATTENER,
    ActionType.NAMED_SUBDIR_COLLECTOR,
}


def test_supported_action_types_matches_expected_set():
    assert set(supported_action_types()) == _EXPECTED_SUPPORTED


def test_image_categorizer_is_excluded():
    assert ActionType.IMAGE_CATEGORIZER not in supported_action_types()


def test_get_schema_description_raises_for_image_categorizer():
    with pytest.raises(ValueError):
        get_schema_description(ActionType.IMAGE_CATEGORIZER)


@pytest.mark.parametrize("action_type", sorted(_EXPECTED_SUPPORTED, key=lambda a: a.name))
def test_schema_description_is_substantial_for_every_supported_action_type(action_type):
    """Staleness tripwire: catches a docstring accidentally gutted to near-nothing."""
    description = get_schema_description(action_type)
    assert isinstance(description, str)
    assert len(description) > 200


def test_renamer_schema_mentions_direct_fields():
    """Fields construct_batch_renamer's own docstring documents directly."""
    description = get_schema_description(ActionType.RENAMER)
    for keyword in ("function", "locations", "mappings"):
        assert keyword in description


def test_renamer_full_schema_mentions_pattern_rule_fields():
    """search_patterns/rename_tag live one level down, on the pattern-rule dicts
    inside a renamer group's ``mappings`` list — documented in
    FilenameMappingDefinition.construct_mappings's docstring (shared
    vocabulary), not duplicated in construct_batch_renamer's own docstring.
    Only the combined description carries both."""
    description = get_full_schema_description(ActionType.RENAMER)
    for keyword in ("search_patterns", "rename_tag"):
        assert keyword in description


def test_backup_schema_mentions_required_fields_and_modes():
    description = get_schema_description(ActionType.BACKUP)
    for keyword in (
        "source_dir", "target_dir", "file_types", "hash_mode",
        "MIRROR", "PUSH_AND_REMOVE", "SHA256", "FILENAME",
    ):
        assert keyword in description


def test_duplicate_remover_schema_mentions_required_fields():
    description = get_schema_description(ActionType.DUPLICATE_REMOVER)
    for keyword in ("source_dirs", "preferred_delete_dirs", "use_hash_cache"):
        assert keyword in description


def test_directory_observer_schema_mentions_required_fields():
    description = get_schema_description(ActionType.DIRECTORY_OBSERVER)
    for keyword in ("sortable_dirs", "extra_dirs", "parent_dirs"):
        assert keyword in description


def test_directory_flattener_schema_mentions_required_fields():
    description = get_schema_description(ActionType.DIRECTORY_FLATTENER)
    for keyword in ("location", "search_patterns"):
        assert keyword in description


def test_named_subdir_collector_schema_mentions_required_fields():
    description = get_schema_description(ActionType.NAMED_SUBDIR_COLLECTOR)
    for keyword in ("root", "subdir_names", "clear_sources", "subdir_depth"):
        assert keyword in description


def test_shared_vocabulary_mentions_key_concepts():
    description = get_shared_vocabulary_description()
    for keyword in (
        "USER_HOME",
        "exclude_dirs",
        "chain_parenthetical_indices",
        "{{type:arg1:arg2",
        "filetype_definitions",
        "filename_mapping_functions",
    ):
        assert keyword in description


def test_full_schema_description_combines_shared_and_specific():
    description = get_full_schema_description(ActionType.RENAMER)
    # Shared vocabulary (Location) ...
    assert "USER_HOME" in description
    # ... and the renamer-specific schema.
    assert "rename_tag" in description


def test_full_schema_description_raises_for_unsupported_action_type():
    with pytest.raises(ValueError):
        get_full_schema_description(ActionType.IMAGE_CATEGORIZER)
