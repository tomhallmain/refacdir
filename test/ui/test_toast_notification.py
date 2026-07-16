"""
Regression tests for ``ToastNotification`` screen placement (item #11).

Toasts previously always centered on ``QApplication.primaryScreen()``, so on a
multi-monitor setup where the app window lived on a secondary screen, toasts
would appear on the wrong monitor. ``ToastNotification`` now resolves the
screen from an optional ``screen_anchor`` window (e.g. the main window)
instead, falling back to the primary screen when no anchor is given or the
anchor can't report a screen yet.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ui.toast_notification import ToastNotification

pytestmark = pytest.mark.ui


class _FakeScreen:
    def __init__(self, rect: QRect):
        self._rect = rect

    def geometry(self):
        return self._rect


class _FakeAnchor:
    def __init__(self, screen):
        self._screen = screen

    def screen(self):
        return self._screen


class _BrokenAnchor:
    """Anchor whose .screen() raises, exercising the defensive fallback."""

    def screen(self):
        raise RuntimeError("no native window yet")


def test_toast_positions_on_anchor_screen_not_primary(qtbot):
    """A toast anchored to a window on a secondary screen must land there."""
    secondary = QRect(1920, 0, 1024, 768)
    anchor = _FakeAnchor(_FakeScreen(secondary))

    toast = ToastNotification(screen_anchor=anchor)
    qtbot.addWidget(toast)
    toast.show_message("hello", duration=50)

    assert toast.x() >= secondary.x()
    assert toast.x() + toast.width() <= secondary.x() + secondary.width()
    assert toast.y() >= secondary.y()


def test_toast_falls_back_to_primary_screen_without_anchor(qtbot):
    primary_geometry = QApplication.primaryScreen().geometry()

    toast = ToastNotification()
    qtbot.addWidget(toast)
    toast.show_message("hello", duration=50)

    assert toast.x() >= primary_geometry.x()
    assert toast.x() + toast.width() <= primary_geometry.x() + primary_geometry.width()


def test_toast_falls_back_to_primary_screen_when_anchor_screen_raises(qtbot):
    primary_geometry = QApplication.primaryScreen().geometry()

    toast = ToastNotification(screen_anchor=_BrokenAnchor())
    qtbot.addWidget(toast)
    toast.show_message("hello", duration=50)

    assert toast.x() >= primary_geometry.x()
    assert toast.x() + toast.width() <= primary_geometry.x() + primary_geometry.width()


def test_resolve_screen_returns_anchor_screen_directly(qtbot):
    secondary = QRect(-1024, 0, 1024, 768)  # e.g. a monitor to the left of primary
    fake_screen = _FakeScreen(secondary)
    anchor = _FakeAnchor(fake_screen)

    toast = ToastNotification(screen_anchor=anchor)
    qtbot.addWidget(toast)

    assert toast._resolve_screen() is fake_screen
