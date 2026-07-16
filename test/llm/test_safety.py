"""
Tests for refacdir/llm/safety.py — forcing every LLM-drafted action into its
safest dry-run/confirmation state (Phase 4, docs/LLM_CONFIG_CHAT_SCOPE.md).
"""

import pytest

from refacdir.batch import ActionType
from refacdir.llm.safety import apply_safety_defaults


@pytest.mark.parametrize(
    "action_type",
    [ActionType.RENAMER, ActionType.BACKUP, ActionType.DIRECTORY_FLATTENER, ActionType.NAMED_SUBDIR_COLLECTOR],
)
def test_forces_test_true_regardless_of_draft_value(action_type):
    result = apply_safety_defaults(action_type, {"name": "x", "test": False})
    assert result["test"] is True


@pytest.mark.parametrize(
    "action_type",
    [ActionType.RENAMER, ActionType.BACKUP, ActionType.DIRECTORY_FLATTENER, ActionType.NAMED_SUBDIR_COLLECTOR],
)
def test_forces_test_true_when_absent_from_draft(action_type):
    result = apply_safety_defaults(action_type, {"name": "x"})
    assert result["test"] is True


def test_duplicate_remover_forces_skip_confirm_false():
    result = apply_safety_defaults(
        ActionType.DUPLICATE_REMOVER, {"name": "x", "skip_confirm": True}
    )
    assert result["skip_confirm"] is False
    assert "test" not in result


def test_directory_observer_is_returned_unchanged():
    original = {"name": "x", "extra_dirs": ["/some/path"]}
    result = apply_safety_defaults(ActionType.DIRECTORY_OBSERVER, original)
    assert result == original


def test_returns_a_copy_not_the_original_dict():
    original = {"name": "x"}
    result = apply_safety_defaults(ActionType.RENAMER, original)
    assert result is not original
    assert "test" not in original


def test_raises_for_image_categorizer():
    with pytest.raises(ValueError):
        apply_safety_defaults(ActionType.IMAGE_CATEGORIZER, {"name": "x"})
