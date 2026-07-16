"""
Tests for ``RenamerActionDialog._apply_suggested_rule`` — applying a suggestion
(static preset or directory-detected) picked in ``RenamerRuleSuggesterDialog``
to the rule currently being edited.
"""

from __future__ import annotations

import pytest

from refacdir.batch import ActionType
from ui.config_action_dialogs import RenamerActionDialog

pytestmark = pytest.mark.ui


def test_applies_pattern_and_rename_tag_to_blank_fields(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_suggested_rule(
        {"search_patterns": "{{is_short_integer_filename}}", "rename_tag": "int_"}
    )

    assert dialog.rule_search_edit.text() == "{{is_short_integer_filename}}"
    assert dialog.rule_tag_edit.text() == "int_"


def test_does_not_overwrite_an_already_filled_rename_tag(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog.rule_tag_edit.setText("my_custom_tag_")
    dialog._apply_suggested_rule(
        {"search_patterns": "{{is_short_integer_filename}}", "rename_tag": "int_"}
    )

    assert dialog.rule_tag_edit.text() == "my_custom_tag_"


def test_pattern_without_rename_tag_key_does_not_touch_tag_field(qtbot):
    """Directory-detected suggestions carry no rename_tag key at all."""
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_suggested_rule({"search_patterns": "foo"})

    assert dialog.rule_search_edit.text() == "foo"
    assert dialog.rule_tag_edit.text() == ""


def test_second_pattern_is_appended_comma_separated(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_suggested_rule({"search_patterns": "foo"})
    dialog._apply_suggested_rule({"search_patterns": "bar"})

    assert dialog.rule_search_edit.text() == "foo, bar"


def test_duplicate_pattern_is_not_appended_twice(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_suggested_rule({"search_patterns": "foo"})
    dialog._apply_suggested_rule({"search_patterns": "foo"})

    assert dialog.rule_search_edit.text() == "foo"


def test_blank_pattern_is_ignored(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_suggested_rule({"search_patterns": "  "})

    assert dialog.rule_search_edit.text() == ""
