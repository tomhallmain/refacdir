#!/usr/bin/env python3
"""RefacDir -- persistent headless entry point.

No QApplication, no window: this process holds one set of configs open for its
lifetime and serves it over MCP (extensions/mcp_server.py), for an agent to
drive with no GUI involved.

It implements the same session interface ui/mcp_session_qt.py does for a live
window, so the server is unchanged between the two. The differences are all
below the interface: there is no GUI thread to marshal onto, so nothing is, and
the AppActions behind a run is the Qt-free build -- which logs instead of
showing, and declines the duplicate review instead of waiting on a person who
is not there.

Confirmation is forced off for every run started here. Nobody is at the
keyboard, and the prompts the action modules would otherwise raise read from
stdin.

Run it:
    python app_headless.py --port 6200
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import yaml

from extensions.mcp_server import MCPServerExtension
from refacdir.batch import BatchArgs, BatchJob
from refacdir.batch_job_history import (
    JOB_OPERATION_SAMPLE,
    history_summaries,
    job_detail,
)
from refacdir.job_queue import JobQueue
from refacdir.utils.background_runner import ThreadedTaskRunner
from refacdir.utils.headless_app_actions import build_headless_app_actions
from refacdir.utils.logger import setup_logger

logger = setup_logger("app_headless")


def _execute_batch(args: BatchArgs) -> None:
    """Run one batch to completion. Called on the runner's worker thread.

    Calls BatchJob directly rather than going through run.py, which is a CLI
    front end on its way out.
    """
    job = BatchJob(args)
    job.run()
    job.log_results()


class HeadlessMCPSession:
    """Session backed by a set of configs rather than a window.

    Nothing here marshals: there is no event loop to protect, and the state it
    guards is already behind JobQueue's lock or the cache's.
    """

    def __init__(self, configs: Optional[dict] = None):
        self._batch_args = BatchArgs(
            recache_configs=configs is None,
            configs=configs if configs is not None else {},
        )
        self._queue = JobQueue()
        self._runner = ThreadedTaskRunner()
        self._overrides: dict = {}
        self._app_actions = build_headless_app_actions({
            "get_batch_args": lambda: self._batch_args,
            "refresh_configs": self.refresh_configs,
        })

    # ------------------------------------------------------------------
    # Domain actions the Qt-free AppActions build asks the caller for
    # ------------------------------------------------------------------
    def refresh_configs(self) -> None:
        """Re-read the configs directory, keeping any selection still valid."""
        current = dict(self._batch_args.configs)
        discovered = BatchArgs.discover_configs_from_disk()
        self._batch_args.configs = {
            path: current.get(path, will_run) for path, will_run in discovered.items()
        }
        logger.info(f"Configs refreshed: {len(self._batch_args.configs)} found")

    # ------------------------------------------------------------------
    # Configs
    # ------------------------------------------------------------------
    def list_configs(self) -> list:
        """Every discovered config. ``selected_for_run`` matches ``will_run``
        here -- a headless session has no search filter narrowing a run."""
        return [
            {
                "path": path,
                "basename": os.path.basename(path.replace("\\", "/")),
                "will_run": bool(will_run),
                "selected_for_run": bool(will_run),
            }
            for path, will_run in sorted(self._batch_args.configs.items())
        ]

    def read_config(self, path: str) -> dict:
        abs_path = BatchArgs.config_yaml_abs_path(path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(path)
        with open(abs_path, encoding="utf-8") as handle:
            return yaml.load(handle, Loader=yaml.FullLoader) or {}

    def set_config_enabled(self, path: str, enabled: bool) -> bool:
        if path not in self._batch_args.configs:
            raise FileNotFoundError(path)
        self._batch_args.update_config_state(path, enabled)
        BatchArgs.write_will_run_to_file(path, enabled)
        return enabled

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def run_batch(self, test: bool, only_observers: bool) -> str:
        """Accept a run and return its id, queueing it if one is in flight."""
        run_id = JobQueue.new_run_id()
        self._overrides[run_id] = {
            "test": bool(test),
            "only_observers": bool(only_observers),
        }
        if self._queue.job_running:
            try:
                self._queue.add(run_id)
            except Exception:
                del self._overrides[run_id]
                raise
            logger.info(f"Batch run queued: {run_id}")
            return run_id
        self._start(run_id)
        return run_id

    def _start(self, run_id: str) -> None:
        self._queue.begin(run_id)
        overrides = self._overrides.pop(run_id, {})

        args = BatchArgs(recache_configs=False, configs=dict(self._batch_args.configs))
        args.test = overrides.get("test", True)
        args.only_observers = overrides.get("only_observers", False)
        # Never negotiable here: the prompts this suppresses read from stdin,
        # and nothing is attached to it.
        args.skip_confirm = True
        args.app_actions = self._app_actions

        logger.info(f"Batch run started: {run_id} (test={args.test})")
        self._runner.start(
            _execute_batch,
            (args,),
            on_finished=self._on_run_finished,
            on_error=lambda message: logger.error(f"Batch run failed: {message}"),
            cancelled_exceptions=(KeyboardInterrupt,),
        )

    def _on_run_finished(self) -> None:
        """Runs on the worker thread once a batch returns.

        The runner reports itself idle before calling this, so starting the
        next queued run from here does not hit its already-running guard.
        """
        self._queue.finish()
        next_run_id = self._queue.take()
        if next_run_id is not None:
            self._start(next_run_id)

    def cancel_batch(self) -> dict:
        queued = self._queue.status()["queued"]
        self._queue.cancel()
        self._overrides.clear()
        return {"cancelled_queued": queued}

    def run_status(self, run_id: str) -> dict:
        return self._queue.status(run_id)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def job_history(self, limit: int) -> list:
        return history_summaries(limit)

    def describe_job(self, job_id: str) -> Optional[dict]:
        return job_detail(job_id, JOB_OPERATION_SAMPLE)

    def wait_for_run(self, timeout: Optional[float] = None) -> bool:
        """Block until the running batch finishes. For a caller with no event
        loop; the server itself never needs it."""
        return self._runner.wait(timeout)


def _parse_configs(raw: Optional[str]) -> Optional[dict]:
    """Turn --configs into a selection, or None to discover from disk."""
    if not raw:
        return None
    paths = [p.strip() for p in raw.split(",") if p.strip()]
    if not paths:
        return None
    return {path: True for path in paths}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hold a RefacDir session open with no GUI and serve it over MCP, "
            "for an agent to drive."
        )
    )
    parser.add_argument(
        "--configs",
        default=None,
        help="Comma-separated config paths to select. Default: discover them, "
             "each with the will_run its own YAML sets.",
    )
    parser.add_argument("--host", default=None, help="default: config.mcp_server_host")
    parser.add_argument("--port", type=int, default=None, help="default: config.mcp_server_port")
    parser.add_argument("--token", default=None, help="default: config.mcp_server_token")
    args = parser.parse_args(argv)

    session = HeadlessMCPSession(_parse_configs(args.configs))
    logger.info(f"Headless session ready: {len(session.list_configs())} config(s)")

    server = MCPServerExtension(
        session_resolver=lambda: session,
        host=args.host,
        port=args.port,
        token=args.token,
    )
    refusal = server.refuses_to_start()
    if refusal:
        # Serving is the only thing this process does, so a refusal is fatal
        # here rather than the warning it is alongside a window.
        logger.error(f"Cannot serve MCP: {refusal}")
        return 2

    if not server.start():
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
