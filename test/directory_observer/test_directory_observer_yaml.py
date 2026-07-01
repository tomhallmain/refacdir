"""YAML + ``BatchJob`` for DIRECTORY_OBSERVER (isolated ``tmp_path``)."""
import textwrap

from test.test_utils import patch_batch_job_base_dir, posix_path

from refacdir.batch import BatchArgs, BatchJob


def test_batch_yaml_directory_observer_runs(tmp_path, monkeypatch, restore_batch_configs):
    ext = tmp_path / "obs_extra"
    ext.mkdir()
    (ext / "n.txt").write_text("ok", encoding="utf-8")

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    cfg = tmp_path / "obs_config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            will_run: true
            actions:
              - type: "DIRECTORY_OBSERVER"
                mappings:
                  - name: YAML observer
                    sortable_dirs: []
                    extra_dirs:
                      - "{posix_path(str(ext))}"
                    parent_dirs: []
                    exclude_dirs: []
                    file_types: [".txt"]
            """
        ).strip(),
        encoding="utf-8",
    )

    BatchArgs.override_configs({"obs_config.yaml": True})
    job = BatchJob(BatchArgs())
    job.run_config_file("obs_config.yaml")

    assert not job.failures, job.failures
