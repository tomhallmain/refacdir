"""Unit tests for JobQueue's run identity model."""

import pytest

from refacdir.job_queue import JobQueue


def test_new_run_id_is_unique():
    assert JobQueue.new_run_id() != JobQueue.new_run_id()


def test_begin_mints_an_id_when_not_given_one():
    queue = JobQueue()
    run_id = queue.begin()
    assert run_id
    assert queue.running_id == run_id
    assert queue.job_running is True


def test_begin_keeps_the_id_it_was_given():
    """A queued run was told its id when it was accepted, long before it starts."""
    queue = JobQueue()
    accepted = JobQueue.new_run_id()
    queue.add(accepted)
    taken = queue.take()
    assert queue.begin(taken) == accepted
    assert queue.running_id == accepted


def test_finish_clears_the_running_id():
    queue = JobQueue()
    queue.begin()
    queue.finish()
    assert queue.running_id is None
    assert queue.job_running is False


def test_run_state_distinguishes_running_queued_and_unknown():
    queue = JobQueue()
    running = queue.begin()
    queued = queue.add(JobQueue.new_run_id())

    assert queue.run_state(running) == "running"
    assert queue.run_state(queued) == "queued"
    assert queue.run_state(JobQueue.new_run_id()) == "unknown"
    assert queue.run_state("") == "unknown"


def test_finished_run_reads_as_unknown():
    """Nothing here remembers completed runs; history answers for those."""
    queue = JobQueue()
    run_id = queue.begin()
    queue.finish()
    assert queue.run_state(run_id) == "unknown"


def test_status_reports_the_queue_without_a_run_id():
    queue = JobQueue()
    assert queue.status() == {"running": False, "running_id": None, "queued": 0}

    running = queue.begin()
    queue.add(JobQueue.new_run_id())
    status = queue.status()
    assert status["running"] is True
    assert status["running_id"] == running
    assert status["queued"] == 1
    assert "run_state" not in status


def test_status_answers_about_one_run_when_asked():
    queue = JobQueue()
    queued = queue.add(JobQueue.new_run_id())
    status = queue.status(queued)
    assert status["run_id"] == queued
    assert status["run_state"] == "queued"


def test_job_running_setter_still_works_for_existing_call_sites():
    queue = JobQueue()
    queue.job_running = True
    assert queue.running_id is not None
    queue.job_running = False
    assert queue.running_id is None


def test_job_running_setter_does_not_replace_a_live_id():
    queue = JobQueue()
    run_id = queue.begin()
    queue.job_running = True
    assert queue.running_id == run_id


def test_add_returns_the_id_and_take_pops_in_order():
    queue = JobQueue()
    first = queue.add("a")
    second = queue.add("b")
    assert (first, second) == ("a", "b")
    assert queue.take() == "a"
    assert queue.take() == "b"
    assert queue.take() is None


def test_add_past_max_size_raises():
    queue = JobQueue(max_size=2)
    queue.add("a")
    queue.add("b")
    with pytest.raises(Exception, match="Reached limit of pending runs"):
        queue.add("c")


def test_cancel_clears_the_queue_but_not_the_running_run():
    queue = JobQueue()
    running = queue.begin()
    queue.add(JobQueue.new_run_id())
    queue.cancel()
    assert queue.status()["queued"] == 0
    assert queue.running_id == running


def test_has_pending_covers_running_and_queued():
    queue = JobQueue()
    assert queue.has_pending() is False
    queue.add("a")
    assert queue.has_pending() is True
    queue.take()
    assert queue.has_pending() is False
    queue.begin()
    assert queue.has_pending() is True
