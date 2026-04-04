"""
Batch + YAML integration for RENAMER actions.

Configs live under pytest ``tmp_path`` with ``BatchJob.BASE_DIR`` patched so tests
never read or write the repo ``configs/`` directory.
"""
import textwrap

import pytest

from refacdir.batch import BatchArgs, BatchJob
from refacdir.filename_ops import FilenameMappingDefinition


@pytest.fixture
def restore_batch_configs():
    prev = dict(BatchArgs.configs)
    yield
    BatchArgs.configs = prev


def _posix_path(p: str) -> str:
    return p.replace("\\", "/")


def test_batch_yaml_renamer_runs_rename_by_mtime_dry_run(
    tmp_path, monkeypatch, restore_batch_configs, restore_filename_mapping_registry
):
    """
    Load YAML from an isolated dir (not ``configs/``) and run RENAMER via ``BatchJob``.
    ``test: true`` in YAML is the user dry-run flag, not pytest.
    """
    monkeypatch.setattr(BatchJob, "BASE_DIR", str(tmp_path))

    loc = tmp_path / "rename_root"
    loc.mkdir()
    (loc / "sample.txt").write_text("hello", encoding="utf-8")

    cfg_path = tmp_path / "unit_renamer_config.yaml"
    yaml_body = f"""
will_run: true
actions:
  - type: RENAMER
    mappings:
      - name: YAML renamer group
        function: rename_by_mtime
        test: true
        skip_confirm: true
        recursive: false
        mappings:
          - search_patterns: "*.txt"
            rename_tag: "yaml_"
        locations:
          - root: "{_posix_path(str(loc))}"
"""
    cfg_path.write_text(textwrap.dedent(yaml_body).strip(), encoding="utf-8")

    BatchArgs.override_configs({"unit_renamer_config.yaml": True})
    args = BatchArgs()
    args.skip_confirm = True
    job = BatchJob(args)

    job.run_config_file("unit_renamer_config.yaml")

    assert not job.failures, f"Batch reported failures: {job.failures}"
    # User dry-run: original file still present
    assert (loc / "sample.txt").exists()
    assert not any(p.name.startswith("yaml_") for p in loc.iterdir())


def test_construct_batch_renamer_from_dict_matches_programmatic_mappings():
    """``BatchJob.construct_batch_renamer`` builds the same mapping keys as ``construct_mappings``."""
    job = BatchJob(BatchArgs())
    yaml_dict = {
        "name": "direct",
        "function": "rename_by_mtime",
        "test": True,
        "skip_confirm": True,
        "recursive": False,
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "t_"}],
        "locations": [{"root": "C:/tmp/renamer_root"}],
    }
    br, func = job.construct_batch_renamer(yaml_dict)
    assert func == "rename_by_mtime"
    expected = FilenameMappingDefinition.construct_mappings(yaml_dict["mappings"])
    assert br.mappings == expected
