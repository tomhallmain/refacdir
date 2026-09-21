"""Unit tests for the Qt-free background task runner."""

import threading

import pytest

from refacdir.utils.background_runner import ThreadedTaskRunner


class _Cancelled(Exception):
    """Stands in for whatever a caller names as its cancellation signal."""


def test_runs_the_task_with_its_arguments():
    runner = ThreadedTaskRunner()
    seen = []
    runner.start(lambda *a: seen.append(a), ("x", 1))
    assert runner.wait(5) is True
    assert seen == [("x", 1)]


def test_on_finished_runs_after_success():
    runner = ThreadedTaskRunner()
    done = threading.Event()
    runner.start(lambda: None, on_finished=done.set)
    assert done.wait(5) is True


def test_on_error_receives_the_failure_and_on_finished_still_runs():
    runner = ThreadedTaskRunner()
    errors = []
    done = threading.Event()

    def boom():
        raise ValueError("exploded")

    runner.start(boom, on_error=errors.append, on_finished=done.set)
    assert done.wait(5) is True
    assert errors == ["exploded"]


def test_cancelled_exceptions_are_swallowed_not_reported():
    """Cancelling is a normal outcome, not an error."""
    runner = ThreadedTaskRunner()
    errors = []
    done = threading.Event()

    def cancel():
        raise _Cancelled()

    runner.start(
        cancel,
        on_error=errors.append,
        on_finished=done.set,
        cancelled_exceptions=(_Cancelled,),
    )
    assert done.wait(5) is True
    assert errors == []


def test_starting_while_running_raises():
    runner = ThreadedTaskRunner()
    release = threading.Event()
    runner.start(release.wait)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            runner.start(lambda: None)
    finally:
        release.set()
        runner.wait(5)


def test_is_running_reports_false_inside_on_finished():
    """A caller starting the next queued run from on_finished must not hit the
    already-running guard."""
    runner = ThreadedTaskRunner()
    observed = []
    done = threading.Event()

    def finished():
        observed.append(runner.is_running())
        done.set()

    runner.start(lambda: None, on_finished=finished)
    assert done.wait(5) is True
    assert observed == [False]


def test_a_second_task_can_start_from_on_finished():
    runner = ThreadedTaskRunner()
    second_done = threading.Event()

    def finished():
        # Only the first task schedules another, or this would not terminate.
        if not second_done.is_set():
            runner.start(lambda: None, on_finished=second_done.set)

    runner.start(lambda: None, on_finished=finished)
    assert second_done.wait(5) is True


def test_wait_returns_true_when_nothing_is_running():
    assert ThreadedTaskRunner().wait(0) is True


def test_progress_is_forwarded_with_an_indeterminate_sentinel():
    runner = ThreadedTaskRunner()
    reports = []
    done = threading.Event()

    def work():
        runner.report_progress("scanning", 50)
        runner.report_progress("indeterminate")

    runner.start(work, on_progress=lambda c, p: reports.append((c, p)), on_finished=done.set)
    assert done.wait(5) is True
    assert reports == [("scanning", 50), ("indeterminate", -1)]


def test_progress_after_the_task_is_dropped():
    runner = ThreadedTaskRunner()
    reports = []
    done = threading.Event()
    runner.start(lambda: None, on_progress=lambda c, p: reports.append((c, p)), on_finished=done.set)
    assert done.wait(5) is True
    runner.report_progress("late", 10)
    assert reports == []


def test_on_finished_raising_does_not_escape():
    runner = ThreadedTaskRunner()

    def boom():
        raise ValueError("finish exploded")

    runner.start(lambda: None, on_finished=boom)
    assert runner.wait(5) is True
    assert runner.is_running() is False
