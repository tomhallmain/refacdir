"""UI tests for the config editor."""

from __future__ import annotations

import pytest

from refacdir.batch import BatchArgs
from ui.app_actions import AppActions
from ui.config_editor_window import ConfigEditorWindow

from test.ui.conftest import merge_preserving_refresh_configs, write_runnable_config

pytestmark = pytest.mark.ui


def _actions_with_refresh(noop_app_actions, refresh_configs):
    return AppActions(
        {
            name: getattr(noop_app_actions, name)
            for name in AppActions.REQUIRED_ACTIONS
            if name != "refresh_configs"
        }
        | {"refresh_configs": refresh_configs}
    )


def test_reload_config_list_delegates_to_refresh_configs(qtbot, noop_app_actions, monkeypatch):
    """reload_config_list must not call BatchArgs.setup_configs directly (improvement #1)."""
    BatchArgs.configs = {"configs/alpha.yaml": True}

    refresh_calls: list[int] = []
    setup_calls: list[int] = []

    def tracking_refresh():
        refresh_calls.append(1)

    def tracking_setup(*_args, **_kwargs):
        setup_calls.append(1)

    monkeypatch.setattr(BatchArgs, "setup_configs", tracking_setup)

    editor = ConfigEditorWindow(
        app_actions=_actions_with_refresh(noop_app_actions, tracking_refresh),
    )
    qtbot.addWidget(editor)
    refresh_calls.clear()
    setup_calls.clear()

    editor.reload_config_list()

    assert refresh_calls == [1]
    assert setup_calls == []


def test_reload_config_list_preserves_selection_via_merge_refresh(qtbot, noop_app_actions):
    """refresh_configs merge path keeps unchecked configs when the editor reloads."""
    write_runnable_config("alpha.yaml")
    write_runnable_config("beta.yaml")

    BatchArgs.configs = {
        "configs/alpha.yaml": False,
        "configs/beta.yaml": True,
    }

    editor = ConfigEditorWindow(
        app_actions=_actions_with_refresh(noop_app_actions, merge_preserving_refresh_configs),
    )
    qtbot.addWidget(editor)
    editor.reload_config_list()

    assert BatchArgs.configs["configs/alpha.yaml"] is False
    assert BatchArgs.configs["configs/beta.yaml"] is True
    assert editor.config_list.count() == 2
    labels = [editor.config_list.item(i).text() for i in range(editor.config_list.count())]
    assert labels == ["configs/alpha.yaml", "configs/beta.yaml"]


def test_after_save_refreshes_configs_once(qtbot, noop_app_actions, monkeypatch):
    """_after_save must trigger a single refresh_configs via reload_config_list (#2)."""
    from PySide6.QtWidgets import QMessageBox

    refresh_calls: list[int] = []

    def tracking_refresh():
        refresh_calls.append(1)

    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    editor = ConfigEditorWindow(
        app_actions=_actions_with_refresh(noop_app_actions, tracking_refresh),
    )
    qtbot.addWidget(editor)
    refresh_calls.clear()

    editor._after_save("configs/alpha.yaml")

    assert refresh_calls == [1]
    assert editor.path_label.text() == "configs/alpha.yaml"
