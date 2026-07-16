"""
Tests for the ``chain_parenthetical_indices`` checkbox in ``RenamerActionDialog``'s
rule editor — the UI-facing counterpart of the same YAML mapping option.
"""

from __future__ import annotations

import pytest

from refacdir.batch import ActionType
from ui.config_action_dialogs import RenamerActionDialog

pytestmark = pytest.mark.ui


def test_new_rule_persists_chain_parenthetical_indices_flag(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog.rule_search_edit.setText("report.pdf")
    dialog.rule_tag_edit.setText("Report_")
    dialog.rule_chain_check.setChecked(True)
    dialog._on_upsert_rule()

    assert dialog._rules[0]["chain_parenthetical_indices"] is True


def test_rule_without_chain_checkbox_omits_the_key(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog.rule_search_edit.setText("notes.txt")
    dialog.rule_tag_edit.setText("Notes_")
    dialog._on_upsert_rule()

    assert "chain_parenthetical_indices" not in dialog._rules[0]


def test_selecting_a_chained_rule_checks_the_box_and_shows_hint(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._rules = [
        {
            "search_patterns": "report.pdf",
            "rename_tag": "Report_",
            "chain_parenthetical_indices": True,
        }
    ]
    dialog._refresh_rules_list()
    dialog.rules_list.setCurrentRow(0)

    assert dialog.rule_chain_check.isChecked() is True
    assert "chained" in dialog.rules_list.item(0).text()


def test_selecting_a_plain_rule_unchecks_the_box(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._rules = [
        {"search_patterns": "report.pdf", "rename_tag": "Report_"},
        {
            "search_patterns": "notes.txt",
            "rename_tag": "Notes_",
            "chain_parenthetical_indices": True,
        },
    ]
    dialog._refresh_rules_list()

    dialog.rules_list.setCurrentRow(1)
    assert dialog.rule_chain_check.isChecked() is True

    dialog.rules_list.setCurrentRow(0)
    assert dialog.rule_chain_check.isChecked() is False
