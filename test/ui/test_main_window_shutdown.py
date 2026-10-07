"""Shutdown: closing the main window ends the app; exit flushes the pattern cache."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

import app_qt
import refacdir.utils.persistent_pattern_cache as pattern_cache_module
from ui.inactivity_shutdown import InactivityShutdown

pytestmark = pytest.mark.ui


def test_closing_the_window_emits_closed_signal(qtbot, main_window):
    with qtbot.waitSignal(main_window.closed_signal, timeout=2000):
        main_window.close()


def test_exit_flushes_the_pattern_cache_then_exits(monkeypatch):
    flushed = []
    monkeypatch.setattr(pattern_cache_module.persistent_pattern_cache, "flush", lambda: flushed.append(1))

    with pytest.raises(SystemExit) as excinfo:
        app_qt._exit_process(3)

    assert flushed == [1]
    assert excinfo.value.code == 3


def test_stopped_inactivity_shutdown_ignores_activity(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    shutdown = InactivityShutdown(host, timeout_ms=60_000)
    assert shutdown._timer.isActive()

    shutdown.stop()
    # Un-paused, a still-installed filter would restart the timer on activity.
    shutdown._paused = False
    QApplication.sendEvent(host, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier))

    assert not shutdown._timer.isActive()
