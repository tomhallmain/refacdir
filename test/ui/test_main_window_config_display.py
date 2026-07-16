"""
Regression tests for sidebar checkbox display: config paths must show just the
basename, not the full "configs/..." relative path used as the underlying key.
"""

from __future__ import annotations

import pytest

import app_qt
from app_qt import MainWindow

pytestmark = pytest.mark.ui


@pytest.mark.parametrize(
    "path, expected",
    [
        ("configs/my_backup.yaml", "my_backup.yaml"),
        ("configs/nested/my_backup.yaml", "my_backup.yaml"),
        ("my_backup.yaml", "my_backup.yaml"),
    ],
)
def test_config_display_name_strips_directory(path, expected):
    assert MainWindow._config_display_name(path) == expected


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


def test_sync_config_widgets_shows_basename_with_full_path_tooltip(main_window):
    main_window.batch_args.configs = {"configs/my_backup.yaml": True}
    main_window.sync_config_widgets()

    checkbox = main_window._config_checkboxes["configs/my_backup.yaml"]
    assert checkbox.text() == "my_backup.yaml"
    assert checkbox.toolTip() == "configs/my_backup.yaml"


def test_sync_config_widgets_keeps_basename_after_reorder(main_window):
    """Existing checkboxes are repositioned, not recreated — label must stay correct."""
    main_window.batch_args.configs = {
        "configs/zeta.yaml": True,
        "configs/alpha.yaml": True,
    }
    main_window.sync_config_widgets()
    main_window.batch_args.configs = {
        "configs/alpha.yaml": True,
        "configs/zeta.yaml": True,
        "configs/beta.yaml": False,
    }
    main_window.sync_config_widgets()

    labels = {
        path: checkbox.text() for path, checkbox in main_window._config_checkboxes.items()
    }
    assert labels == {
        "configs/zeta.yaml": "zeta.yaml",
        "configs/alpha.yaml": "alpha.yaml",
        "configs/beta.yaml": "beta.yaml",
    }
