"""Qt-free background execution for long-running work such as a batch run.

The Qt path runs the batch on a thread and marshals completion back to the GUI
thread with a timer. None of that is available without a QApplication, but the
work itself is plain Python -- so what has to be swappable is the execution
strategy, not the function being executed.

This is the strategy a caller with no event loop uses: a daemon thread, with
the callbacks delivered directly. Because there is no GUI thread to marshal
onto, callbacks run on the worker thread; a caller that mutates shared state
from them does its own locking, as it would for any other thread.

- Exception types named in cancelled_exceptions are swallowed. Cancelling is a
  normal outcome, not an error, and the caller names them so this module stays
  independent of what it is running.
- Any other exception is reported through on_error as its string form.
- on_finished always runs, success or failure.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Optional, Sequence

from refacdir.utils.logger import setup_logger

logger = setup_logger("background_runner")


class ThreadedTaskRunner:
    """Runs one task at a time on a daemon thread.

    One at a time, because a second batch starting while one is in flight is a
    caller error rather than something to queue -- JobQueue is what sequences
    runs, and it sits in front of this.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._on_progress: Optional[Callable[[str, int], None]] = None

    def start(
        self,
        func: Callable[..., Any],
        args: Sequence[Any] = (),
        *,
        on_finished: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str, int], None]] = None,
        cancelled_exceptions: tuple = (),
    ) -> None:
        """Run *func(*args)* on a background thread.

        Raises RuntimeError if a task is already running, rather than silently
        dropping either task.
        """
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("A task is already running on this runner.")
            self._on_progress = on_progress
            thread = threading.Thread(
                target=self._run,
                args=(func, tuple(args), on_finished, on_error, cancelled_exceptions),
                daemon=True,
            )
            self._thread = thread
        thread.start()

    def _run(
        self,
        func: Callable[..., Any],
        args: tuple,
        on_finished: Optional[Callable[[], None]],
        on_error: Optional[Callable[[str], None]],
        cancelled_exceptions: tuple,
    ) -> None:
        try:
            try:
                func(*args)
            except cancelled_exceptions:
                logger.debug("Task cancelled.")
            except Exception as e:
                logger.error(traceback.format_exc())
                if on_error is not None:
                    on_error(str(e))
        finally:
            # Cleared before on_finished so is_running() reports False for the
            # duration of that callback -- a caller that starts the next queued
            # run from it would otherwise hit the already-running guard.
            with self._lock:
                self._thread = None
                self._on_progress = None
            if on_finished is not None:
                try:
                    on_finished()
                except Exception:
                    logger.exception("on_finished callback raised.")

    def is_running(self) -> bool:
        """True from start() until the task function has returned."""
        with self._lock:
            return self._thread is not None

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the running task finishes. True if nothing is still running.

        The Qt path never needs this -- its event loop keeps turning while the
        worker runs -- but a headless caller has nothing else to wait on.
        """
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def report_progress(self, context: str, percent_complete: Optional[int] = None) -> None:
        """Forward a progress report from the worker thread.

        Percent is normalised to a -1 sentinel for "indeterminate", so a caller
        gets the same values whichever strategy produced them.
        """
        with self._lock:
            on_progress = self._on_progress
        if on_progress is None:
            return
        on_progress(context, int(percent_complete) if percent_complete is not None else -1)
