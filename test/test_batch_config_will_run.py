"""Tests for file-level will_run sync between YAML and BatchArgs.configs."""

from __future__ import annotations

import os
import textwrap

import yaml

from refacdir.batch import BatchArgs, BatchJob
from refacdir.config import Config
from test.test_utils import patch_batch_job_base_dir, posix_path


def _write_config(name: str, *, will_run: bool, actions_yaml: str = "actions: []") -> str:
    rel_path = f"configs/{name}"
    content = textwrap.dedent(
        f"""
        will_run: {'true' if will_run else 'false'}
        filename_mapping_functions: []
        filetype_definitions: []
        {actions_yaml}
        """
    ).strip()
    with open(os.path.join(Config.configs_dir(), name), "w", encoding="utf-8") as handle:
        handle.write(content)
    return rel_path


def test_setup_configs_reads_will_run_from_yaml():
    _write_config("disabled.yaml", will_run=False)
    _write_config("enabled.yaml", will_run=True)

    BatchArgs.setup_configs(recache=True)

    assert BatchArgs.configs["configs/disabled.yaml"] is False
    assert BatchArgs.configs["configs/enabled.yaml"] is True


def test_setup_configs_defaults_will_run_true_when_key_missing():
    rel_path = "configs/no_flag.yaml"
    with open(os.path.join(Config.configs_dir(), "no_flag.yaml"), "w", encoding="utf-8") as handle:
        handle.write("actions: []\n")

    BatchArgs.setup_configs(recache=True)

    assert BatchArgs.configs[rel_path] is True


def test_write_will_run_to_file_updates_yaml():
    rel_path = _write_config("toggle_me.yaml", will_run=True)

    BatchArgs.write_will_run_to_file(rel_path, False)

    with open(BatchArgs.config_yaml_abs_path(rel_path), encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert data["will_run"] is False


def test_write_will_run_to_file_noop_when_unchanged():
    rel_path = _write_config("unchanged.yaml", will_run=True)
    abs_path = BatchArgs.config_yaml_abs_path(rel_path)
    before_mtime = os.path.getmtime(abs_path)

    BatchArgs.write_will_run_to_file(rel_path, True)

    assert os.path.getmtime(abs_path) == before_mtime


def test_run_config_file_skips_when_yaml_will_run_false(
    tmp_path, monkeypatch, restore_batch_configs
):
    """YAML will_run=false is a second safety gate even if BatchArgs.configs says run."""
    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    cfg = tmp_path / "skip_flag.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            will_run: false
            actions:
              - type: "DIRECTORY_OBSERVER"
                mappings:
                  - name: observer
                    sortable_dirs: []
                    extra_dirs: []
                    parent_dirs: []
                    exclude_dirs: []
                    file_types: [".txt"]
            """
        ).strip(),
        encoding="utf-8",
    )

    BatchArgs.override_configs({"skip_flag.yaml": True})
    job = BatchJob(BatchArgs())
    job.run_config_file("skip_flag.yaml")

    assert not job.failures
