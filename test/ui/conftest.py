"""
Pytest fixtures for Qt UI tests (pytest-qt).

Use the ``qtbot`` fixture from pytest-qt when constructing widgets; call
``qtbot.addWidget(widget)`` so the widget is tracked and destroyed cleanly.

Cache/config isolation comes from root ``test/conftest.py`` (``isolated_app_singletons``).
"""

from __future__ import annotations

import pytest

from refacdir.batch import BatchArgs
from refacdir.config import Config
from ui.app_actions import AppActions


@pytest.fixture
def session_batch_args():
    """Session ``BatchArgs`` for UI tests that mirror the main window config state."""
    return BatchArgs(recache_configs=False, configs={})


def merge_preserving_refresh_configs(batch_args: BatchArgs, current_configs: dict | None = None) -> None:
    """
    Mirror ``MainWindow._refresh_configs`` merge logic for UI tests.

    Re-scans disk via ``batch_args.setup_configs`` but keeps in-session checkbox
    selections for configs that already existed.
    """
    current = dict(current_configs if current_configs is not None else batch_args.configs)
    batch_args.setup_configs(recache=True)
    merged = dict(batch_args.configs)
    for path in merged:
        if path in current:
            merged[path] = current[path]
    batch_args.configs = merged


@pytest.fixture
def noop_app_actions(session_batch_args):
    """Minimal ``AppActions`` with no-op callbacks for editor/window tests."""

    def _noop(*_args, **_kwargs):
        return None

    return AppActions(
        {
            "toast": _noop,
            "alert": _noop,
            "progress_text": _noop,
            "progress_bar_update": _noop,
            "progress_bar_reset": _noop,
            "refresh_configs": _noop,
            "review_duplicates": lambda _payload: {"action": "cancel", "files": []},
            "get_batch_args": lambda: session_batch_args,
        }
    )


def write_runnable_config(name: str, *, will_run: bool = True) -> str:
    """Write a minimal runnable YAML config under the isolated configs directory."""
    rel_path = f"configs/{name}"
    content = (
        f"will_run: {'true' if will_run else 'false'}\n"
        "filename_mapping_functions: []\n"
        "filetype_definitions: []\n"
        "actions: []\n"
    )
    import os

    with open(os.path.join(Config.configs_dir(), name), "w", encoding="utf-8") as handle:
        handle.write(content)
    return rel_path


def write_config_content(name: str, content: str) -> str:
    """Write raw YAML content under the isolated configs directory."""
    import os

    with open(os.path.join(Config.configs_dir(), name), "w", encoding="utf-8") as handle:
        handle.write(content)
    return f"configs/{name}"


def read_config_file(name: str) -> str:
    """Read raw YAML from the isolated configs directory."""
    import os

    with open(os.path.join(Config.configs_dir(), name), encoding="utf-8") as handle:
        return handle.read()
