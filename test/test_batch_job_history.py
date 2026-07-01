"""Tests for batch job history recording and reversal."""

import os

from refacdir.batch_job_history import (
    MAX_BATCH_JOB_HISTORY,
    begin_batch_job,
    finish_batch_job,
    get_batch_job_history,
    job_mapping_groups,
    record_file_operation,
    recording_context,
    reverse_job,
)


def test_test_mode_batch_does_not_record():
    begin_batch_job(["foo.yaml"], test=True)
    record_file_operation("rename", "/a/old.txt", "/a/new.txt")
    assert finish_batch_job({}, [], False) is None
    assert get_batch_job_history() == []


def test_records_rename_and_prepends(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["renamer.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)
    assert job_id is not None

    history = get_batch_job_history()
    assert len(history) == 1
    assert history[0]["job_id"] == job_id
    assert history[0]["operations"][0]["source"] == os.path.normpath(str(src))
    assert history[0]["operations"][0]["dest"] == os.path.normpath(str(dest))

    result = reverse_job(job_id)
    assert result.succeeded == 1
    assert src.is_file()
    assert not dest.exists()
    assert get_batch_job_history()[0]["operations"][0]["reversed"]


def test_recording_context_tags_operations(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    with recording_context(config="cfg.yaml", mapping_name="pattern_a", action_type="renamer"):
        record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    op = get_batch_job_history()[0]["operations"][0]
    assert op["meta"]["config"] == "cfg.yaml"
    assert op["meta"]["mapping_name"] == "pattern_a"
    assert op["meta"]["action_type"] == "renamer"

    groups = job_mapping_groups(get_batch_job_history()[0])
    assert len(groups) == 1
    assert groups[0]["mapping_name"] == "pattern_a"
    assert groups[0]["operation_count"] == 1

    result = reverse_job(job_id, config="cfg.yaml", mapping_name="pattern_a")
    assert result.succeeded == 1
    assert src.is_file()


def test_reverse_mapping_only_leaves_other_mapping_intact(tmp_path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("a")
    file_b.write_text("b")
    mapped_a = tmp_path / "mapped_a.txt"
    mapped_b = tmp_path / "mapped_b.txt"
    os.rename(file_a, mapped_a)
    os.rename(file_b, mapped_b)

    begin_batch_job(["cfg.yaml"], test=False)
    with recording_context(config="cfg.yaml", mapping_name="mapping_one"):
        record_file_operation("rename", str(file_a), str(mapped_a))
    with recording_context(config="cfg.yaml", mapping_name="mapping_two"):
        record_file_operation("rename", str(file_b), str(mapped_b))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, config="cfg.yaml", mapping_name="mapping_one")
    assert result.succeeded == 1
    assert file_a.is_file()
    assert mapped_b.is_file()
    assert not mapped_a.exists()

    history = get_batch_job_history()[0]["operations"]
    assert history[0]["reversed"] is True
    assert history[1]["reversed"] is False


def test_history_capped_at_max():
    for i in range(MAX_BATCH_JOB_HISTORY + 5):
        begin_batch_job([f"cfg_{i}.yaml"], test=False)
        job_id = finish_batch_job({}, [], False)
        assert job_id is not None

    history = get_batch_job_history()
    assert len(history) == MAX_BATCH_JOB_HISTORY
    assert history[0]["configs"] == [f"cfg_{MAX_BATCH_JOB_HISTORY + 4}.yaml"]


def test_reverse_skips_missing_dest(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    begin_batch_job(["renamer.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id)
    assert result.attempted == 0
    assert result.skipped == 1
