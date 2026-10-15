"""MainWindow's Toggle Theme button: switches the theme, says so, and stores the choice."""

from __future__ import annotations

import pytest

from refacdir.utils.translations import _

pytestmark = pytest.mark.ui


@pytest.fixture
def toasts(main_window, monkeypatch):
    shown = []
    monkeypatch.setattr(main_window._toast, "show_message",
                        lambda message, duration=3000: shown.append(message))
    return shown


def test_toggle_switches_theme_and_tells_the_user(main_window, toasts, monkeypatch):
    stores = []
    monkeypatch.setattr(main_window, "schedule_store_ui_settings", lambda: stores.append(True))
    assert main_window.is_dark_theme is True

    main_window.toggle_theme_btn.click()
    assert main_window.is_dark_theme is False
    assert toasts == [_("Theme switched to light.")]

    main_window.toggle_theme_btn.click()
    assert main_window.is_dark_theme is True
    assert toasts[-1] == _("Theme switched to dark.")

    assert len(stores) == 2
