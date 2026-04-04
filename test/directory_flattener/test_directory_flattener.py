"""Unit tests for ``DirectoryFlattener`` (user dry-run via ``test=True``)."""

from refacdir.batch_renamer import DirectoryFlattener


def test_directory_flattener_dry_run_does_not_move_files(tmp_path):
    """``test=True`` is user dry-run: nested files stay in place."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    f = nested / "keep.txt"
    f.write_text("data", encoding="utf-8")

    fl = DirectoryFlattener(
        "unit",
        {"root": str(root)},
        search_patterns=["*"],
        test=True,
        skip_confirm=True,
    )
    fl.run()
    assert f.exists()
    assert not (root / "keep.txt").exists()


def test_construct_directory_flattener_from_batch_job(tmp_path):
    from refacdir.batch import BatchJob, BatchArgs

    root = tmp_path / "r"
    root.mkdir()

    job = BatchJob(BatchArgs())
    fl = job.construct_directory_flattener(
        {
            "name": "direct",
            "location": {"root": str(root)},
            "search_patterns": ["*"],
            "test": True,
            "skip_confirm": True,
        }
    )
    assert fl.name == "direct"
    assert fl.batch_renamer.test is True
