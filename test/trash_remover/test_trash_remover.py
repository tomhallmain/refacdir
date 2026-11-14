"""``TrashRemover`` against directories under ``tmp_path``."""

import os
import threading
import time

import pytest

from refacdir.batch_renamer import Location
from refacdir.trash_remover import TrashRemover, parse_size, protected_directory_reason


def make_tree(root, files: dict):
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def remover(directories, **kwargs):
    kwargs.setdefault("skip_confirm", True)
    return TrashRemover("unit", [Location(str(d)) for d in directories], **kwargs)


def set_age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


class _ConfirmStub:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, title, message, details=None, acknowledgement=None):
        self.calls.append((title, message, details, acknowledgement))
        return self.answer


def test_dry_run_removes_nothing(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "sub/b.txt": "b"})
    remover([trash], test=True).run()
    assert (trash / "a.txt").exists()
    assert (trash / "sub" / "b.txt").exists()


def test_empties_every_directory_and_keeps_the_directories(tmp_path):
    one = make_tree(tmp_path / "one", {"a.txt": "a", "sub/deep/b.txt": "b"})
    two = make_tree(tmp_path / "two", {"c.txt": "c"})
    remover([one, two]).run()
    assert one.is_dir() and two.is_dir()
    assert list(one.iterdir()) == []
    assert list(two.iterdir()) == []


def test_exclude_dirs_are_kept_with_their_contents(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "keep/k.txt": "k", "keep/inner/i.txt": "i"})
    TrashRemover("unit", [Location(str(trash), exclude_dirs=["keep"])], skip_confirm=True).run()
    assert not (trash / "a.txt").exists()
    assert (trash / "keep" / "k.txt").exists()
    assert (trash / "keep" / "inner" / "i.txt").exists()


def test_symlink_is_removed_and_its_target_kept(tmp_path):
    outside = make_tree(tmp_path / "outside", {"precious.txt": "p"})
    trash = tmp_path / "trash"
    trash.mkdir()
    try:
        os.symlink(outside, trash / "link_to_outside", target_is_directory=True)
        os.symlink(outside / "precious.txt", trash / "file_link")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    remover([trash]).run()
    assert list(trash.iterdir()) == []
    assert (outside / "precious.txt").read_text(encoding="utf-8") == "p"


def test_protected_directories_are_refused_at_construction(tmp_path):
    from refacdir.utils.app_paths import app_data_dir

    home = os.path.expanduser("~")
    root = os.path.abspath(os.sep)
    for path in (home, root, app_data_dir(), os.path.dirname(home)):
        assert protected_directory_reason(path) is not None, path
        with pytest.raises(ValueError, match="refusing to empty"):
            TrashRemover("unit", [Location(path)])
    assert protected_directory_reason(str(tmp_path / "trash")) is None


def test_overlapping_directories_are_refused(tmp_path):
    outer = tmp_path / "trash"
    with pytest.raises(ValueError, match="overlap"):
        remover([outer, outer / "inner"])


def test_directories_or_system_trash_are_required():
    with pytest.raises(ValueError, match="directories is required"):
        TrashRemover("unit", [])
    TrashRemover("unit", [], empty_system_trash=True)


def test_invalid_delete_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="delete_mode"):
        remover([tmp_path / "trash"], delete_mode="shred")


def test_unremovable_file_is_a_failure_and_the_rest_is_removed(tmp_path, monkeypatch):
    trash = make_tree(tmp_path / "trash", {"locked.txt": "l", "free.txt": "f"})
    real_remove = os.remove

    def fake_remove(path, *args, **kwargs):
        if os.path.basename(path) == "locked.txt":
            raise PermissionError("in use")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", fake_remove)
    with pytest.raises(Exception, match="could not be removed"):
        remover([trash]).run()
    assert (trash / "locked.txt").exists()
    assert not (trash / "free.txt").exists()


def test_declined_confirmation_removes_nothing(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a"})
    stub = _ConfirmStub(False)
    remover([trash], skip_confirm=False, app_actions=stub).run()
    assert (trash / "a.txt").exists()
    assert len(stub.calls) == 1
    assert stub.calls[0][3] is not None  # permanent deletion asks for an acknowledgement


def test_accepted_confirmation_removes(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a"})
    remover([trash], skip_confirm=False, app_actions=_ConfirmStub(True)).run()
    assert not (trash / "a.txt").exists()


def test_missing_directory_fails_before_removing_by_default(tmp_path):
    present = make_tree(tmp_path / "present", {"a.txt": "a"})
    with pytest.raises(Exception, match="not found"):
        remover([tmp_path / "missing", present]).run()
    assert (present / "a.txt").exists()


def test_missing_directory_is_skipped_when_enabled(tmp_path):
    present = make_tree(tmp_path / "present", {"a.txt": "a"})
    remover([tmp_path / "missing", present], skip_missing_locations=True).run()
    assert not (present / "a.txt").exists()
    assert not (tmp_path / "missing").exists()


def test_all_directories_missing_fails_when_enabled(tmp_path):
    with pytest.raises(Exception, match="None of the locations"):
        remover([tmp_path / "gone1", tmp_path / "gone2"], skip_missing_locations=True).run()


def test_older_than_days_keeps_recent_entries(tmp_path):
    trash = make_tree(tmp_path / "trash", {"old.txt": "o", "new.txt": "n", "olddir/x.txt": "x"})
    set_age(trash / "old.txt", 10)
    set_age(trash / "olddir" / "x.txt", 10)
    set_age(trash / "olddir", 10)
    remover([trash], older_than_days=5).run()
    assert not (trash / "old.txt").exists()
    assert not (trash / "olddir").exists()
    assert (trash / "new.txt").exists()


def test_directory_with_a_kept_file_is_kept(tmp_path):
    trash = make_tree(tmp_path / "trash", {"sub/a.tmp": "a", "sub/b.txt": "b"})
    remover([trash], patterns=["*.tmp"]).run()
    assert not (trash / "sub" / "a.tmp").exists()
    assert (trash / "sub" / "b.txt").exists()


def test_remove_subdirectories_false_keeps_the_tree(tmp_path):
    trash = make_tree(tmp_path / "trash", {"sub/deep/a.txt": "a"})
    remover([trash], remove_subdirectories=False).run()
    assert (trash / "sub" / "deep").is_dir()
    assert not (trash / "sub" / "deep" / "a.txt").exists()


def test_max_entries_fails_without_removing(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "b.txt": "b"})
    with pytest.raises(Exception, match="max_entries"):
        remover([trash], max_entries=1).run()
    assert (trash / "a.txt").exists() and (trash / "b.txt").exists()


def test_max_total_size_fails_without_removing(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "x" * 2048})
    with pytest.raises(Exception, match="max_total_size"):
        remover([trash], max_total_size="1KB").run()
    assert (trash / "a.txt").exists()


def test_parse_size():
    assert parse_size(None) is None
    assert parse_size(10) == 10
    assert parse_size("1KB") == 1024
    assert parse_size("2 gb") == 2 * 1024 ** 3
    with pytest.raises(ValueError):
        parse_size("lots")


def test_system_trash_mode_trashes_whole_directories_as_one_item(tmp_path, trashed_paths):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "sub/b.txt": "b", "sub/c.txt": "c"})
    remover([trash], delete_mode="system_trash").run()
    assert list(trash.iterdir()) == []
    assert sorted(os.path.basename(p) for p in trashed_paths) == ["a.txt", "sub"]


def test_permanent_mode_never_uses_the_system_trash(tmp_path, trashed_paths):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a"})
    remover([trash]).run()
    assert trashed_paths == []


def test_empty_system_trash_empties_the_freedesktop_trash(tmp_path, fake_system_trash):
    make_tree(fake_system_trash, {"files/old.txt": "o", "files/dir/x.txt": "x", "info/old.txt.trashinfo": "i"})
    TrashRemover("unit", [], empty_system_trash=True, skip_confirm=True).run()
    assert list((fake_system_trash / "files").iterdir()) == []
    assert list((fake_system_trash / "info").iterdir()) == []


def test_empty_system_trash_dry_run_keeps_it(tmp_path, fake_system_trash):
    make_tree(fake_system_trash, {"files/old.txt": "o"})
    TrashRemover("unit", [], empty_system_trash=True, test=True).run()
    assert (fake_system_trash / "files" / "old.txt").exists()


def test_unsupported_platform_is_a_failure(monkeypatch):
    monkeypatch.setattr("refacdir.trash_remover._system_trash_platform", lambda: "unsupported")
    with pytest.raises(Exception, match="could not be removed"):
        TrashRemover("unit", [], empty_system_trash=True, skip_confirm=True).run()


def test_will_run_false_skips(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a"})
    remover([trash], will_run=False).run()
    assert (trash / "a.txt").exists()


def test_cancel_stops_before_the_next_directory(tmp_path):
    one = make_tree(tmp_path / "one", {"a.txt": "a"})
    cancel = threading.Event()
    cancel.set()
    remover([one], cancel_event=cancel).run()
    assert (one / "a.txt").exists()


def test_preview_lists_planned_and_missing(tmp_path):
    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "sub/b.txt": "b"})
    plan = remover([trash, tmp_path / "missing"]).preview()
    assert plan["entry_count"] == 3  # two files and sub/
    assert plan["missing"] == [Location(str(tmp_path / "missing")).root]
    assert (trash / "a.txt").exists()


def test_removals_are_recorded_as_not_reversible(tmp_path):
    import refacdir.batch_job_history as history

    trash = make_tree(tmp_path / "trash", {"a.txt": "a", "sub/b.txt": "b"})
    history.begin_batch_job(["cfg.yaml"])
    with history.recording_context(config="cfg.yaml", mapping_name="unit", action_type="trash_remover"):
        remover([trash]).run()
    operations = history._active_session.operations
    assert {os.path.basename(op["source"]) for op in operations} == {"a.txt", "b.txt", "sub"}
    assert all(op["type"] == "delete" and op["reversible"] is False for op in operations)
    assert all(op["dest"] == "" for op in operations)
    assert all(op["meta"]["mapping_name"] == "unit" for op in operations)
