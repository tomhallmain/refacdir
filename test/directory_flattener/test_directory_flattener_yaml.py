"""YAML + ``BatchJob`` for DIRECTORY_FLATTENER (isolated ``tmp_path``)."""
import textwrap

import pytest

from test.test_utils import patch_batch_job_base_dir, posix_path

from refacdir.batch import BatchArgs, BatchJob


@pytest.fixture
def restore_batch_configs():
    prev = dict(BatchArgs.configs)
    yield
    BatchArgs.configs = prev


def test_batch_yaml_directory_flattener_dry_run(
    tmp_path, monkeypatch, restore_batch_configs
):
    root = tmp_path / "flat_root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "x.txt").write_text("z", encoding="utf-8")

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    cfg = tmp_path / "flat_config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            will_run: true
            actions:
              - type: "DIRECTORY_FLATTENER"
                mappings:
                  - name: YAML flattener
                    test: true
                    skip_confirm: true
                    search_patterns: ["*"]
                    location:
                      root: "{posix_path(str(root))}"
            """
        ).strip(),
        encoding="utf-8",
    )

    BatchArgs.override_configs({"flat_config.yaml": True})
    job = BatchJob(BatchArgs())
    job.run_config_file("flat_config.yaml")

    assert not job.failures, job.failures
    assert (root / "sub" / "x.txt").exists()
