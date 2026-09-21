"""The headless session's own logic.

Batch execution is stubbed throughout: what matters here is the session
contract, the run identity model, and that a run started with no GUI cannot
reach a prompt. Running a real BatchJob would test refacdir, not this.
"""

import os
import threading

import pytest
import yaml

from app_headless import HeadlessMCPSession, _parse_configs, main
from refacdir.config import Config
from refacdir.utils.headless_app_actions import HeadlessActionUnavailable


@pytest.fixture
def session(monkeypatch):
    """A session whose runs record their BatchArgs instead of executing."""
    started = []

    def fake_execute(args):
        started.append(args)

    monkeypatch.setattr("app_headless._execute_batch", fake_execute)
    return HeadlessMCPSession(configs={"configs/a.yaml": True}), started


def _wait_for(predicate, timeout=5.0):
    deadline = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        deadline.wait(0.01)
        waited += 0.01
    return False


class TestConfigs:
    def test_list_configs_reports_the_selection(self, session):
        adapter, _ = session
        assert adapter.list_configs() == [
            {
                "path": "configs/a.yaml",
                "basename": "a.yaml",
                "will_run": True,
                "selected_for_run": True,
            }
        ]

    def test_selected_for_run_tracks_will_run_with_no_filter(self, session):
        """A headless session has no search box narrowing a run."""
        adapter, _ = session
        adapter.set_config_enabled("configs/a.yaml", False)
        entry = adapter.list_configs()[0]
        assert entry["will_run"] is False
        assert entry["selected_for_run"] is False

    def test_read_config_parses_the_yaml(self, session):
        adapter, _ = session
        path = os.path.join(Config.configs_dir(), "readable.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump({"will_run": True, "actions": []}, handle)
        assert adapter.read_config("configs/readable.yaml")["will_run"] is True

    def test_unknown_config_raises_file_not_found(self, session):
        adapter, _ = session
        with pytest.raises(FileNotFoundError):
            adapter.read_config("configs/nope.yaml")
        with pytest.raises(FileNotFoundError):
            adapter.set_config_enabled("configs/nope.yaml", True)

    def test_refresh_configs_keeps_a_still_valid_selection(self, session, monkeypatch):
        adapter, _ = session
        adapter.set_config_enabled("configs/a.yaml", False)
        monkeypatch.setattr(
            "refacdir.batch.BatchArgs.discover_configs_from_disk",
            classmethod(lambda cls: {"configs/a.yaml": True, "configs/new.yaml": True}),
        )
        adapter.refresh_configs()
        by_path = {c["path"]: c["will_run"] for c in adapter.list_configs()}
        assert by_path["configs/a.yaml"] is False   # the user's choice survives
        assert by_path["configs/new.yaml"] is True  # newly discovered


class TestRuns:
    def test_run_batch_returns_an_id_and_executes(self, session):
        adapter, started = session
        run_id = adapter.run_batch(test=True, only_observers=False)
        assert run_id
        assert _wait_for(lambda: len(started) == 1)

    def test_a_run_never_asks_for_confirmation(self, session):
        """Nobody is at the keyboard; the prompts this suppresses read stdin."""
        adapter, started = session
        adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: len(started) == 1)
        assert started[0].skip_confirm is True

    def test_flags_reach_the_batch_args(self, session):
        adapter, started = session
        adapter.run_batch(test=False, only_observers=True)
        assert _wait_for(lambda: len(started) == 1)
        assert started[0].test is False
        assert started[0].only_observers is True

    def test_the_app_actions_behind_a_run_decline_the_duplicate_review(self, session):
        """The whole reason a headless run cannot hang."""
        adapter, started = session
        adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: len(started) == 1)
        decision = started[0].app_actions.review_duplicates({"total_duplicate_files": 2})
        assert decision == {"action": "cancel", "files": []}

    def test_run_status_tracks_a_finished_run_as_unknown(self, session):
        adapter, started = session
        run_id = adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: adapter.run_status(run_id)["run_state"] == "unknown")

    def test_a_second_run_queues_behind_the_first(self, session, monkeypatch):
        release = threading.Event()
        started = []

        def blocking_execute(args):
            started.append(args)
            release.wait(5)

        monkeypatch.setattr("app_headless._execute_batch", blocking_execute)
        adapter, _ = session

        first = adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: len(started) == 1)
        second = adapter.run_batch(test=True, only_observers=False)

        assert adapter.run_status(first)["run_state"] == "running"
        assert adapter.run_status(second)["run_state"] == "queued"

        release.set()
        assert _wait_for(lambda: len(started) == 2)

    def test_a_queued_run_keeps_its_own_flags(self, session, monkeypatch):
        """The queued run's test flag must not be taken from whatever ran first."""
        release = threading.Event()
        started = []

        def blocking_execute(args):
            started.append(args)
            release.wait(5)

        monkeypatch.setattr("app_headless._execute_batch", blocking_execute)
        adapter, _ = session

        adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: len(started) == 1)
        adapter.run_batch(test=False, only_observers=True)
        release.set()

        assert _wait_for(lambda: len(started) == 2)
        assert started[1].test is False
        assert started[1].only_observers is True

    def test_cancel_drops_queued_runs_only(self, session, monkeypatch):
        release = threading.Event()
        started = []

        def blocking_execute(args):
            started.append(args)
            release.wait(5)

        monkeypatch.setattr("app_headless._execute_batch", blocking_execute)
        adapter, _ = session

        first = adapter.run_batch(test=True, only_observers=False)
        assert _wait_for(lambda: len(started) == 1)
        adapter.run_batch(test=True, only_observers=False)

        assert adapter.cancel_batch() == {"cancelled_queued": 1}
        assert adapter.run_status(first)["run_state"] == "running"
        release.set()
        assert _wait_for(lambda: adapter.run_status(first)["run_state"] == "unknown")


class TestDomainActions:
    def test_get_batch_args_is_supplied(self, session):
        adapter, _ = session
        actions = adapter._app_actions
        assert actions.get_batch_args() is adapter._batch_args

    def test_refresh_configs_is_supplied(self, session):
        adapter, _ = session
        # Would raise if the builder had left it unsupplied.
        assert adapter._app_actions.refresh_configs() is None

    def test_no_domain_action_is_left_unsupplied(self, session):
        from refacdir.utils.headless_app_actions import missing_domain_actions

        adapter, _ = session
        assert missing_domain_actions(adapter._app_actions) == []


class TestArgumentParsing:
    def test_no_configs_means_discover_from_disk(self):
        assert _parse_configs(None) is None
        assert _parse_configs("") is None
        assert _parse_configs("  ,  ") is None

    def test_configs_are_split_and_selected(self):
        assert _parse_configs("configs/a.yaml, configs/b.yaml") == {
            "configs/a.yaml": True,
            "configs/b.yaml": True,
        }


class TestEntryPoint:
    def test_a_refusal_to_serve_is_fatal(self, monkeypatch):
        """Serving is all this process does, so it exits rather than idling."""
        monkeypatch.setattr("app_headless._execute_batch", lambda args: None)
        assert main(["--port", "0"]) == 2

    def test_non_loopback_is_refused(self, monkeypatch):
        monkeypatch.setattr("app_headless._execute_batch", lambda args: None)
        assert main(["--port", "6200", "--host", "0.0.0.0"]) == 2

    def test_a_configured_token_is_refused(self, monkeypatch):
        monkeypatch.setattr("app_headless._execute_batch", lambda args: None)
        assert main(["--port", "6200", "--token", "hunter2"]) == 2
