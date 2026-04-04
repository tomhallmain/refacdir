"""
YAML + ``BatchJob`` for DUPLICATE_REMOVER (configs under ``tmp_path``, never ``configs/``).
"""
import textwrap

import pytest

from test.test_utils import patch_batch_job_base_dir, posix_path

from refacdir.batch import BatchArgs, BatchJob


@pytest.fixture
def restore_batch_configs():
    prev = dict(BatchArgs.configs)
    yield
    BatchArgs.configs = prev


def test_batch_yaml_duplicate_remover_runs(
    tmp_path, monkeypatch, restore_batch_configs
):
    d = tmp_path / "dups"
    d.mkdir()
    (d / "a.bin").write_bytes(b"x")
    (d / "b.bin").write_bytes(b"x")

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    cfg = tmp_path / "dup_config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            will_run: true
            actions:
              - type: "DUPLICATE_REMOVER"
                mappings:
                  - name: YAML duplicate remover
                    source_dirs:
                      - "{posix_path(str(d))}"
                    recursive: true
                    skip_confirm: true
                    use_hash_cache: false
                    exclude_dirs: []
                    preferred_delete_dirs: []
            """
        ).strip(),
        encoding="utf-8",
    )

    BatchArgs.override_configs({"dup_config.yaml": True})
    job = BatchJob(BatchArgs())
    job.run_config_file("dup_config.yaml")

    assert not job.failures, job.failures
    assert len(list(d.glob("*.bin"))) == 1
