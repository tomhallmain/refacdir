"""YAML + ``BatchJob`` for TRASH_REMOVER (isolated ``tmp_path``)."""

from test.test_utils import patch_batch_job_base_dir, posix_path


def write_config(tmp_path, directories, extra: dict = None):
    lines = [
        "will_run: true",
        "actions:",
        '  - type: "TRASH_REMOVER"',
        "    mappings:",
        "      - name: YAML trash",
        "        skip_confirm: true",
        "        directories:",
    ]
    lines += [f'          - "{posix_path(str(d))}"' for d in directories]
    for key, value in (extra or {}).items():
        lines.append(f"        {key}: {value}")
    cfg = tmp_path / "trash_remover_config.yaml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


def _run(tmp_path, monkeypatch, **batch_flags):
    from refacdir.batch import BatchArgs, BatchJob

    patch_batch_job_base_dir(monkeypatch, str(tmp_path), BatchJob)
    args = BatchArgs(configs={"trash_remover_config.yaml": True})
    for key, value in batch_flags.items():
        setattr(args, key, value)
    job = BatchJob(args)
    job.run_config_file("trash_remover_config.yaml")
    return job


def test_batch_yaml_trash_remover_dry_run(tmp_path, monkeypatch, restore_batch_configs):
    trash = tmp_path / "trash"
    trash.mkdir()
    (trash / "a.txt").write_text("a", encoding="utf-8")
    write_config(tmp_path, [trash], extra={"test": "true"})
    job = _run(tmp_path, monkeypatch)
    assert not job.failures, job.failures
    assert (trash / "a.txt").exists()


def test_batch_yaml_trash_remover_empties(tmp_path, monkeypatch, restore_batch_configs):
    one, two = tmp_path / "one", tmp_path / "two"
    for d in (one, two):
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "x.txt").write_text("x", encoding="utf-8")
    write_config(tmp_path, [one, two])
    job = _run(tmp_path, monkeypatch)
    assert not job.failures, job.failures
    assert one.is_dir() and list(one.iterdir()) == []
    assert two.is_dir() and list(two.iterdir()) == []


def test_batch_yaml_missing_directory_follows_the_batch_option(tmp_path, monkeypatch, restore_batch_configs):
    present = tmp_path / "present"
    present.mkdir()
    (present / "a.txt").write_text("a", encoding="utf-8")
    write_config(tmp_path, [tmp_path / "missing", present])

    job = _run(tmp_path, monkeypatch)
    assert job.failures
    assert (present / "a.txt").exists()

    job = _run(tmp_path, monkeypatch, skip_missing_locations=True)
    assert not job.failures, job.failures
    assert not (present / "a.txt").exists()


def test_batch_yaml_protected_directory_fails(tmp_path, monkeypatch, restore_batch_configs):
    import os

    write_config(tmp_path, [os.path.expanduser("~")])
    job = _run(tmp_path, monkeypatch)
    assert job.failures


def test_batch_yaml_removals_are_recorded_with_config_and_mapping(tmp_path, monkeypatch, restore_batch_configs):
    import refacdir.batch_job_history as history

    trash = tmp_path / "trash"
    trash.mkdir()
    (trash / "a.txt").write_text("a", encoding="utf-8")
    write_config(tmp_path, [trash])
    history.begin_batch_job(["trash_remover_config.yaml"])
    job = _run(tmp_path, monkeypatch)
    assert not job.failures, job.failures
    (op,) = history._active_session.operations
    assert op["reversible"] is False
    assert op["meta"]["mapping_name"] == "YAML trash"
    assert op["meta"]["action_type"] == "trash_remover"
