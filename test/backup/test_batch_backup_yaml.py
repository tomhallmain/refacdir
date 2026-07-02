"""
Batch + YAML integration for BACKUP actions.

Configs are written under pytest's tmp_path and BatchJob.BASE_DIR is patched to that path
so tests never read from the repo `configs/` tree or the user's live config set.
See :mod:`test.test_utils` for shared isolation helpers.
"""
import os
import textwrap

from test.test_utils import patch_batch_job_base_dir, posix_path

from refacdir.batch import BatchArgs, BatchJob
from refacdir.filename_ops import FiletypesDefinition, FilenameMappingDefinition


def test_batch_yaml_backup_resolves_named_filetypes_and_runs(
    tmp_path, monkeypatch, restore_batch_registries, restore_batch_configs
):
    """
    Load a YAML file from an isolated directory (not configs/), register filetype_definitions,
    resolve '{{yaml_test_types}}' via FiletypesDefinition, and run BACKUP through BatchJob.
    """
    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir()
    tgt.mkdir()
    (src / "sample.txt").write_text("hello", encoding="utf-8")

    cfg_path = tmp_path / "unit_backup_config.yaml"
    yaml_body = f"""
will_run: true
filetype_definitions:
  - name: yaml_test_types
    extensions:
      - .txt
actions:
  - type: BACKUP
    mappings:
      - name: YAML backup group
        test: true
        skip_confirm: true
        backup_mappings:
          - name: mapping_one
            source_dir: "{posix_path(str(src))}"
            target_dir: "{posix_path(str(tgt))}"
            mode: PUSH
            file_types: "{{{{yaml_test_types}}}}"
"""
    cfg_path.write_text(textwrap.dedent(yaml_body).strip(), encoding="utf-8")

    args = BatchArgs(configs={"unit_backup_config.yaml": True})
    args.skip_confirm = True
    job = BatchJob(args)

    job.run_config_file("unit_backup_config.yaml")

    assert not job.failures, f"Batch reported failures: {job.failures}"
    assert "yaml_test_types" in FiletypesDefinition.NAMED_DEFINITIONS
    # Dry-run: nothing copied to target
    assert not (tgt / "sample.txt").exists()


def test_batch_construct_backup_matches_yaml_named_types(
    restore_batch_registries,
):
    """construct_backup alone resolves {{name}} the same way as a loaded config."""
    FiletypesDefinition.add_named_definitions(
        [
            {
                "name": "construct_test_types",
                "extensions": [".md"],
            }
        ]
    )
    job = BatchJob(BatchArgs(configs={}))
    mgr = job.construct_backup(
        {
            "name": "direct",
            "test": True,
            "skip_confirm": True,
            "backup_mappings": [
                {
                    "name": "m",
                    "source_dir": "C:/tmp/src",
                    "target_dir": "C:/tmp/tgt",
                    "file_types": "{{construct_test_types}}",
                }
            ],
        }
    )
    assert mgr.backup_mappings[0].file_types == [".md"]
