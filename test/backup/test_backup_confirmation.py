"""BackupManager's confirmation: one question listing the mappings, no exit on No."""

from __future__ import annotations

from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMapping, BackupMode
from refacdir.utils.headless_app_actions import build_headless_app_actions


def _manager(tmp_path, answer, asked, *, test=False):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    mapping = BackupMapping(
        name="photos", source_dir=str(source), target_dir=str(target), mode=BackupMode.PUSH
    )

    def confirm(title, message, details=None, acknowledgement=None):
        asked.append((title, message, details, acknowledgement))
        return answer

    actions = build_headless_app_actions({"confirm": confirm})
    manager = BackupManager(
        mappings=[mapping], test=test, skip_confirm=False, app_actions=actions
    )
    return manager, target


def test_declined_backup_returns_without_exiting_or_copying(tmp_path):
    asked = []
    manager, target = _manager(tmp_path, False, asked)

    manager.run()  # a decline must not raise SystemExit

    assert len(asked) == 1
    assert list(target.iterdir()) == []


def test_confirmed_backup_runs(tmp_path):
    asked = []
    manager, target = _manager(tmp_path, True, asked)

    manager.run()

    assert (target / "a.txt").exists()
    _title, _message, details, acknowledgement = asked[0]
    assert "photos" in details
    assert acknowledgement


def test_dry_run_backup_still_asks(tmp_path):
    asked = []
    manager, target = _manager(tmp_path, True, asked, test=True)

    manager.run()

    assert len(asked) == 1
    assert not (target / "a.txt").exists()
