"""Which configs a MainWindow run covers: the filtered selection, or one config."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

import app_qt
from refacdir.utils.translations import _

pytestmark = pytest.mark.ui


@pytest.fixture
def run_window(main_window, monkeypatch):
    """``main_window`` with batch runs and alerts captured, not executed or shown."""
    window = main_window
    window.started_args = []
    window.alerts = []
    monkeypatch.setattr(app_qt, "main", lambda args: window.started_args.append(args))
    monkeypatch.setattr(app_qt.Utils, "start_thread", staticmethod(lambda func: func()))
    monkeypatch.setattr(
        window, "alert", lambda title, message, kind="info": window.alerts.append((title, message, kind))
    )

    window.batch_args.configs = {
        "configs/alpha.yaml": True,
        "configs/beta.yaml": True,
        "configs/off.yaml": False,
    }
    window.filtered_configs = dict(window.batch_args.configs)
    return window


def test_run_covers_filtered_configs(run_window):
    run_window.filtered_configs = {"configs/alpha.yaml": True}

    run_window.run()

    assert run_window.started_args[0].configs == {"configs/alpha.yaml": True}


def test_run_button_runs_filtered_configs(run_window):
    run_window.run_btn.click()

    assert run_window.started_args[0].configs == run_window.filtered_configs


def test_run_config_runs_only_that_config_and_keeps_filter(run_window):
    before = dict(run_window.filtered_configs)

    run_window.run_config("configs/beta.yaml")

    assert run_window.started_args[0].configs == {"configs/beta.yaml": True}
    assert run_window.filtered_configs == before
    assert run_window._run_overrides == {}
    assert run_window.alerts == []


def test_run_config_unknown_config_alerts_without_running(run_window):
    run_window.run_config("configs/missing.yaml")

    assert run_window.started_args == []
    assert run_window.alerts[0][0] == _("Error")
    assert run_window.alerts[0][2] == "error"


def test_run_config_unchecked_config_warns_without_running(run_window):
    run_window.run_config("configs/off.yaml")

    assert run_window.started_args == []
    assert run_window.alerts == [
        (_("Config not enabled"), _("Check {0} to run it.").format("off.yaml"), "warning")
    ]


def test_run_config_queued_keeps_override_until_started(run_window):
    run_window.job_queue.job_running = True

    run_id = run_window.run_config("configs/beta.yaml")

    assert run_window.started_args == []
    assert run_window._run_overrides[run_id] == {"configs": {"configs/beta.yaml": True}}

    run_window.job_queue.finish()
    run_window._start_batch_run(run_window.job_queue.take())

    assert run_window.started_args[0].configs == {"configs/beta.yaml": True}
    assert run_window._run_overrides == {}


def test_run_queue_full_drops_override(run_window):
    run_window.job_queue.job_running = True
    run_window.job_queue.max_size = 0

    run_window.run(configs={"configs/beta.yaml": True})

    assert run_window._run_overrides == {}
    assert run_window.alerts[0][0] == _("Queue full")


def test_mcp_run_uses_filtered_configs_with_confirmations_off(run_window):
    run_window.filtered_configs = {"configs/alpha.yaml": True}

    run_window.start_mcp_run(test=True, only_observers=False)

    args = run_window.started_args[0]
    assert args.configs == {"configs/alpha.yaml": True}
    assert args.test is True
    assert args.skip_confirm is True


def test_enter_with_single_filter_match_runs_that_config(run_window):
    run_window.filter_text = "bet"
    run_window.filtered_configs = {"configs/beta.yaml": True}

    run_window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))

    assert run_window.started_args[0].configs == {"configs/beta.yaml": True}
    assert run_window.alerts == []
