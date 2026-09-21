import threading
import uuid

from refacdir.utils.logger import setup_logger

# Set up logger for job queue
logger = setup_logger('job_queue')


class JobQueue:
    """Sequences batch runs, and is the identity model for a run in flight.

    A run gets its id when it is *accepted*, not when it starts. A client told
    "accepted" has nothing else to ask about until the run reaches the front of
    the queue, and by then the answer it was given has to still mean something.

    Read from the thread that accepts runs and from whatever serves status, so
    every field is behind the lock.
    """

    def __init__(self, max_size=20):
        self.max_size = max_size
        self.pending_jobs = []
        self._running_id = None
        self._lock = threading.RLock()

    @staticmethod
    def new_run_id() -> str:
        return uuid.uuid4().hex

    # ------------------------------------------------------------------
    # job_running stays a property so existing `queue.job_running = True/False`
    # call sites keep working while the id underneath is what is really tracked.
    # ------------------------------------------------------------------
    @property
    def job_running(self) -> bool:
        with self._lock:
            return self._running_id is not None

    @job_running.setter
    def job_running(self, value: bool) -> None:
        with self._lock:
            if value:
                if self._running_id is None:
                    self._running_id = self.new_run_id()
            else:
                self._running_id = None

    def begin(self, run_id: str = None) -> str:
        """Mark a run started and return its id, minting one if not given."""
        with self._lock:
            self._running_id = run_id or self.new_run_id()
            return self._running_id

    def finish(self) -> None:
        with self._lock:
            self._running_id = None

    @property
    def running_id(self):
        with self._lock:
            return self._running_id

    def has_pending(self):
        with self._lock:
            return self._running_id is not None or len(self.pending_jobs) > 0

    def take(self):
        with self._lock:
            if len(self.pending_jobs) == 0:
                return None
            return self.pending_jobs.pop(0)

    def add(self, run_config):
        with self._lock:
            if len(self.pending_jobs) >= self.max_size:
                raise Exception(f"Reached limit of pending runs: {self.max_size} - wait until current run has completed.")
            self.pending_jobs.append(run_config)
        logger.info(f"Added pending job: {run_config}")
        return run_config

    def cancel(self) -> None:
        """Drop everything queued. The run in flight is stopped by its own caller."""
        with self._lock:
            self.pending_jobs = []

    def run_state(self, run_id: str) -> str:
        """Where *run_id* stands: running, queued, or unknown.

        Unknown covers both a finished run and one that never existed. Nothing
        here remembers completed runs -- batch_job_history is what answers for
        those, and only for runs that were not dry runs.
        """
        if not run_id:
            return "unknown"
        with self._lock:
            if run_id == self._running_id:
                return "running"
            if run_id in self.pending_jobs:
                return "queued"
        return "unknown"

    def status(self, run_id: str = "") -> dict:
        """A snapshot for a status reader, taken under one lock acquisition."""
        with self._lock:
            status = {
                "running": self._running_id is not None,
                "running_id": self._running_id,
                "queued": len(self.pending_jobs),
            }
            if run_id:
                status["run_id"] = run_id
                status["run_state"] = self.run_state(run_id)
        return status
