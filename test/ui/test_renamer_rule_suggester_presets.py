"""
Tests for the "Common Patterns" static preset section of ``RenamerRuleSuggesterDialog``.

Presets must be visible immediately (no directory/Analyze needed), and nothing
gets applied to a mapping until the user explicitly selects a suggestion and
clicks OK — this covers both the preset list and the existing directory-scan
list, which must keep behaving exactly as before (pattern only, no rename_tag).
"""

from __future__ import annotations

import pytest

from ui.renamer_rule_suggester_dialog import RenamerRuleSuggesterDialog

pytestmark = pytest.mark.ui


def test_presets_are_populated_without_analyzing_a_directory(qtbot):
    dialog = RenamerRuleSuggesterDialog()
    qtbot.addWidget(dialog)

    assert dialog.preset_list.count() > 0
    assert dialog.result_rule() is None  # nothing selected yet


def test_selecting_a_preset_and_accepting_emits_pattern_and_rename_tag(qtbot):
    dialog = RenamerRuleSuggesterDialog()
    qtbot.addWidget(dialog)

    emitted = []
    dialog.rule_applied.connect(lambda payload: emitted.append(payload))

    dialog.preset_list.setCurrentRow(0)
    assert dialog.result_rule() is not None
    assert dialog.result_rule()["search_patterns"]

    dialog._accept_selected()

    assert len(emitted) == 1
    payload = emitted[0]
    assert "_source" not in payload  # internal bookkeeping key must not leak
    assert payload["search_patterns"]
    assert payload["rename_tag"]


def test_selecting_a_preset_deselects_the_detected_list_and_vice_versa(qtbot):
    dialog = RenamerRuleSuggesterDialog()
    qtbot.addWidget(dialog)

    # Fake a "detected from files" suggestion without needing a real directory scan.
    dialog._suggestions = [{"search_patterns": "foo", "reason": "test", "confidence": 50}]
    dialog.suggestion_list.addItem("1. [50%] foo (1 files, 100.0%)")

    dialog.preset_list.setCurrentRow(0)
    assert dialog.suggestion_list.currentRow() == -1
    assert dialog.result_rule()["search_patterns"] != "foo"

    dialog.suggestion_list.setCurrentRow(0)
    assert dialog.preset_list.currentRow() == -1
    assert dialog.result_rule()["search_patterns"] == "foo"


def test_detected_suggestion_payload_has_no_rename_tag_key(qtbot):
    """Preserves pre-existing behavior: directory-detected suggestions only ever
    carried a bare pattern, never a rename_tag suggestion."""
    dialog = RenamerRuleSuggesterDialog()
    qtbot.addWidget(dialog)

    dialog._suggestions = [{"search_patterns": "foo", "reason": "test", "confidence": 50}]
    dialog.suggestion_list.addItem("1. [50%] foo (1 files, 100.0%)")
    dialog.suggestion_list.setCurrentRow(0)

    emitted = []
    dialog.rule_applied.connect(lambda payload: emitted.append(payload))
    dialog._accept_selected()

    assert emitted == [{"search_patterns": "foo"}]
