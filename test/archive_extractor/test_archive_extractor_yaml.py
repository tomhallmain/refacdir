"""YAML + ``BatchJob`` for ARCHIVE_EXTRACTOR (isolated ``tmp_path``)."""

import textwrap
import zipfile

from test.test_utils import patch_batch_job_base_dir, posix_path


def make_zip(path, members: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def write_config(tmp_path, search, target, extra: dict = None):
    """Build the config line by line; the mapping keys all sit at one indent level."""
    lines = [
        "will_run: true",
        "actions:",
        '  - type: "ARCHIVE_EXTRACTOR"',
        "    mappings:",
        "      - name: YAML extractor",
        "        skip_confirm: true",
        "        search_dir:",
        f'          root: "{posix_path(str(search))}"',
        f'        target_dir: "{posix_path(str(target))}"',
    ]
    for key, value in (extra or {}).items():
        lines.append(f"        {key}: {value}")
    cfg = tmp_path / "archive_extractor_config.yaml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


def test_batch_yaml_archive_extractor_dry_run(tmp_path, monkeypatch, restore_batch_configs):
    from refacdir.batch import BatchArgs, BatchJob

    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "reports.zip", {"q1.pdf": "a"})

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)
    write_config(tmp_path, search, target, extra={"test": "true"})

    args = BatchArgs(configs={"archive_extractor_config.yaml": True})
    job = BatchJob(args)
    job.run_config_file("archive_extractor_config.yaml")

    assert not job.failures, job.failures
    assert not target.exists()
    assert (search / "reports.zip").exists()


def test_batch_yaml_archive_extractor_extracts(tmp_path, monkeypatch, restore_batch_configs):
    from refacdir.batch import BatchArgs, BatchJob

    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "reports.zip", {"2024/q1.pdf": "a", "q2.pdf": "b"})

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)
    write_config(tmp_path, search, target)

    args = BatchArgs(configs={"archive_extractor_config.yaml": True})
    job = BatchJob(args)
    job.run_config_file("archive_extractor_config.yaml")

    assert not job.failures, job.failures
    assert (target / "q1.pdf").read_text(encoding="utf-8") == "a"
    assert (target / "q2.pdf").read_text(encoding="utf-8") == "b"


def test_batch_yaml_archive_extractor_preserve_structure(
    tmp_path, monkeypatch, restore_batch_configs
):
    from refacdir.batch import BatchArgs, BatchJob

    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "reports.zip", {"2024/q1.pdf": "a"})

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)
    write_config(tmp_path, search, target, extra={"preserve_structure": "true"})

    args = BatchArgs(configs={"archive_extractor_config.yaml": True})
    job = BatchJob(args)
    job.run_config_file("archive_extractor_config.yaml")

    assert not job.failures, job.failures
    assert (target / "reports" / "2024" / "q1.pdf").read_text(encoding="utf-8") == "a"


def test_batch_yaml_archive_extractor_missing_required_key_fails(
    tmp_path, monkeypatch, restore_batch_configs
):
    from refacdir.batch import BatchArgs, BatchJob

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)
    cfg = tmp_path / "archive_extractor_config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            will_run: true
            actions:
              - type: "ARCHIVE_EXTRACTOR"
                mappings:
                  - name: no target
                    search_dir: "."
            """
        ).strip(),
        encoding="utf-8",
    )

    args = BatchArgs(configs={"archive_extractor_config.yaml": True})
    job = BatchJob(args)
    job.run_config_file("archive_extractor_config.yaml")

    assert job.failures
