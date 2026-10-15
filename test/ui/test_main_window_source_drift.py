"""MainWindow tells the user when a build's startup check finds its source
checkout has changed; the check reports from a background thread."""

from __future__ import annotations

import threading

import pytest

from refacdir.utils.translations import _

pytestmark = pytest.mark.ui


def test_drift_reported_from_a_worker_thread_shows_a_toast(qtbot, main_window, monkeypatch):
    shown = []
    monkeypatch.setattr(main_window._toast, "show_message",
                        lambda message, duration=3000: shown.append((message, duration)))

    worker = threading.Thread(target=main_window.source_drift_signal.emit, args=("2 commits behind",))
    worker.start()
    worker.join(5)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    message, duration = shown[0]
    assert message == _("This build differs from its source checkout. Details are in the log.")
    assert duration > 3000
