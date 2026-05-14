"""Unit tests for ``NamedSubdirCollector``."""

import pytest

from refacdir.named_subdir_collector import NamedSubdirCollector


def test_collects_nested_files_resolves_clashes_clears_sources(tmp_path):
    root = tmp_path / "root"
    (root / "A").mkdir(parents=True)
    (root / "X" / "A").mkdir(parents=True)
    (root / "X" / "C").mkdir(parents=True)
    (root / "Y" / "B").mkdir(parents=True)
    (root / "Y" / "C").mkdir(parents=True)
    (root / "Z" / "A").mkdir(parents=True)
    (root / "Z" / "C").mkdir(parents=True)
    (root / "X" / "A" / "f1.txt").write_text("a", encoding="utf-8")
    (root / "Z" / "A" / "f2.txt").write_text("b", encoding="utf-8")
    (root / "Y" / "B" / "f3.txt").write_text("c", encoding="utf-8")
    (root / "X" / "C" / "f4.txt").write_text("d", encoding="utf-8")
    (root / "Y" / "C" / "dup.txt").write_text("e", encoding="utf-8")
    (root / "Z" / "C" / "dup.txt").write_text("f", encoding="utf-8")

    collector = NamedSubdirCollector(
        "unit",
        str(root),
        ["A", "B", "C"],
        test=False,
        skip_confirm=True,
        clear_sources=True,
    )
    collector.run()

    assert (root / "A" / "f1.txt").read_text(encoding="utf-8") == "a"
    assert (root / "A" / "f2.txt").read_text(encoding="utf-8") == "b"
    assert (root / "B" / "f3.txt").read_text(encoding="utf-8") == "c"
    assert (root / "C" / "f4.txt").read_text(encoding="utf-8") == "d"
    assert (root / "C" / "dup.txt").read_text(encoding="utf-8") == "e"
    assert (root / "C" / "dup_1.txt").read_text(encoding="utf-8") == "f"
    assert not (root / "X" / "A").exists()


def test_dry_run_does_not_move_files(tmp_path):
    root = tmp_path / "root"
    nested = root / "X" / "A"
    nested.mkdir(parents=True)
    f = nested / "keep.txt"
    f.write_text("data", encoding="utf-8")

    NamedSubdirCollector(
        "dry",
        str(root),
        ["A"],
        test=True,
        skip_confirm=True,
        clear_sources=True,
    ).run()

    assert f.exists()
    assert not (root / "A" / "keep.txt").exists()


def test_clear_sources_false_leaves_empty_nested_dirs(tmp_path):
    root = tmp_path / "root"
    (root / "sub" / "A").mkdir(parents=True)
    (root / "sub" / "A" / "only.txt").write_text("x", encoding="utf-8")

    NamedSubdirCollector(
        "no_clear",
        str(root),
        ["A"],
        test=False,
        skip_confirm=True,
        clear_sources=False,
    ).run()

    assert (root / "A" / "only.txt").read_text(encoding="utf-8") == "x"
    assert (root / "sub" / "A").is_dir()


def test_subdir_depth_default_skips_deeper_named_dir(tmp_path):
    root = tmp_path / "root"
    (root / "B" / "C").mkdir(parents=True)
    (root / "B" / "C" / "shallow.txt").write_text("s", encoding="utf-8")
    (root / "B" / "_" / "C").mkdir(parents=True)
    (root / "B" / "_" / "C" / "deep.txt").write_text("d", encoding="utf-8")

    NamedSubdirCollector(
        "unit",
        str(root),
        ["C"],
        test=False,
        skip_confirm=True,
        clear_sources=True,
    ).run()

    assert (root / "C" / "shallow.txt").read_text(encoding="utf-8") == "s"
    assert (root / "B" / "_" / "C" / "deep.txt").read_text(encoding="utf-8") == "d"


def test_subdir_depth_minus_one_collects_any_depth(tmp_path):
    root = tmp_path / "root"
    (root / "B" / "C").mkdir(parents=True)
    (root / "B" / "C" / "shallow.txt").write_text("s", encoding="utf-8")
    (root / "B" / "_" / "C").mkdir(parents=True)
    (root / "B" / "_" / "C" / "deep.txt").write_text("d", encoding="utf-8")

    NamedSubdirCollector(
        "unit",
        str(root),
        ["C"],
        test=False,
        skip_confirm=True,
        clear_sources=True,
        subdir_depth=-1,
    ).run()

    assert (root / "C" / "shallow.txt").read_text(encoding="utf-8") == "s"
    assert (root / "C" / "deep.txt").read_text(encoding="utf-8") == "d"


def test_subdir_depth_two_requires_three_relative_components(tmp_path):
    root = tmp_path / "root"
    (root / "B" / "C").mkdir(parents=True)
    (root / "B" / "C" / "two_parts.txt").write_text("no", encoding="utf-8")
    (root / "B" / "_" / "C").mkdir(parents=True)
    (root / "B" / "_" / "C" / "three_parts.txt").write_text("yes", encoding="utf-8")

    NamedSubdirCollector(
        "unit",
        str(root),
        ["C"],
        test=False,
        skip_confirm=True,
        clear_sources=True,
        subdir_depth=2,
    ).run()

    assert (root / "B" / "C" / "two_parts.txt").read_text(encoding="utf-8") == "no"
    assert (root / "C" / "three_parts.txt").read_text(encoding="utf-8") == "yes"


def test_invalid_subdir_depth_raises():
    with pytest.raises(Exception, match="subdir_depth"):
        NamedSubdirCollector(
            "bad",
            ".",
            ["A"],
            subdir_depth=-2,
        )


def test_construct_named_subdir_collector_from_batch_job(tmp_path):
    pytest.importorskip("keyring")
    from refacdir.batch import BatchArgs, BatchJob

    root = tmp_path / "r"
    root.mkdir()

    job = BatchJob(BatchArgs())
    collector = job.construct_named_subdir_collector(
        {
            "name": "via_batch",
            "root": {"root": str(root)},
            "subdir_names": ["X"],
            "test": True,
            "skip_confirm": True,
            "clear_sources": False,
        }
    )
    assert collector.name == "via_batch"
    assert collector.test is True
    assert collector.clear_sources is False
    assert collector.subdir_depth == 1
