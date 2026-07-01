"""UI tests for config editor path resolution (load/save/discovery)."""

from __future__ import annotations

import os

import pytest
import yaml
from PySide6.QtWidgets import QFileDialog, QMessageBox

from refacdir.config import Config
from ui.config_editor_window import ConfigEditorWindow

from test.ui.conftest import read_config_file, write_config_content, write_runnable_config

pytestmark = pytest.mark.ui


@pytest.fixture
def no_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a, **_k: None)


@pytest.fixture
def wrong_cwd(monkeypatch):
    """Process cwd away from configs dir (simulates mid-batch chdir)."""
    other = os.path.join(Config.configs_dir(), "..", "wrong_cwd")
    os.makedirs(other, exist_ok=True)
    monkeypatch.chdir(other)


def test_config_basename_strips_configs_prefix_and_backslashes():
    assert ConfigEditorWindow._config_basename("configs/foo.yaml") == "foo.yaml"
    assert ConfigEditorWindow._config_basename("configs\\bar.yaml") == "bar.yaml"


def test_config_paths_from_disk_lists_isolated_configs(qtbot, noop_app_actions):
    write_runnable_config("first.yaml")
    write_runnable_config("second.yaml")

    editor = ConfigEditorWindow(app_actions=None)
    qtbot.addWidget(editor)

    paths = editor._config_paths_from_disk()
    assert paths == ["configs/first.yaml", "configs/second.yaml"]


def test_reload_without_app_actions_scans_configs_dir(qtbot, wrong_cwd):
    write_runnable_config("listed.yaml")

    editor = ConfigEditorWindow(app_actions=None)
    qtbot.addWidget(editor)
    editor.reload_config_list()

    assert editor.config_list.count() == 1
    assert editor.config_list.item(0).text() == "configs/listed.yaml"


def test_load_config_reads_from_configs_dir(qtbot, noop_app_actions, wrong_cwd):
    write_config_content(
        "loaded.yaml",
        "will_run: false\nfilename_mapping_functions: []\nfiletype_definitions: []\nactions: []\n",
    )

    editor = ConfigEditorWindow(app_actions=noop_app_actions)
    qtbot.addWidget(editor)
    editor.load_config("configs/loaded.yaml")

    assert editor.current_config_path == "configs/loaded.yaml"
    assert editor.path_label.text() == "configs/loaded.yaml"
    assert editor.will_run_checkbox.isChecked() is False


def test_load_config_missing_file_does_not_mutate_state(
    qtbot, noop_app_actions, wrong_cwd, no_message_boxes, monkeypatch
):
    warned: list[str] = []

    def capture_warning(_parent, _title, message):
        warned.append(message)

    monkeypatch.setattr(QMessageBox, "warning", capture_warning)

    editor = ConfigEditorWindow(app_actions=noop_app_actions)
    qtbot.addWidget(editor)
    editor.new_config()
    editor.load_config("configs/does_not_exist.yaml")

    assert editor.current_config_path is None
    assert editor.path_label.text() == "(new config)"
    assert warned and "does_not_exist.yaml" in warned[0]
    assert Config.configs_dir() in warned[0]


def test_save_current_config_writes_under_configs_dir(
    qtbot, noop_app_actions, wrong_cwd, no_message_boxes
):
    write_runnable_config("edit_me.yaml", will_run=True)

    editor = ConfigEditorWindow(app_actions=noop_app_actions)
    qtbot.addWidget(editor)
    editor.load_config("configs/edit_me.yaml")
    editor.will_run_checkbox.setChecked(False)

    editor.save_current_config()

    saved = yaml.safe_load(read_config_file("edit_me.yaml"))
    assert saved["will_run"] is False
    assert os.path.isfile(os.path.join(Config.configs_dir(), "edit_me.yaml"))


def test_save_as_writes_file_and_sets_configs_rel_path(
    qtbot, noop_app_actions, wrong_cwd, no_message_boxes, monkeypatch
):
    target = os.path.join(Config.configs_dir(), "saved_as.yaml")

    def fake_save_dialog(_parent, _title, _default, _filter):
        return (target, "YAML Files (*.yaml)")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save_dialog)

    editor = ConfigEditorWindow(app_actions=noop_app_actions)
    qtbot.addWidget(editor)
    editor.new_config()
    editor.will_run_checkbox.setChecked(False)

    editor.save_as_config()

    assert editor.current_config_path == "configs/saved_as.yaml"
    assert editor.path_label.text() == "configs/saved_as.yaml"
    assert os.path.isfile(target)
    assert yaml.safe_load(read_config_file("saved_as.yaml"))["will_run"] is False


def test_save_as_default_dialog_path_uses_configs_dir(qtbot, noop_app_actions, monkeypatch):
    captured: list[str] = []

    def fake_save_dialog(_parent, _title, default_path, _filter):
        captured.append(default_path)
        return ("", "YAML Files (*.yaml)")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save_dialog)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a, **_k: None)

    editor = ConfigEditorWindow(app_actions=noop_app_actions)
    qtbot.addWidget(editor)
    editor.new_config()
    editor.save_as_config()

    assert captured
    assert captured[0].startswith(Config.configs_dir())
    assert captured[0].endswith("new_config.yaml")


def test_open_selected_config_loads_by_list_key(qtbot, noop_app_actions, wrong_cwd):
    write_config_content(
        "picked.yaml",
        "will_run: true\nfilename_mapping_functions: []\nfiletype_definitions: []\nactions: []\n",
    )

    editor = ConfigEditorWindow(app_actions=None)
    qtbot.addWidget(editor)
    editor.reload_config_list()
    editor.config_list.setCurrentRow(0)

    editor.open_selected_config()

    assert editor.current_config_path == "configs/picked.yaml"
    assert editor.path_label.text() == "configs/picked.yaml"
