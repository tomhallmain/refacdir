"""Unit tests for ``DirectoryObserver`` / ``DirData``."""

from refacdir.directory_observer import DirData, DirectoryObserver


def test_dir_data_observe_counts_txt_files(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "one.txt").write_text("a", encoding="utf-8")
    (ext / "two.txt").write_text("b", encoding="utf-8")
    (ext / "skip.bin").write_bytes(b"\x00")

    DirData.set_file_types([".txt"])
    dd = DirData(str(ext))
    total, typed = dd.observe()
    assert total == 3
    assert typed == 2
    assert dd.dict[".txt"] == 2


def test_directory_observer_extra_dir_runs(tmp_path):
    """``extra_dirs`` (no ``_unsorted`` requirement)."""
    ext = tmp_path / "watch"
    ext.mkdir()
    (ext / "a.txt").write_text("x", encoding="utf-8")

    obs = DirectoryObserver(
        "unit",
        sortable_dirs=[],
        extra_dirs=[str(ext)],
        parent_dirs=[],
        exclude_dirs=[],
        file_types=[".txt"],
    )
    obs.run()
    assert obs.total_file_count >= 1


def test_construct_directory_observer_from_batch_job(tmp_path):
    from refacdir.batch import BatchJob, BatchArgs

    extra = tmp_path / "extra"
    extra.mkdir()

    job = BatchJob(BatchArgs())
    o = job.construct_directory_observer(
        {
            "name": "direct",
            "sortable_dirs": [],
            "extra_dirs": [str(extra)],
            "parent_dirs": [],
            "exclude_dirs": [],
            "file_types": [".txt"],
        }
    )
    assert o.name == "direct"
