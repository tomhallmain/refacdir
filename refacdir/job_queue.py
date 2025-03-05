
class JobQueue:
    def __init__(self, max_size=20):
        self.max_size = max_size
        self.pending_jobs = []
        self.job_running = False

    def has_pending(self):
        return self.job_running or len(self.pending_jobs) > 0

    def take(self):
        if len(self.pending_jobs) == 0:
            return None
        run_config = self.pending_jobs[0]
        del self.pending_jobs[0]
        return run_config

    def add(self, run_config):
        if len(self.pending_jobs) > self.max_size:
            raise Exception(f"Reached limit of pending runs: {self.max_size} - wait until current run has completed.")
        self.pending_jobs.append(run_config)
        print(f"Added pending job: {run_config}")
