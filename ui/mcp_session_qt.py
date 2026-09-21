"""Adapts a live MainWindow to the session interface extensions/mcp_server.py
calls through.

Kept out of that module so it stays free of any Qt dependency; the headless
entry point provides the other implementation of the same interface, against a
BatchArgs and a Qt-free AppActions instead of a window.

**What is marshalled, and what is not.** The MCP server answers on its own
thread. Anything reaching window state or a widget goes through
``MainWindow.run_on_gui_thread``; anything already guarded by its own lock does
not, because a GUI round-trip would add a way to block without adding safety:

- marshalled: the config list, enabling a config, starting a run, cancelling
  queued runs -- all of which read or write window state.
- not marshalled: run status (JobQueue holds a lock), job history (the cache
  holds one), and reading a config file (a plain disk read).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

import yaml

from refacdir.batch import BatchArgs
from refacdir.batch_job_history import JOB_OPERATION_SAMPLE, history_summaries, job_detail

if TYPE_CHECKING:
    from app_qt import MainWindow

class QtMainWindowMCPSession:
    """Session backed by one open ``MainWindow``."""

    def __init__(self, window: "MainWindow"):
        self._window = window

    # ------------------------------------------------------------------
    # Configs
    # ------------------------------------------------------------------
    def list_configs(self) -> list:
        """Every discovered config, with whether it is selected to run.

        ``selected_for_run`` is not the same as ``will_run``: a search filter in
        the window narrows what a run actually covers, and a config filtered out
        of view is not in that set however its own checkbox reads.
        """
        def read():
            window = self._window
            filtered = set(window.filtered_configs)
            return [
                {
                    "path": path,
                    "basename": os.path.basename(path.replace("\\", "/")),
                    "will_run": bool(will_run),
                    "selected_for_run": path in filtered,
                }
                for path, will_run in sorted(window.batch_args.configs.items())
            ]
        return self._window.run_on_gui_thread(read)

    def read_config(self, path: str) -> dict:
        """One config's YAML, parsed. A plain disk read, so not marshalled."""
        abs_path = BatchArgs.config_yaml_abs_path(path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(path)
        with open(abs_path, encoding="utf-8") as handle:
            return yaml.load(handle, Loader=yaml.FullLoader) or {}

    def set_config_enabled(self, path: str, enabled: bool) -> bool:
        """Select or deselect one config, as the checkbox does.

        Goes through the checkbox where there is one so ``toggle_config`` stays
        the single place a config's state changes -- it updates the args, writes
        the YAML back and schedules the settings save. A config with no checkbox
        yet is updated directly.
        """
        def apply():
            window = self._window
            if path not in window.batch_args.configs:
                raise FileNotFoundError(path)
            checkbox = window._config_checkboxes.get(path)
            if checkbox is not None and checkbox.isChecked() != enabled:
                checkbox.setChecked(enabled)
            else:
                window.batch_args.update_config_state(path, enabled)
                if path in window.filtered_configs:
                    window.filtered_configs[path] = enabled
                BatchArgs.write_will_run_to_file(path, enabled)
            return enabled
        return self._window.run_on_gui_thread(apply)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def run_batch(self, test: bool, only_observers: bool) -> str:
        return self._window.run_on_gui_thread(
            lambda: self._window.start_mcp_run(test=test, only_observers=only_observers)
        )

    def cancel_batch(self) -> dict:
        return self._window.run_on_gui_thread(self._window.cancel_queued_runs)

    def run_status(self, run_id: str) -> dict:
        """JobQueue guards its own state, so this answers without the GUI thread
        -- which also means it still answers while the window is busy."""
        return self._window.job_queue.status(run_id)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def job_history(self, limit: int) -> list:
        """Shaped by batch_job_history so every front end reports a job the
        same way. The cache holds its own lock, so this is not marshalled."""
        return history_summaries(limit)

    def describe_job(self, job_id: str) -> Optional[dict]:
        return job_detail(job_id, JOB_OPERATION_SAMPLE)
