"""Unit tests for ``DuplicateRemover`` on isolated temp trees."""

from refacdir.duplicate_remover import DuplicateRemover


def test_duplicate_remover_removes_identical_file_when_skip_confirm(tmp_path):
    """Two equal files → one duplicate removed when ``skip_confirm=True``."""
    (tmp_path / "keep.txt").write_bytes(b"same-bytes")
    (tmp_path / "dup.txt").write_bytes(b"same-bytes")
    dr = DuplicateRemover(
        "unit",
        [str(tmp_path)],
        skip_confirm=True,
        use_hash_cache=False,
    )
    dr.run()
    txts = list(tmp_path.glob("*.txt"))
    assert len(txts) == 1


def test_construct_duplicate_remover_from_batch_job():
    """``BatchJob.construct_duplicate_remover`` builds a remover with expected sources."""
    from refacdir.batch import BatchJob, BatchArgs

    job = BatchJob(BatchArgs())
    dr = job.construct_duplicate_remover(
        {
            "name": "direct",
            "source_dirs": ["C:/tmp/a", "C:/tmp/b"],
            "recursive": False,
            "skip_confirm": True,
            "use_hash_cache": False,
        }
    )
    assert dr.name == "direct"
    assert dr.recursive is False
    assert dr.skip_confirm is True
    assert dr.use_hash_cache is False
