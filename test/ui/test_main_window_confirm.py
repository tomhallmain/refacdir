"""MainWindow.confirm: asked on the GUI thread, marshalled from the batch worker."""

from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QMessageBox

import app_qt
from refacdir.utils.translations import _

pytestmark = pytest.mark.ui


@pytest.fixture
def dialog_answers(main_window, monkeypatch):
    """Stub the dialog: record each request and the status line it was shown with."""
    shown = []

    def install(answer):
        def fake_dialog(request):
            shown.append((request, main_window.status_label.text()))
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(main_window, "_show_confirm_dialog", fake_dialog)
        return shown
    return install


def test_confirm_on_the_gui_thread_shows_the_dialog_directly(main_window, dialog_answers):
    shown = dialog_answers(True)
    assert main_window.confirm("Confirm backup", "Run it?", details="d", acknowledgement="a") is True
    request, _status = shown[0]
    assert request == {
        "title": "Confirm backup",
        "message": "Run it?",
        "details": "d",
        "acknowledgement": "a",
    }


def test_confirm_from_a_worker_thread_is_marshalled_and_waits(qtbot, main_window, dialog_answers):
    shown = dialog_answers(False)
    result = {}

    worker = threading.Thread(
        target=lambda: result.setdefault("answer", main_window.confirm("Confirm renaming", "Go?"))
    )
    worker.start()
    qtbot.waitUntil(lambda: "answer" in result, timeout=5000)
    worker.join(1)

    assert result["answer"] is False
    _request, status = shown[0]
    assert status == _("Waiting for confirmation: {0}").format("Confirm renaming")


def test_a_failing_dialog_answers_no(qtbot, main_window, dialog_answers):
    dialog_answers(RuntimeError("boom"))
    result = {}

    worker = threading.Thread(
        target=lambda: result.setdefault("answer", main_window.confirm("Confirm", "Go?"))
    )
    worker.start()
    qtbot.waitUntil(lambda: "answer" in result, timeout=5000)

    assert result["answer"] is False


def _message_box_without_exec(monkeypatch, on_exec):
    """Swap app_qt's QMessageBox for a subclass whose exec() runs *on_exec* instead."""

    class _Box(QMessageBox):
        def exec(self):
            return on_exec(self)

    monkeypatch.setattr(app_qt, "QMessageBox", _Box)


def test_acknowledgement_gates_the_yes_button(main_window, monkeypatch):
    observed = {}

    def tick_and_accept(box):
        yes = box.button(QMessageBox.Yes)
        observed["yes_enabled_before"] = yes.isEnabled()
        box.checkBox().setChecked(True)
        observed["yes_enabled_after"] = yes.isEnabled()
        yes.click()
        return 0

    _message_box_without_exec(monkeypatch, tick_and_accept)
    answer = main_window._show_confirm_dialog(
        {"title": "T", "message": "M", "details": None, "acknowledgement": "I have checked"}
    )

    assert observed == {"yes_enabled_before": False, "yes_enabled_after": True}
    assert answer is True


def test_closing_without_an_answer_is_no(main_window, monkeypatch):
    _message_box_without_exec(monkeypatch, lambda box: 0)
    answer = main_window._show_confirm_dialog(
        {"title": "T", "message": "M", "details": None, "acknowledgement": None}
    )
    assert answer is False
