"""Tests for the batch job queue."""

from refacdir.job_queue import JobQueue


def test_job_queue_add_and_take_fifo():
    queue = JobQueue(max_size=5)
    queue.add("first")
    queue.add("second")

    assert queue.take() == "first"
    assert queue.take() == "second"
    assert queue.take() is None


def test_job_queue_has_pending():
    queue = JobQueue()
    assert queue.has_pending() is False

    queue.job_running = True
    assert queue.has_pending() is True

    queue.job_running = False
    queue.add("run")
    assert queue.has_pending() is True


def test_job_queue_max_size_raises():
    queue = JobQueue(max_size=1)
    queue.add("only")

    try:
        queue.add("overflow")
        raised = False
    except Exception:
        raised = True

    assert raised
