"""YAML + ``BatchJob`` for NAMED_SUBDIR_COLLECTOR (isolated ``tmp_path``)."""

import textwrap

from test.test_utils import patch_batch_job_base_dir, posix_path


def test_batch_yaml_named_subdir_collector_dry_run(
    tmp_path, monkeypatch, restore_batch_configs
):
    from refacdir.batch import BatchArgs, BatchJob

    root = tmp_path / "collect_root"
    (root / "nested" / "A").mkdir(parents=True)
    (root / "nested" / "A" / "stay.txt").write_text("z", encoding="utf-8")

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)

    cfg = tmp_path / "named_subdir_config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            will_run: true
            actions:
              - type: "NAMED_SUBDIR_COLLECTOR"
                mappings:
                  - name: YAML collector
                    test: true
                    skip_confirm: true
                    clear_sources: true
                    subdir_names: ["A"]
                    root:
                      root: "{posix_path(str(root))}"
            """
        ).strip(),
        encoding="utf-8",
    )

    args = BatchArgs(configs={"named_subdir_config.yaml": True})
    job = BatchJob(args)
    job.run_config_file("named_subdir_config.yaml")

    assert not job.failures, job.failures
    assert (root / "nested" / "A" / "stay.txt").exists()
