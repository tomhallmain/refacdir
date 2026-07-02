"""UI tests for debounced UI settings persistence on MainWindow."""

from __future__ import annotations

import pytest

import app_qt
from app_qt import MainWindow

pytestmark = pytest.mark.ui


class _InactivityShutdownStub:
    def __init__(self, _window):
        pass

    def set_timeout_minutes(self, _minutes):
        pass

    def pause(self):
        pass

    def resume(self):
        pass


@pytest.fixture
def main_window(qtbot, monkeypatch):
    """MainWindow with network/server and restore paths stubbed out."""
    monkeypatch.setattr(app_qt.MainWindow, "setup_server", lambda self: None)
    monkeypatch.setattr(app_qt.MainWindow, "load_configs", lambda self: None)
    monkeypatch.setattr(app_qt.MainWindow, "restore_ui_settings", lambda self: None)
    monkeypatch.setattr(app_qt.MainWindow, "restore_window_geometry", lambda self: None)
    monkeypatch.setattr(app_qt, "InactivityShutdown", _InactivityShutdownStub)

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_schedule_store_ui_settings_debounces_disk_writes(qtbot, main_window, monkeypatch):
    store_calls: list[int] = []
    monkeypatch.setattr(app_qt.app_info_cache, "store", lambda: store_calls.append(1))

    main_window.schedule_store_ui_settings()
    main_window.schedule_store_ui_settings()
    main_window.schedule_store_ui_settings()

    assert store_calls == []
    assert main_window._ui_settings_store_timer.isActive()

    qtbot.wait(app_qt._UI_SETTINGS_STORE_DEBOUNCE_MS + 100)

    assert store_calls == [1]


def test_debounced_flush_snapshots_latest_config_checkbox_state(qtbot, main_window, monkeypatch):
    captured: list[dict] = []
    store_calls: list[int] = []

    monkeypatch.setattr(
        app_qt.app_info_cache,
        "set_selected_configs",
        lambda configs: captured.append(dict(configs)),
    )
    monkeypatch.setattr(app_qt.app_info_cache, "store", lambda: store_calls.append(1))
    monkeypatch.setattr(app_qt.app_info_cache, "set_ui_theme", lambda _theme: None)
    monkeypatch.setattr(app_qt.app_info_cache, "set_operation_settings", lambda _settings: None)

    main_window.batch_args.configs = {"configs/alpha.yaml": True}
    main_window.schedule_store_ui_settings()
    main_window.batch_args.configs = {"configs/alpha.yaml": False}

    main_window.flush_store_ui_settings()

    assert store_calls == [1]
    assert captured == [{"configs/alpha.yaml": False}]


def test_debounced_timer_snapshots_latest_config_checkbox_state(qtbot, main_window, monkeypatch):
    captured: list[dict] = []
    store_calls: list[int] = []

    monkeypatch.setattr(
        app_qt.app_info_cache,
        "set_selected_configs",
        lambda configs: captured.append(dict(configs)),
    )
    monkeypatch.setattr(app_qt.app_info_cache, "store", lambda: store_calls.append(1))
    monkeypatch.setattr(app_qt.app_info_cache, "set_ui_theme", lambda _theme: None)
    monkeypatch.setattr(app_qt.app_info_cache, "set_operation_settings", lambda _settings: None)

    main_window.batch_args.configs = {"configs/alpha.yaml": True}
    main_window.schedule_store_ui_settings()
    main_window.batch_args.configs = {"configs/alpha.yaml": False}

    qtbot.wait(app_qt._UI_SETTINGS_STORE_DEBOUNCE_MS + 100)

    assert store_calls == [1]
    assert captured == [{"configs/alpha.yaml": False}]
