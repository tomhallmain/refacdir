"""
Tests for ``LLMConfigChatDialog`` (Phase 5, docs/LLM_CONFIG_CHAT_SCOPE.md).

The draft/preview work itself (``_run_draft``) is tested directly, without any
real threading, by monkeypatching the module-level ``draft_action``/
``preview_action``/``LLM`` names ``ui.llm_config_chat_dialog`` imported —
matching the test file's own import pattern, this is a fast, deterministic
way to exercise the dialog's logic without a real Ollama instance and without
timing-dependent thread/signal waits. One end-to-end test at the bottom
exercises the actual background-thread + Qt-signal wiring via
``qtbot.waitSignal``, using the same monkeypatched instant fakes.
"""

from __future__ import annotations

import pytest

from refacdir.batch import ActionType
from refacdir.llm.validation import ValidationResult
from refacdir.llm.conversation import DraftResult
from refacdir.llm.preview import PreviewResult
import ui.llm_config_chat_dialog as llm_config_chat_dialog
from ui.llm_config_chat_dialog import LLMConfigChatDialog

pytestmark = pytest.mark.ui

_ACTION_DICT = {
    "name": "Test renamer",
    "function": "rename_by_ctime",
    "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
    "locations": [{"root": "/tmp/somewhere"}],
}


def _successful_draft_result():
    return DraftResult(
        action_type=ActionType.RENAMER,
        success=True,
        action_dict=dict(_ACTION_DICT),
        warnings=[],
        attempts=[],
    )


def _failed_draft_result():
    return DraftResult(action_type=ActionType.RENAMER, success=False, attempts=[])


# ---------------------------------------------------------------------------
# Construction / unsupported action type
# ---------------------------------------------------------------------------

def test_supported_action_type_enables_drafting(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    assert dialog.draft_btn.isEnabled() is True
    assert dialog.description_edit.isEnabled() is True


def test_unsupported_action_type_disables_drafting(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.IMAGE_CATEGORIZER)
    qtbot.addWidget(dialog)

    assert dialog.draft_btn.isEnabled() is False
    assert dialog.description_edit.isEnabled() is False


def test_clicking_draft_on_unsupported_action_type_does_nothing(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_config_chat_dialog, "draft_action", lambda *a, **k: calls.append(1))

    dialog = LLMConfigChatDialog(action_type=ActionType.IMAGE_CATEGORIZER)
    qtbot.addWidget(dialog)
    dialog.description_edit.setPlainText("categorize my photos")
    dialog._on_draft_clicked()

    assert calls == []


# ---------------------------------------------------------------------------
# _on_draft_clicked guard rails
# ---------------------------------------------------------------------------

def test_draft_with_blank_description_shows_message_and_does_not_disable_button(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(1))

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog._on_draft_clicked()

    assert shown == [1]
    assert dialog.draft_btn.isEnabled() is True


# ---------------------------------------------------------------------------
# _run_draft — the actual draft + preview work, no threading involved
# ---------------------------------------------------------------------------

def test_run_draft_calls_draft_action_then_preview_action_on_success(qtbot, monkeypatch):
    calls = {}

    def fake_draft_action(description, action_type, llm, max_attempts):
        calls["draft_args"] = (description, action_type, max_attempts)
        return _successful_draft_result()

    def fake_preview_action(action_type, action_dict):
        calls["preview_args"] = (action_type, action_dict)
        return PreviewResult(action_type=action_type, available=True, summary="1 file matched")

    monkeypatch.setattr(llm_config_chat_dialog, "draft_action", fake_draft_action)
    monkeypatch.setattr(llm_config_chat_dialog, "preview_action", fake_preview_action)
    monkeypatch.setattr(llm_config_chat_dialog, "LLM", lambda model_name, endpoint: object())

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    draft_result, preview_result = dialog._run_draft("rename my files", "some-model", None)

    assert draft_result.success is True
    assert preview_result.summary == "1 file matched"
    assert calls["draft_args"] == ("rename my files", ActionType.RENAMER, llm_config_chat_dialog.DEFAULT_MAX_ATTEMPTS)
    assert calls["preview_args"] == (ActionType.RENAMER, _ACTION_DICT)


def test_run_draft_skips_preview_when_draft_failed(qtbot, monkeypatch):
    preview_calls = []
    monkeypatch.setattr(llm_config_chat_dialog, "draft_action", lambda *a, **k: _failed_draft_result())
    monkeypatch.setattr(
        llm_config_chat_dialog, "preview_action", lambda *a, **k: preview_calls.append(1)
    )
    monkeypatch.setattr(llm_config_chat_dialog, "LLM", lambda model_name, endpoint: object())

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    draft_result, preview_result = dialog._run_draft("rename my files", "some-model", None)

    assert draft_result.success is False
    assert preview_result is None
    assert preview_calls == []


# ---------------------------------------------------------------------------
# _on_worker_finished — UI state after a completed draft
# ---------------------------------------------------------------------------

def test_worker_finished_with_success_enables_apply_and_shows_draft(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    preview = PreviewResult(action_type=ActionType.RENAMER, available=True, summary="1 file matched", details={})
    dialog._on_worker_finished(_successful_draft_result(), preview)

    assert dialog.apply_btn.isEnabled() is True
    assert dialog.draft_btn.isEnabled() is True
    assert "renamed_" in dialog.draft_view.toPlainText()
    assert "1 file matched" in dialog.preview_view.toPlainText()


def test_worker_finished_with_unavailable_preview_shows_reason(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    preview = PreviewResult(action_type=ActionType.RENAMER, available=False, reason="Invalid root directory: /nope")
    dialog._on_worker_finished(_successful_draft_result(), preview)

    assert dialog.apply_btn.isEnabled() is True
    assert "Invalid root directory" in dialog.preview_view.toPlainText()


def test_worker_finished_with_failure_disables_apply(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    dialog._on_worker_finished(_failed_draft_result(), None)

    assert dialog.apply_btn.isEnabled() is False
    assert "Failed after" in dialog.conversation_log.toPlainText()


def test_worker_failed_reenables_draft_button_and_logs_error(qtbot):
    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog.draft_btn.setEnabled(False)

    dialog._on_worker_failed("connection refused")

    assert dialog.draft_btn.isEnabled() is True
    assert "connection refused" in dialog.conversation_log.toPlainText()


# ---------------------------------------------------------------------------
# Apply — never emits without an explicit click, never closes the dialog
# ---------------------------------------------------------------------------

def test_apply_without_a_draft_shows_message_and_emits_nothing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)

    emitted = []
    dialog.action_drafted.connect(lambda payload: emitted.append(payload))
    dialog._on_apply_clicked()

    assert emitted == []


def test_apply_after_successful_draft_emits_action_dict_and_does_not_close(qtbot):
    close_calls = []

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog.close = lambda: close_calls.append(1)  # apply must not call close()/accept()/reject()
    dialog._on_worker_finished(_successful_draft_result(), None)

    emitted = []
    dialog.action_drafted.connect(lambda payload: emitted.append(payload))
    dialog._on_apply_clicked()

    assert emitted == [_ACTION_DICT]
    assert close_calls == []
    assert dialog.apply_btn.isEnabled() is False  # re-disabled until the next successful draft
    assert dialog._draft_result is None  # cleared so a stray second click can't re-apply it


def test_apply_twice_without_a_new_draft_only_emits_once(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog._on_worker_finished(_successful_draft_result(), None)

    emitted = []
    dialog.action_drafted.connect(lambda payload: emitted.append(payload))
    dialog._on_apply_clicked()
    dialog._on_apply_clicked()  # _draft_result was cleared by the first apply; this is now a no-op

    assert len(emitted) == 1


# ---------------------------------------------------------------------------
# End-to-end: real thread + real Qt signal, monkeypatched instant fakes.
# ---------------------------------------------------------------------------

def test_draft_button_click_runs_worker_thread_and_updates_ui(qtbot, monkeypatch):
    monkeypatch.setattr(llm_config_chat_dialog, "draft_action", lambda *a, **k: _successful_draft_result())
    monkeypatch.setattr(
        llm_config_chat_dialog,
        "preview_action",
        lambda *a, **k: PreviewResult(action_type=ActionType.RENAMER, available=True, summary="ok"),
    )
    monkeypatch.setattr(llm_config_chat_dialog, "LLM", lambda model_name, endpoint: object())

    dialog = LLMConfigChatDialog(action_type=ActionType.RENAMER)
    qtbot.addWidget(dialog)
    dialog.description_edit.setPlainText("rename my files")

    with qtbot.waitSignal(dialog._signals.finished, timeout=2000):
        dialog._on_draft_clicked()

    assert dialog.apply_btn.isEnabled() is True
    assert "renamed_" in dialog.draft_view.toPlainText()
