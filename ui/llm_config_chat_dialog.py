"""
"Chat with LLM to define configs" dialog (Phase 5, docs/LLM_CONFIG_CHAT_SCOPE.md).

Non-modal, "apply without closing" — the same pattern as
``RenamerRuleSuggesterDialog``: the user can draft, review, and apply more
than one action in a single session without the dialog closing itself.
Nothing is written to the real batch config until the user explicitly clicks
Apply; the draft/validate/retry loop (Phase 3) already forces every
successful draft into its safest dry-run state (Phase 4) before it ever
reaches this dialog, and Apply only ever emits a signal — this dialog never
touches a config file directly.

Runs the draft + preview work (a real Ollama call can take seconds to
minutes) on a background thread, using the same ``threading.Thread`` +
Qt-signal pattern already used by ``ui/test_results_window.py``, so the UI
never freezes while waiting on the model. Qt signals are safe to emit from a
non-GUI thread; the connected slot below still runs on the GUI thread.

Model/endpoint are plain fields on this dialog rather than a new app-wide LLM
settings object — refacdir has no such settings object yet, and adding one is
out of scope here (see docs/LLM_CONFIG_CHAT_SCOPE.md's Phase 5 notes).
"""

import json
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from refacdir.batch import ActionType
from refacdir.lib.multi_display import SmartDialog
from refacdir.llm.config_schema import supported_action_types
from refacdir.llm.conversation import DEFAULT_MAX_ATTEMPTS, draft_action
from refacdir.llm.client import LLM
from refacdir.llm.preview import preview_action

DEFAULT_MODEL_NAME = "deepseek-r1:14b"


class _DraftWorkerSignals(QObject):
    """Marshal background-thread results back onto the GUI thread."""
    finished = Signal(object, object)  # (DraftResult, PreviewResult-or-None)
    failed = Signal(str)


class LLMConfigChatDialog(SmartDialog):
    """
    Draft one complete action (for a single, fixed ``action_type``) from a
    plain-language description, via the Phase 3 draft/validate/retry loop,
    then preview (Phase 4) what it would touch before the user applies it.

    Emits ``action_drafted`` with the validated action dict only when the
    user explicitly clicks Apply — never automatically. The dialog stays
    open afterward (same "apply without closing" principle as
    ``RenamerRuleSuggesterDialog``) so the user can describe and apply
    another action without reopening it.
    """

    action_drafted = Signal(dict)

    def __init__(self, parent=None, action_type: ActionType = None, default_model: str = DEFAULT_MODEL_NAME):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=f"Draft {action_type.value} Action with AI",
            geometry="820x720",
            center=True,
        )
        self.setModal(False)
        self._action_type = action_type
        self._draft_result = None
        self._preview_result = None
        self._supported = action_type in supported_action_types()
        self._signals = _DraftWorkerSignals()
        self._signals.finished.connect(self._on_worker_finished)
        self._signals.failed.connect(self._on_worker_failed)

        layout = QVBoxLayout(self)

        intro_text = (
            f"Describe the {action_type.value} action you want in plain language. "
            "Nothing is written to the config until you click Apply below."
        )
        if not self._supported:
            intro_text = (
                f"{action_type.value} actions aren't supported by the AI drafting "
                "feature yet (see docs/LLM_CONFIG_CHAT_SCOPE.md)."
            )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            'e.g. "Move every screenshot in Downloads into a Screenshots folder"'
        )
        self.description_edit.setMinimumHeight(80)
        self.description_edit.setEnabled(self._supported)
        layout.addWidget(self.description_edit)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        self.model_edit = QLineEdit(default_model)
        model_row.addWidget(self.model_edit, 1)
        model_row.addWidget(QLabel("Endpoint override"))
        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText("blank = default local Ollama endpoint")
        model_row.addWidget(self.endpoint_edit, 1)
        layout.addLayout(model_row)

        self.draft_btn = QPushButton("Draft")
        self.draft_btn.setEnabled(self._supported)
        self.draft_btn.clicked.connect(self._on_draft_clicked)
        layout.addWidget(self.draft_btn)

        conversation_group = QGroupBox("Conversation")
        conversation_layout = QVBoxLayout(conversation_group)
        self.conversation_log = QTextEdit()
        self.conversation_log.setReadOnly(True)
        conversation_layout.addWidget(self.conversation_log)
        layout.addWidget(conversation_group, 1)

        draft_group = QGroupBox("Current Draft")
        draft_layout = QVBoxLayout(draft_group)
        self.draft_view = QTextEdit()
        self.draft_view.setReadOnly(True)
        draft_layout.addWidget(self.draft_view)
        layout.addWidget(draft_group, 1)

        preview_group = QGroupBox("Preview (what this would touch)")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_view = QTextEdit()
        self.preview_view.setReadOnly(True)
        preview_layout.addWidget(self.preview_view)
        layout.addWidget(preview_group, 1)

        button_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        button_row.addWidget(self.apply_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    # -- Draft ----------------------------------------------------------------

    def _on_draft_clicked(self):
        if not self._supported:
            return
        description = self.description_edit.toPlainText().strip()
        if not description:
            QMessageBox.information(self, "Description Required", "Describe the action you want first.")
            return

        self.draft_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self._draft_result = None
        self._preview_result = None
        self.conversation_log.append(f"> {description}")
        self.draft_view.clear()
        self.preview_view.clear()

        model_name = self.model_edit.text().strip() or DEFAULT_MODEL_NAME
        endpoint = self.endpoint_edit.text().strip() or None
        signals = self._signals

        def run_worker():
            try:
                draft_result, preview_result = self._run_draft(description, model_name, endpoint)
                signals.finished.emit(draft_result, preview_result)
            except Exception as exc:
                signals.failed.emit(str(exc))

        threading.Thread(target=run_worker, daemon=True).start()

    def _run_draft(self, description: str, model_name: str, endpoint):
        """
        The actual draft + preview work (Phases 3-4) — synchronous, no
        thread/signal involvement, so it's directly testable without any
        threading/timing concerns. Called from a background thread by
        ``_on_draft_clicked``; returns ``(DraftResult, PreviewResult-or-None)``
        or raises.
        """
        llm = LLM(model_name=model_name, endpoint=endpoint)
        draft_result = draft_action(description, self._action_type, llm, max_attempts=DEFAULT_MAX_ATTEMPTS)
        preview_result = None
        if draft_result.success:
            preview_result = preview_action(self._action_type, draft_result.action_dict)
        return draft_result, preview_result

    def _on_worker_finished(self, draft_result, preview_result):
        self.draft_btn.setEnabled(True)
        self._draft_result = draft_result
        self._preview_result = preview_result

        for idx, attempt in enumerate(draft_result.attempts, start=1):
            if attempt.parse_error:
                self.conversation_log.append(f"Attempt {idx}: parse error — {attempt.parse_error}")
            elif attempt.validation is not None and not attempt.validation.valid:
                self.conversation_log.append(
                    f"Attempt {idx}: validation failed — {attempt.validation.error_summary()}"
                )
            else:
                self.conversation_log.append(f"Attempt {idx}: OK")

        if draft_result.success:
            self.draft_view.setPlainText(json.dumps(draft_result.action_dict, indent=2))
            if draft_result.warnings:
                self.conversation_log.append("Warnings: " + "; ".join(draft_result.warnings))
            if preview_result is not None:
                if preview_result.available:
                    self.preview_view.setPlainText(
                        preview_result.summary + "\n\n" + json.dumps(preview_result.details, indent=2, default=str)
                    )
                else:
                    self.preview_view.setPlainText(f"Preview unavailable: {preview_result.reason}")
            self.apply_btn.setEnabled(True)
        else:
            self.conversation_log.append(
                f"Failed after {draft_result.attempt_count} attempt(s): {draft_result.last_error_summary()}"
            )

    def _on_worker_failed(self, message: str):
        self.draft_btn.setEnabled(True)
        self.conversation_log.append(f"Error: {message}")

    # -- Apply ------------------------------------------------------------------

    def _on_apply_clicked(self):
        if self._draft_result is None or not self._draft_result.success:
            QMessageBox.information(self, "No Draft", "Draft an action first.")
            return
        # Apply without closing, matching RenamerRuleSuggesterDialog — the
        # user may want to describe and apply another action next.
        self.action_drafted.emit(self._draft_result.action_dict)
        self.conversation_log.append("Applied.")
        self.apply_btn.setEnabled(False)
        self._draft_result = None
        self._preview_result = None
