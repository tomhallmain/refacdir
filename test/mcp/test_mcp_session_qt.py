"""The Qt session adapter's own logic, against a stand-in window.

No QApplication and no real widgets: the adapter's job is to decide what to
marshal, what to read directly, and how to shape each answer, and all of that
is observable through a fake. Importing the module pulls Qt in through the
``ui`` package, which the offscreen platform in the root conftest covers.
"""

import os

import pytest
import yaml

from refacdir.config import Config
from refacdir.job_queue import JobQueue
from ui.mcp_session_qt import JOB_OPERATION_SAMPLE, QtMainWindowMCPSession


class FakeCheckbox:
    def __init__(self, checked=False, on_toggle=None):
        self._checked = checked
        self._on_toggle = on_toggle

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)
        if self._on_toggle is not None:
            self._on_toggle(self._checked)


class FakeBatchArgs:
    def __init__(self, configs):
        self.configs = dict(configs)

    def update_config_state(self, path, will_run):
        if path in self.configs:
            self.configs[path] = will_run


class FakeWindow:
    """Stands in for MainWindow, recording what the adapter marshalled."""

    def __init__(self, configs=None, filtered=None):
        configs = configs if configs is not None else {"configs/a.yaml": True}
        self.batch_args = FakeBatchArgs(configs)
        self.filtered_configs = dict(filtered if filtered is not None else configs)
        self._config_checkboxes = {}
        self.job_queue = JobQueue()
        self.gui_calls = 0
        self.mcp_runs = []
        self.cancelled = 0

    def run_on_gui_thread(self, func, timeout=30.0):
        self.gui_calls += 1
        return func()

    def start_mcp_run(self, test, only_observers):
        self.mcp_runs.append((test, only_observers))
        return "run-id-1"

    def cancel_queued_runs(self):
        self.cancelled += 1
        return {"cancelled_queued": 0}


@pytest.fixture
def session():
    window = FakeWindow()
    return QtMainWindowMCPSession(window), window


class TestConfigs:
    def test_list_configs_reports_path_basename_and_state(self, session):
        adapter, _ = session
        listed = adapter.list_configs()
        assert listed == [
            {
                "path": "configs/a.yaml",
                "basename": "a.yaml",
                "will_run": True,
                "selected_for_run": True,
            }
        ]

    def test_a_filtered_out_config_is_listed_but_not_selected(self):
        """A search filter in the window narrows what a run covers, which is not
        the same as the config's own checkbox state."""
        window = FakeWindow(
            configs={"configs/a.yaml": True, "configs/b.yaml": True},
            filtered={"configs/a.yaml": True},
        )
        listed = QtMainWindowMCPSession(window).list_configs()
        by_path = {c["path"]: c for c in listed}
        assert by_path["configs/b.yaml"]["will_run"] is True
        assert by_path["configs/b.yaml"]["selected_for_run"] is False
        assert by_path["configs/a.yaml"]["selected_for_run"] is True

    def test_list_configs_is_marshalled(self, session):
        adapter, window = session
        adapter.list_configs()
        assert window.gui_calls == 1

    def test_read_config_parses_the_yaml(self, session):
        adapter, _ = session
        path = os.path.join(Config.configs_dir(), "readable.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump({"will_run": True, "actions": []}, handle)

        assert adapter.read_config("configs/readable.yaml") == {
            "will_run": True,
            "actions": [],
        }

    def test_read_config_is_not_marshalled(self, session):
        """A plain disk read gains nothing from a GUI round-trip."""
        adapter, window = session
        path = os.path.join(Config.configs_dir(), "readable.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump({"will_run": True}, handle)

        adapter.read_config("configs/readable.yaml")
        assert window.gui_calls == 0

    def test_missing_config_raises_file_not_found(self, session):
        adapter, _ = session
        with pytest.raises(FileNotFoundError):
            adapter.read_config("configs/not_here.yaml")

    def test_set_config_enabled_goes_through_the_checkbox(self, session):
        """toggle_config stays the single place a config's state changes."""
        adapter, window = session
        toggled = []
        window._config_checkboxes["configs/a.yaml"] = FakeCheckbox(
            checked=True, on_toggle=toggled.append
        )

        assert adapter.set_config_enabled("configs/a.yaml", False) is False
        assert toggled == [False]

    def test_already_in_the_wanted_state_updates_directly(self, session):
        """setChecked fires nothing when the state matches, so the adapter has
        to carry the write itself."""
        adapter, window = session
        toggled = []
        window._config_checkboxes["configs/a.yaml"] = FakeCheckbox(
            checked=True, on_toggle=toggled.append
        )

        assert adapter.set_config_enabled("configs/a.yaml", True) is True
        assert toggled == []
        assert window.batch_args.configs["configs/a.yaml"] is True

    def test_config_without_a_checkbox_is_updated_directly(self, session):
        adapter, window = session
        assert adapter.set_config_enabled("configs/a.yaml", False) is False
        assert window.batch_args.configs["configs/a.yaml"] is False
        assert window.filtered_configs["configs/a.yaml"] is False

    def test_unknown_config_raises_file_not_found(self, session):
        adapter, _ = session
        with pytest.raises(FileNotFoundError):
            adapter.set_config_enabled("configs/nope.yaml", True)


class TestRuns:
    def test_run_batch_passes_the_flags_through(self, session):
        adapter, window = session
        assert adapter.run_batch(test=False, only_observers=True) == "run-id-1"
        assert window.mcp_runs == [(False, True)]

    def test_run_batch_is_marshalled(self, session):
        adapter, window = session
        adapter.run_batch(test=True, only_observers=False)
        assert window.gui_calls == 1

    def test_cancel_batch_delegates_and_is_marshalled(self, session):
        adapter, window = session
        assert adapter.cancel_batch() == {"cancelled_queued": 0}
        assert window.cancelled == 1
        assert window.gui_calls == 1

    def test_run_status_reads_the_queue_directly(self, session):
        """JobQueue guards its own state, so status still answers while the
        window is busy."""
        adapter, window = session
        running = window.job_queue.begin()

        status = adapter.run_status(running)
        assert status["run_state"] == "running"
        assert status["running_id"] == running
        assert window.gui_calls == 0

    def test_run_status_without_an_id_reports_the_queue(self, session):
        adapter, window = session
        window.job_queue.add(JobQueue.new_run_id())
        status = adapter.run_status("")
        assert status["queued"] == 1
        assert "run_state" not in status


def _record(job_id, operations=0):
    return {
        "job_id": job_id,
        "started_at": "2026-09-21T00:00:00+00:00",
        "finished_at": "2026-09-21T00:01:00+00:00",
        "configs": ["configs/a.yaml"],
        "test": False,
        "cancelled": False,
        "failures": [],
        "action_counts": {"RENAMER": 1},
        "operations": [
            {"type": "rename", "source": f"s{i}", "dest": f"d{i}",
             "reversible": True, "reversed": False, "meta": {}}
            for i in range(operations)
        ],
        "reversible_operation_count": operations,
    }


class TestHistory:
    def test_job_history_is_newest_first(self, session):
        from refacdir.utils.app_info_cache import app_info_cache

        adapter, _ = session
        app_info_cache.prepend_batch_job_record(_record("older"))
        app_info_cache.prepend_batch_job_record(_record("newer"))

        assert [j["job_id"] for j in adapter.job_history(10)] == ["newer", "older"]

    def test_job_history_honours_the_limit(self, session):
        from refacdir.utils.app_info_cache import app_info_cache

        adapter, _ = session
        for i in range(5):
            app_info_cache.prepend_batch_job_record(_record(f"j{i}"))

        assert len(adapter.job_history(2)) == 2

    def test_job_history_carries_the_recorded_field_names(self, session):
        from refacdir.utils.app_info_cache import app_info_cache

        adapter, _ = session
        app_info_cache.prepend_batch_job_record(_record("j1", operations=3))
        entry = adapter.job_history(10)[0]
        assert entry["started_at"]
        assert entry["finished_at"]
        assert entry["operation_count"] == 3
        assert entry["reversible_operation_count"] == 3

    def test_job_history_omits_the_operation_list(self, session):
        from refacdir.utils.app_info_cache import app_info_cache

        adapter, _ = session
        app_info_cache.prepend_batch_job_record(_record("j1", operations=3))
        assert "operations" not in adapter.job_history(10)[0]

    def test_describe_job_summarises_and_samples(self, session):
        from refacdir.utils.app_info_cache import app_info_cache

        adapter, _ = session
        app_info_cache.prepend_batch_job_record(
            _record("j1", operations=JOB_OPERATION_SAMPLE + 10)
        )
        described = adapter.describe_job("j1")

        assert described["operation_count"] == JOB_OPERATION_SAMPLE + 10
        assert len(described["operation_sample"]) == JOB_OPERATION_SAMPLE
        assert described["action_counts"] == {"RENAMER": 1}
        assert isinstance(described["mapping_groups"], list)

    def test_describe_job_returns_none_for_an_unknown_id(self, session):
        adapter, _ = session
        assert adapter.describe_job("no-such-job") is None

    def test_history_is_not_marshalled(self, session):
        """The cache holds its own lock."""
        adapter, window = session
        adapter.job_history(5)
        adapter.describe_job("anything")
        assert window.gui_calls == 0
