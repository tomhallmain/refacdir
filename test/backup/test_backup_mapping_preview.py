"""
Tests for ``BackupMapping.preview_changes()`` — a read-only summary of what
``backup()`` would do, built from the hash tables ``setup()`` already
collects. Added for the LLM config-chat feature's Phase 4 match/affected-file
preview (docs/LLM_CONFIG_CHAT_SCOPE.md), but it's a general-purpose addition
to BackupMapping, not LLM-specific itself — these tests exercise it directly,
independent of anything in refacdir/llm/.
"""

from refacdir.backup.backup_mapping import BackupMapping
from refacdir.backup.backup_modes import BackupMode


def test_preview_new_source_files_are_to_add_or_update(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")

    mapping = BackupMapping(name="m", source_dir=str(source), target_dir=str(target))
    mapping.setup()

    changes = mapping.preview_changes()
    assert len(changes["to_add_or_update"]) == 1
    assert changes["to_add_or_update"][0].endswith("a.txt")
    assert changes["to_remove_stale"] == []


def test_preview_unchanged_file_is_not_listed(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (target / "a.txt").write_text("hello", encoding="utf-8")

    mapping = BackupMapping(name="m", source_dir=str(source), target_dir=str(target))
    mapping.setup()

    changes = mapping.preview_changes()
    assert changes["to_add_or_update"] == []


def test_preview_changed_content_is_to_add_or_update(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("new content", encoding="utf-8")
    (target / "a.txt").write_text("old content", encoding="utf-8")

    mapping = BackupMapping(name="m", source_dir=str(source), target_dir=str(target))
    mapping.setup()

    changes = mapping.preview_changes()
    assert len(changes["to_add_or_update"]) == 1
    assert changes["to_add_or_update"][0].endswith("a.txt")


def test_preview_stale_target_file_only_flagged_in_mirror_mode(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (target / "stale.txt").write_text("orphaned", encoding="utf-8")

    push_mapping = BackupMapping(
        name="push", source_dir=str(source), target_dir=str(target), mode=BackupMode.PUSH,
    )
    push_mapping.setup()
    assert push_mapping.preview_changes()["to_remove_stale"] == []

    mirror_mapping = BackupMapping(
        name="mirror", source_dir=str(source), target_dir=str(target), mode=BackupMode.MIRROR,
    )
    mirror_mapping.setup()
    stale = mirror_mapping.preview_changes()["to_remove_stale"]
    assert len(stale) == 1
    assert stale[0].endswith("stale.txt")


def test_preview_does_not_touch_disk(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (target / "stale.txt").write_text("orphaned", encoding="utf-8")

    mapping = BackupMapping(
        name="m", source_dir=str(source), target_dir=str(target), mode=BackupMode.MIRROR,
    )
    mapping.setup()
    mapping.preview_changes()

    assert not (target / "a.txt").exists()
    assert (target / "stale.txt").exists()
