"""
Regression tests for ``MainWindow.toggle_config``.

``QCheckBox.stateChanged`` delivers the state as an ``int``, and a PySide6
``Qt.CheckState`` enum member never compares equal to an ``int``, so comparing
the raw argument to ``Qt.Checked`` read every toggle as unchecked and wrote
``will_run: false`` for each click.
"""

from __future__ import annotations

import pytest
import yaml
from PySide6.QtCore import Qt

from test.ui.conftest import read_config_file, write_runnable_config

pytestmark = pytest.mark.ui


def _show_config(main_window, rel_path: str, will_run: bool):
    main_window.batch_args.configs = {rel_path: will_run}
    main_window.sync_config_widgets()
    main_window.filter_configs("")
    return main_window._config_checkboxes[rel_path]


def _file_will_run(name: str) -> bool:
    return yaml.safe_load(read_config_file(name))["will_run"]


def test_checking_a_config_checkbox_enables_it(main_window):
    rel_path = write_runnable_config("toggle_on.yaml", will_run=False)
    checkbox = _show_config(main_window, rel_path, False)

    checkbox.setChecked(True)

    assert main_window.batch_args.configs[rel_path] is True
    assert main_window.filtered_configs[rel_path] is True
    assert _file_will_run("toggle_on.yaml") is True


def test_unchecking_a_config_checkbox_disables_it(main_window):
    rel_path = write_runnable_config("toggle_off.yaml", will_run=True)
    checkbox = _show_config(main_window, rel_path, True)

    checkbox.setChecked(False)

    assert main_window.batch_args.configs[rel_path] is False
    assert main_window.filtered_configs[rel_path] is False
    assert _file_will_run("toggle_off.yaml") is False


@pytest.mark.parametrize(
    "state, expected",
    [
        (Qt.CheckState.Checked.value, True),
        (Qt.CheckState.Unchecked.value, False),
        (Qt.CheckState.Checked, True),
        (Qt.CheckState.Unchecked, False),
    ],
)
def test_toggle_config_accepts_int_or_enum_state(main_window, state, expected):
    rel_path = write_runnable_config("toggle_direct.yaml", will_run=not expected)
    _show_config(main_window, rel_path, not expected)

    main_window.toggle_config(rel_path, state)

    assert main_window.batch_args.configs[rel_path] is expected
    assert _file_will_run("toggle_direct.yaml") is expected
