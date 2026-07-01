"""Tests for batch job history recording and reversal."""

import os

import pytest

from refacdir.batch_job_history import (
    MAX_BATCH_JOB_HISTORY,
    begin_batch_job,
    find_batch_job,
    finish_batch_job,
    get_batch_job_history,
    job_mapping_groups,
    record_file_operation,
    recording_context,
    reverse_job,
)


def _record_rename(src, dest, **context):
    with recording_context(**context):
        record_file_operation("rename", str(src), str(dest))


# --- Recording and persistence ---


def test_test_mode_batch_does_not_record():
    begin_batch_job(["foo.yaml"], test=True)
    record_file_operation("rename", "/a/old.txt", "/a/new.txt")
    assert finish_batch_job({}, [], False) is None
    assert get_batch_job_history() == []


def test_record_without_active_session_is_no_op():
    record_file_operation("rename", "/a/old.txt", "/a/new.txt")
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


def test_paths_are_normalized_on_record(tmp_path):
    src = tmp_path / "sub" / "old.txt"
    dest = tmp_path / "new.txt"
    src.parent.mkdir()
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src).replace("\\", "/"), str(dest).replace("\\", "/"))
    finish_batch_job({}, [], False)

    op = get_batch_job_history()[0]["operations"][0]
    assert op["source"] == os.path.normpath(str(src))
    assert op["dest"] == os.path.normpath(str(dest))


def test_history_capped_at_max():
    for i in range(MAX_BATCH_JOB_HISTORY + 5):
        begin_batch_job([f"cfg_{i}.yaml"], test=False)
        job_id = finish_batch_job({}, [], False)
        assert job_id is not None

    history = get_batch_job_history()
    assert len(history) == MAX_BATCH_JOB_HISTORY
    assert history[0]["configs"] == [f"cfg_{MAX_BATCH_JOB_HISTORY + 4}.yaml"]


def test_finish_persists_cancelled_and_config_list():
    begin_batch_job(["a.yaml", "b.yaml"], test=False)
    job_id = finish_batch_job({}, ["something failed"], cancelled=True)
    job = find_batch_job(job_id)
    assert job["cancelled"] is True
    assert job["failures"] == ["something failed"]
    assert job["configs"] == ["a.yaml", "b.yaml"]


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


def test_nested_recording_context_replaces_not_merges(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    with recording_context(config="outer.yaml"):
        with recording_context(mapping_name="inner_only"):
            record_file_operation("rename", str(src), str(dest))
    finish_batch_job({}, [], False)

    meta = get_batch_job_history()[0]["operations"][0]["meta"]
    assert meta.get("config") is None
    assert meta["mapping_name"] == "inner_only"


def test_recording_context_restored_after_exception():
    begin_batch_job(["cfg.yaml"], test=False)
    with recording_context(config="cfg.yaml", mapping_name="before"):
        with pytest.raises(RuntimeError):
            with recording_context(mapping_name="during"):
                raise RuntimeError("boom")
        record_file_operation("rename", "/x/a.txt", "/x/b.txt")
    finish_batch_job({}, [], False)

    meta = get_batch_job_history()[0]["operations"][0]["meta"]
    assert meta["config"] == "cfg.yaml"
    assert meta["mapping_name"] == "before"


def test_explicit_meta_overrides_recording_context(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    with recording_context(config="cfg.yaml", mapping_name="from_context"):
        record_file_operation(
            "rename",
            str(src),
            str(dest),
            meta={"mapping_name": "from_call", "extra": 1},
        )
    finish_batch_job({}, [], False)

    meta = get_batch_job_history()[0]["operations"][0]["meta"]
    assert meta["config"] == "cfg.yaml"
    assert meta["mapping_name"] == "from_call"
    assert meta["extra"] == 1


# --- Whole-job reversal ---


def test_full_job_reverse_applies_lifo_for_rename_chain(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    a.write_text("chain")
    os.rename(a, b)
    os.rename(b, c)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(a), str(b))
    record_file_operation("rename", str(b), str(c))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id)
    assert result.succeeded == 2
    assert a.is_file()
    assert a.read_text() == "chain"
    assert not b.exists()
    assert not c.exists()


def test_move_operations_are_reversible(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "moved.txt"
    src.write_text("move me")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("move", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id)
    assert result.succeeded == 1
    assert src.is_file()


def test_non_reversible_operation_types_are_skipped(tmp_path):
    dest = tmp_path / "still_here.txt"
    dest.write_text("x")

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("delete", str(tmp_path / "gone.txt"), str(dest))
    job_id = finish_batch_job({}, [], False)

    op = get_batch_job_history()[0]["operations"][0]
    assert op["reversible"] is False

    result = reverse_job(job_id)
    assert result.attempted == 0
    assert result.skipped == 0
    assert dest.is_file()


def test_reverse_skips_missing_dest(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    begin_batch_job(["renamer.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id)
    assert result.attempted == 0
    assert result.skipped == 1


def test_reverse_fails_when_source_path_already_exists(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    src.write_text("original")
    dest.write_text("renamed")
    # Record as if rename happened, but both paths exist (user recreated src manually).

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id)
    assert result.attempted == 1
    assert result.failed == 1
    assert result.succeeded == 0
    assert "already exists" in result.errors[0]
    assert dest.is_file()
    assert src.is_file()


def test_reverse_recreates_missing_source_parent_directory(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    src = sub / "old.txt"
    dest = tmp_path / "new.txt"
    src.write_text("nested")
    os.rename(src, dest)
    sub.rmdir()

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    reverse_job(job_id)
    assert src.is_file()
    assert sub.is_dir()


def test_dry_run_reverse_does_not_move_files_or_persist_flags(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, dry_run=True)
    assert result.succeeded == 1
    assert result.dry_run is True
    assert dest.is_file()
    assert not src.exists()
    assert get_batch_job_history()[0]["operations"][0]["reversed"] is False


def test_second_reverse_skips_already_reversed_operations(tmp_path):
    src = tmp_path / "old.txt"
    dest = tmp_path / "new.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    job_id = finish_batch_job({}, [], False)

    first = reverse_job(job_id)
    assert first.succeeded == 1

    second = reverse_job(job_id)
    assert second.attempted == 0
    assert second.skipped == 0
    assert second.succeeded == 0


def test_reverse_unknown_job_raises():
    with pytest.raises(ValueError, match="Batch job not found"):
        reverse_job("missing-job-id")


def test_reversing_one_job_does_not_affect_another(tmp_path):
    src1 = tmp_path / "one.txt"
    dest1 = tmp_path / "one_new.txt"
    src2 = tmp_path / "two.txt"
    dest2 = tmp_path / "two_new.txt"
    src1.write_text("1")
    src2.write_text("2")
    os.rename(src1, dest1)
    os.rename(src2, dest2)

    begin_batch_job(["first.yaml"], test=False)
    record_file_operation("rename", str(src1), str(dest1))
    job_one = finish_batch_job({}, [], False)

    begin_batch_job(["second.yaml"], test=False)
    record_file_operation("rename", str(src2), str(dest2))
    job_two = finish_batch_job({}, [], False)

    reverse_job(job_one)
    assert src1.is_file()
    assert dest2.is_file()
    assert get_batch_job_history()[0]["operations"][0]["reversed"] is False
    assert get_batch_job_history()[1]["operations"][0]["reversed"] is True


# --- Mapping-scoped reversal ---


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
    _record_rename(file_a, mapped_a, config="cfg.yaml", mapping_name="mapping_one")
    _record_rename(file_b, mapped_b, config="cfg.yaml", mapping_name="mapping_two")
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, config="cfg.yaml", mapping_name="mapping_one")
    assert result.succeeded == 1
    assert file_a.is_file()
    assert mapped_b.is_file()
    assert not mapped_a.exists()

    history = get_batch_job_history()[0]["operations"]
    assert history[0]["reversed"] is True
    assert history[1]["reversed"] is False


def test_same_mapping_name_in_different_configs_are_independent(tmp_path):
    src1 = tmp_path / "cfg1.txt"
    dest1 = tmp_path / "cfg1_new.txt"
    src2 = tmp_path / "cfg2.txt"
    dest2 = tmp_path / "cfg2_new.txt"
    src1.write_text("1")
    src2.write_text("2")
    os.rename(src1, dest1)
    os.rename(src2, dest2)

    begin_batch_job(["cfg1.yaml", "cfg2.yaml"], test=False)
    _record_rename(src1, dest1, config="cfg1.yaml", mapping_name="shared_name")
    _record_rename(src2, dest2, config="cfg2.yaml", mapping_name="shared_name")
    job_id = finish_batch_job({}, [], False)

    groups = job_mapping_groups(get_batch_job_history()[0])
    assert len(groups) == 2

    result = reverse_job(job_id, config="cfg1.yaml", mapping_name="shared_name")
    assert result.succeeded == 1
    assert src1.is_file()
    assert dest2.is_file()


def test_reverse_earlier_mapping_fails_until_later_mapping_is_reversed(tmp_path):
    """When mapping two renamed the file after mapping one, undo mapping one first."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    a.write_text("chain")
    os.rename(a, b)
    os.rename(b, c)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(a, b, config="cfg.yaml", mapping_name="first")
    _record_rename(b, c, config="cfg.yaml", mapping_name="second")
    job_id = finish_batch_job({}, [], False)

    blocked = reverse_job(job_id, config="cfg.yaml", mapping_name="first")
    assert blocked.attempted == 0
    assert blocked.skipped == 1
    assert c.is_file()

    undo_second = reverse_job(job_id, config="cfg.yaml", mapping_name="second")
    assert undo_second.succeeded == 1
    assert b.is_file()
    assert not c.exists()

    undo_first = reverse_job(job_id, config="cfg.yaml", mapping_name="first")
    assert undo_first.succeeded == 1
    assert a.is_file()
    assert not b.exists()


def test_mapping_reverse_uses_lifo_within_mapping_only(tmp_path):
    """Two renames in one mapping should reverse newest-first even if another mapping ran between them."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    other = tmp_path / "other.txt"
    other_dest = tmp_path / "other_new.txt"
    a.write_text("a")
    other.write_text("o")
    os.rename(a, b)
    os.rename(other, other_dest)
    os.rename(b, c)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(a, b, config="cfg.yaml", mapping_name="chain")
    _record_rename(other, other_dest, config="cfg.yaml", mapping_name="other")
    _record_rename(b, c, config="cfg.yaml", mapping_name="chain")
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, config="cfg.yaml", mapping_name="chain")
    assert result.succeeded == 2
    assert a.is_file()
    assert not b.exists()
    assert not c.exists()
    assert other_dest.is_file()


def test_filter_by_config_only_reverses_matching_operations(tmp_path):
    src_a = tmp_path / "a.txt"
    dest_a = tmp_path / "a_new.txt"
    src_b = tmp_path / "b.txt"
    dest_b = tmp_path / "b_new.txt"
    src_a.write_text("a")
    src_b.write_text("b")
    os.rename(src_a, dest_a)
    os.rename(src_b, dest_b)

    begin_batch_job(["one.yaml", "two.yaml"], test=False)
    _record_rename(src_a, dest_a, config="one.yaml", mapping_name="pattern")
    _record_rename(src_b, dest_b, config="two.yaml", mapping_name="pattern")
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, config="one.yaml")
    assert result.succeeded == 1
    assert src_a.is_file()
    assert dest_b.is_file()


def test_filter_by_mapping_name_only(tmp_path):
    src_a = tmp_path / "a.txt"
    dest_a = tmp_path / "a_new.txt"
    src_b = tmp_path / "b.txt"
    dest_b = tmp_path / "b_new.txt"
    src_a.write_text("a")
    src_b.write_text("b")
    os.rename(src_a, dest_a)
    os.rename(src_b, dest_b)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(src_a, dest_a, config="cfg.yaml", mapping_name="target")
    _record_rename(src_b, dest_b, config="cfg.yaml", mapping_name="other")
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, mapping_name="target")
    assert result.succeeded == 1
    assert src_a.is_file()
    assert dest_b.is_file()


def test_wrong_mapping_filter_matches_nothing(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(src, dest, config="cfg.yaml", mapping_name="real")
    job_id = finish_batch_job({}, [], False)

    result = reverse_job(job_id, config="cfg.yaml", mapping_name="nonexistent")
    assert result.attempted == 0
    assert result.skipped == 0
    assert dest.is_file()


def test_untagged_operations_grouped_separately(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    record_file_operation("rename", str(src), str(dest))
    finish_batch_job({}, [], False)

    groups = job_mapping_groups(get_batch_job_history()[0])
    assert len(groups) == 1
    assert groups[0]["config"] == ""
    assert groups[0]["mapping_name"] == ""
    assert groups[0]["operation_count"] == 1


def test_job_mapping_groups_reversible_count_after_partial_reverse(tmp_path):
    src = tmp_path / "a.txt"
    dest = tmp_path / "b.txt"
    src.write_text("x")
    os.rename(src, dest)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(src, dest, config="cfg.yaml", mapping_name="pattern")
    job_id = finish_batch_job({}, [], False)

    assert job_mapping_groups(get_batch_job_history()[0])[0]["reversible_count"] == 1
    reverse_job(job_id, config="cfg.yaml", mapping_name="pattern")
    assert job_mapping_groups(get_batch_job_history()[0])[0]["reversible_count"] == 0


def test_mapping_filter_skips_only_within_filtered_mapping(tmp_path):
    """Reversing one mapping must not count missing-dest skips from another mapping."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    ghost_src = tmp_path / "ghost.txt"
    ghost_dest = tmp_path / "ghost_new.txt"
    a.write_text("a")
    os.rename(a, b)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(a, b, config="cfg.yaml", mapping_name="good")
    with recording_context(config="cfg.yaml", mapping_name="missing"):
        record_file_operation("rename", str(ghost_src), str(ghost_dest))
    job_id = finish_batch_job({}, [], False)

    missing_result = reverse_job(job_id, config="cfg.yaml", mapping_name="missing")
    assert missing_result.attempted == 0
    assert missing_result.skipped == 1

    good_result = reverse_job(job_id, config="cfg.yaml", mapping_name="good")
    assert good_result.succeeded == 1
    assert good_result.skipped == 0
    assert a.is_file()


def test_partial_mapping_reverse_then_whole_job_reverse_completes_remainder(tmp_path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    mapped_a = tmp_path / "a_new.txt"
    mapped_b = tmp_path / "b_new.txt"
    file_a.write_text("a")
    file_b.write_text("b")
    os.rename(file_a, mapped_a)
    os.rename(file_b, mapped_b)

    begin_batch_job(["cfg.yaml"], test=False)
    _record_rename(file_a, mapped_a, config="cfg.yaml", mapping_name="one")
    _record_rename(file_b, mapped_b, config="cfg.yaml", mapping_name="two")
    job_id = finish_batch_job({}, [], False)

    reverse_job(job_id, config="cfg.yaml", mapping_name="one")
    assert file_a.is_file()
    assert mapped_b.is_file()

    remainder = reverse_job(job_id)
    assert remainder.succeeded == 1
    assert file_b.is_file()
    assert not mapped_b.exists()
