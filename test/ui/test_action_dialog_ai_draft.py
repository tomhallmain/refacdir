"""
Tests for the "Draft with AI..." integration added to ``BaseActionDialog``
(Phase 5, docs/LLM_CONFIG_CHAT_SCOPE.md): opening the non-modal
``LLMConfigChatDialog`` and applying its drafted action dict as a new mapping.
"""

from __future__ import annotations

import pytest

from refacdir.batch import ActionType
from ui.config_action_dialogs import DuplicateRemoverActionDialog, ImageCategorizerActionDialog, RenamerActionDialog
from ui.llm_config_chat_dialog import LLMConfigChatDialog

pytestmark = pytest.mark.ui


def _suppress_window_display(monkeypatch):
    """
    ``_open_ai_draft_dialog`` calls show()/raise_()/activateWindow() on a real
    ``LLMConfigChatDialog`` — on platforms where the offscreen QPA platform
    isn't forced (see ``test/conftest.py``'s ``pytest_configure``, which skips
    it on win32), that would pop up a real visible window during the test
    run. Stub these out at the class level before opening the dialog, the
    same way the rest of this suite avoids ever triggering a real show().
    """
    monkeypatch.setattr(LLMConfigChatDialog, "show", lambda self: None)
    monkeypatch.setattr(LLMConfigChatDialog, "raise_", lambda self: None)
    monkeypatch.setattr(LLMConfigChatDialog, "activateWindow", lambda self: None)

_DRAFTED_RENAMER_MAPPING = {
    "name": "Test renamer",
    "function": "rename_by_ctime",
    "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
    "locations": [{"root": "/tmp/somewhere"}],
}


def test_ai_draft_button_enabled_for_supported_action_type(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    assert dialog.ai_draft_btn.isEnabled() is True


def test_ai_draft_button_disabled_for_image_categorizer(qtbot):
    dialog = ImageCategorizerActionDialog(None, ActionType.IMAGE_CATEGORIZER)
    qtbot.addWidget(dialog)

    assert dialog.ai_draft_btn.isEnabled() is False
    assert dialog.ai_draft_btn.toolTip()  # explains why, rather than silently disabled


def test_apply_ai_drafted_action_appends_a_new_mapping_and_selects_it(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)
    assert dialog._mappings == []

    dialog._apply_ai_drafted_action(dict(_DRAFTED_RENAMER_MAPPING))

    assert len(dialog._mappings) == 1
    assert dialog._mappings[0]["name"] == "Test renamer"
    assert dialog.mapping_list.count() == 1
    assert dialog.mapping_list.currentRow() == 0


def test_apply_ai_drafted_action_does_not_disturb_existing_mappings(qtbot):
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog._on_add_mapping()
    assert len(dialog._mappings) == 1

    dialog._apply_ai_drafted_action(dict(_DRAFTED_RENAMER_MAPPING))

    assert len(dialog._mappings) == 2
    assert dialog._mappings[0]["name"] != "Test renamer"
    assert dialog._mappings[1]["name"] == "Test renamer"
    assert dialog.mapping_list.currentRow() == 1


def test_applying_twice_appends_two_separate_mappings(qtbot):
    """Matches the "apply without closing" principle: the AI dialog stays
    open, so the user can draft and apply more than one action per session."""
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._apply_ai_drafted_action(dict(_DRAFTED_RENAMER_MAPPING))
    second = dict(_DRAFTED_RENAMER_MAPPING)
    second["name"] = "Second draft"
    dialog._apply_ai_drafted_action(second)

    assert len(dialog._mappings) == 2
    assert dialog._mappings[1]["name"] == "Second draft"


def test_open_ai_draft_dialog_creates_and_caches_a_single_instance(qtbot, monkeypatch):
    _suppress_window_display(monkeypatch)
    dialog = RenamerActionDialog(None, ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._open_ai_draft_dialog()
    first_instance = dialog._ai_draft_dialog
    assert first_instance is not None
    assert first_instance.isModal() is False  # apply-without-closing pattern

    dialog._open_ai_draft_dialog()
    assert dialog._ai_draft_dialog is first_instance  # reused, not recreated


def test_ai_draft_dialog_applying_flows_into_the_mapping_list(qtbot, monkeypatch):
    """End-to-end wiring check: the signal from LLMConfigChatDialog reaches
    _apply_ai_drafted_action exactly as _apply_suggested_rule does for the
    renamer rule suggester."""
    _suppress_window_display(monkeypatch)
    dialog = DuplicateRemoverActionDialog(None, ActionType.DUPLICATE_REMOVER)
    qtbot.addWidget(dialog)
    dialog._open_ai_draft_dialog()

    drafted = {"name": "Test dedup", "source_dirs": ["/tmp/somewhere"]}
    dialog._ai_draft_dialog.action_drafted.emit(drafted)

    assert len(dialog._mappings) == 1
    assert dialog._mappings[0]["name"] == "Test dedup"
