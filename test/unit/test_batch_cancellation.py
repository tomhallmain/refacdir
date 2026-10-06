"""Cancelling a BatchJob in flight through ``BatchArgs.cancel_event``."""

from __future__ import annotations

import os
import textwrap

import pytest

from refacdir.batch import BatchArgs, BatchJob
from refacdir.batch_job_history import get_batch_job_history
from refacdir.config import Config


class _RecordingAction:
    """Stands in for a constructed action; ``on_run`` lets a test act mid-batch."""

    def __init__(self, name, ran, on_run=None):
        self.name = name
        self._ran = ran
        self._on_run = on_run

    def run(self):
        self._ran.append(self.name)
        if self._on_run is not None:
            self._on_run(self.name)


def _write_config(name: str, mapping_names: list) -> str:
    mappings = "\n".join(f"      - name: {m}" for m in mapping_names)
    content = textwrap.dedent(
        """
        will_run: true
        actions:
          - type: DIRECTORY_OBSERVER
            mappings:
        """
    ).strip("\n") + "\n" + mappings + "\n"
    with open(os.path.join(Config.configs_dir(), name), "w", encoding="utf-8") as handle:
        handle.write(content)
    return f"configs/{name}"


class _Names(list):
    """Run order of the recorded actions, plus what the test wants cancelled."""

    cancel_after = None
    args = None


def _job(configs: dict, *, test: bool = True) -> BatchJob:
    args = BatchArgs(configs=configs)
    args.test = test
    return BatchJob(args)


@pytest.fixture
def recorder(monkeypatch):
    names = _Names()
    names.cancel_after = None
    names.args = None

    def construct(self, yaml_dict):
        def on_run(name):
            if name == names.cancel_after:
                names.args.cancel_event.set()

        return _RecordingAction(yaml_dict["name"], names, on_run)

    monkeypatch.setattr(BatchJob, "construct_directory_observer", construct)
    return names


def test_cancel_before_run_runs_nothing(recorder):
    key = _write_config("a.yaml", ["first"])
    job = _job({key: True})
    job.args.cancel_event.set()

    job.run()

    assert recorder == []
    assert job.cancelled is True


def test_cancel_stops_before_the_next_mapping(recorder):
    key = _write_config("a.yaml", ["first", "second", "third"])
    job = _job({key: True})
    recorder.args = job.args
    recorder.cancel_after = "first"

    job.run()

    assert recorder == ["first"]
    assert job.cancelled is True
    assert job.failures == []


def test_cancel_stops_before_the_next_config(recorder):
    first = _write_config("a.yaml", ["a1"])
    second = _write_config("b.yaml", ["b1"])
    job = _job({first: True, second: True})
    recorder.args = job.args
    recorder.cancel_after = "a1"

    job.run()

    assert recorder == ["a1"]
    assert job.cancelled is True


def test_uncancelled_run_completes(recorder):
    key = _write_config("a.yaml", ["first", "second"])
    job = _job({key: True})

    job.run()

    assert recorder == ["first", "second"]
    assert job.cancelled is False


def test_cancelled_live_run_is_recorded_as_cancelled(recorder):
    key = _write_config("a.yaml", ["first", "second"])
    job = _job({key: True}, test=False)
    recorder.args = job.args
    recorder.cancel_after = "first"

    job.run()

    assert get_batch_job_history()[0]["cancelled"] is True


def test_each_batch_args_has_its_own_cancel_event():
    assert BatchArgs(configs={"x": True}).cancel_event is not BatchArgs(configs={"x": True}).cancel_event
