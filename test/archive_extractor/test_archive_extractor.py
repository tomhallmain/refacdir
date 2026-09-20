"""Unit tests for ``ArchiveExtractor``."""

import zipfile

import pytest

from refacdir.archive_extractor import ArchiveExtractor


def make_zip(path, members: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def extractor(search_dir, target_dir, **kwargs):
    kwargs.setdefault("skip_confirm", True)
    kwargs.setdefault("test", False)
    return ArchiveExtractor("unit", str(search_dir), str(target_dir), **kwargs)


def test_flat_merge_tags_collisions_with_source_archive(tmp_path):
    # Archives are processed in sorted path order, so the a_/b_ prefixes fix
    # which one wins the un-suffixed name.
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "a_reports.zip", {"2024/q1.pdf": "a", "q2.pdf": "b"})
    make_zip(search / "b_archive.zip", {"q1.pdf": "c"})

    extractor(search, target).run()

    assert (target / "q1.pdf").read_text(encoding="utf-8") == "a"
    assert (target / "q2.pdf").read_text(encoding="utf-8") == "b"
    assert (target / "q1__b_archive.pdf").read_text(encoding="utf-8") == "c"


def test_flat_merge_tags_with_internal_directory(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "data.zip", {"one/rep.txt": "x", "two/rep.txt": "y"})

    extractor(search, target).run()

    assert (target / "rep.txt").read_text(encoding="utf-8") == "x"
    assert (target / "rep__data__two.txt").read_text(encoding="utf-8") == "y"


def test_flat_merge_falls_back_to_counter_when_tag_is_taken(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "a" / "reports.zip", {"data.txt": "1"})
    make_zip(search / "b" / "reports.zip", {"data.txt": "2"})
    make_zip(search / "c" / "reports.zip", {"data.txt": "3"})

    extractor(search, target).run()

    assert (target / "data.txt").read_text(encoding="utf-8") == "1"
    assert (target / "data__reports.txt").read_text(encoding="utf-8") == "2"
    assert (target / "data__reports_1.txt").read_text(encoding="utf-8") == "3"


def test_existing_target_file_is_never_overwritten(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    target.mkdir(parents=True)
    (target / "q1.pdf").write_text("original", encoding="utf-8")
    make_zip(search / "reports.zip", {"q1.pdf": "new"})

    extractor(search, target).run()

    assert (target / "q1.pdf").read_text(encoding="utf-8") == "original"
    assert (target / "q1__reports.pdf").read_text(encoding="utf-8") == "new"


def test_preserve_structure_keeps_internal_folders(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "reports.zip", {"2024/q1.pdf": "a", "q2.pdf": "b"})

    extractor(search, target, preserve_structure=True).run()

    assert (target / "reports" / "2024" / "q1.pdf").read_text(encoding="utf-8") == "a"
    assert (target / "reports" / "q2.pdf").read_text(encoding="utf-8") == "b"


def test_preserve_structure_merges_same_stem_and_counters_collisions(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "a" / "reports.zip", {"q1.pdf": "first"})
    make_zip(search / "b" / "reports.zip", {"q1.pdf": "second"})

    extractor(search, target, preserve_structure=True).run()

    assert (target / "reports" / "q1.pdf").read_text(encoding="utf-8") == "first"
    assert (target / "reports" / "q1_1.pdf").read_text(encoding="utf-8") == "second"


def test_dry_run_writes_nothing_but_plans_unique_destinations(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "a.zip", {"same.txt": "1"})
    make_zip(search / "b.zip", {"same.txt": "2"})

    runner = extractor(search, target, test=True)
    plan = runner.preview()
    runner.run()

    assert not target.exists()
    destinations = [entry["destination"] for entry in plan["planned"]]
    assert len(destinations) == len(set(destinations)), destinations
    assert str(target / "same.txt") in destinations
    assert str(target / "same__b.txt") in destinations


def test_members_escaping_the_target_are_skipped(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(
        search / "evil.zip",
        {"../escape.txt": "no", "/absolute.txt": "no", "safe.txt": "yes"},
    )

    extractor(search, target, preserve_structure=True).run()

    assert (target / "evil" / "safe.txt").read_text(encoding="utf-8") == "yes"
    assert not (tmp_path / "escape.txt").exists()
    assert not (target.parent / "escape.txt").exists()


def test_target_directory_is_excluded_from_the_search(tmp_path):
    search = tmp_path / "search"
    target = search / "extracted"
    make_zip(search / "outer.zip", {"a.txt": "a"})
    make_zip(target / "already_here.zip", {"b.txt": "b"})

    runner = extractor(search, target)
    assert runner.find_archives() == [str(search / "outer.zip")]

    runner.run()
    assert (target / "a.txt").exists()
    assert not (target / "b.txt").exists()


def test_rerun_finds_nothing_new(tmp_path):
    search = tmp_path / "search"
    target = search / "extracted"
    make_zip(search / "nested.zip", {"inner.zip": "not really a zip"})

    runner = extractor(search, target)
    runner.run()
    assert (target / "inner.zip").exists()

    second = extractor(search, target)
    assert second.find_archives() == [str(search / "nested.zip")]


def test_pattern_and_recursive_filtering(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "report_a.zip", {"a.txt": "a"})
    make_zip(search / "other.zip", {"b.txt": "b"})
    make_zip(search / "nested" / "report_b.zip", {"c.txt": "c"})

    matched = extractor(search, target, pattern="report_*.zip").find_archives()
    assert matched == [
        str(search / "nested" / "report_b.zip"),
        str(search / "report_a.zip"),
    ]

    shallow = extractor(search, target, pattern="report_*.zip", recursive=False)
    assert shallow.find_archives() == [str(search / "report_a.zip")]


def test_unreadable_archive_is_reported_without_stopping_the_run(tmp_path):
    search = tmp_path / "search"
    target = tmp_path / "out"
    search.mkdir(parents=True)
    (search / "broken.zip").write_text("not a zip at all", encoding="utf-8")
    make_zip(search / "good.zip", {"a.txt": "a"})

    runner = extractor(search, target)
    plan = runner.preview()
    runner.run()

    assert [entry["archive"] for entry in plan["unreadable"]] == [str(search / "broken.zip")]
    assert (target / "a.txt").read_text(encoding="utf-8") == "a"


def test_delete_sources_removes_extracted_archives_only(tmp_path, monkeypatch):
    search = tmp_path / "search"
    target = tmp_path / "out"
    search.mkdir(parents=True)
    (search / "broken.zip").write_text("not a zip at all", encoding="utf-8")
    make_zip(search / "good.zip", {"a.txt": "a"})

    removed = []
    monkeypatch.setattr(
        "refacdir.archive_extractor.remove_file",
        lambda path: removed.append(path) or True,
    )

    extractor(search, target, delete_sources=True).run()

    assert removed == [str(search / "good.zip")]


def test_delete_sources_is_not_applied_on_a_dry_run(tmp_path, monkeypatch):
    search = tmp_path / "search"
    target = tmp_path / "out"
    make_zip(search / "good.zip", {"a.txt": "a"})

    removed = []
    monkeypatch.setattr(
        "refacdir.archive_extractor.remove_file",
        lambda path: removed.append(path) or True,
    )

    extractor(search, target, delete_sources=True, test=True).run()

    assert removed == []
    assert (search / "good.zip").exists()


def test_target_inside_search_is_rejected_when_it_swallows_the_search_dir(tmp_path):
    search = tmp_path / "tree" / "inner"
    target = tmp_path / "tree"
    make_zip(search / "a.zip", {"a.txt": "a"})

    with pytest.raises(Exception, match="would find nothing"):
        extractor(search, target).run()


def test_missing_search_directory_raises(tmp_path):
    with pytest.raises(Exception, match="Invalid search directory"):
        extractor(tmp_path / "nope", tmp_path / "out").run()
