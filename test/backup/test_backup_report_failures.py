"""Tests for failure reporting and log output paths."""

import json
import os

import pytest

from refacdir.backup.backup_mapping import BackupMapping
from refacdir.backup.backup_modes import BackupMode, FailureType


def test_report_failures_writes_json(tmp_path, monkeypatch):
    import refacdir.backup.backup_mapping as bm

    log_path = os.path.join(str(tmp_path), "unit_failures.json")
    monkeypatch.setattr(bm, "_FAILURE_LOG", log_path)

    src = tmp_path / "s"
    tgt = tmp_path / "t"
    src.mkdir()
    tgt.mkdir()

    m = BackupMapping(
        name="x",
        source_dir=str(src),
        target_dir=str(tgt),
        mode=BackupMode.PUSH,
    )
    m.failures.append(
        [FailureType.MOVE_FILE, "simulated", r"C:\tgt\a.txt", r"C:\src\a.txt"]
    )
    m.report_failures()

    assert os.path.isfile(log_path)
    data = json.loads(open(log_path, encoding="utf-8").read())
    assert len(data) == 1
    assert data[0][0] == str(FailureType.MOVE_FILE)
    assert "simulated" in data[0][1]


def test_report_failures_defaults_to_the_cache_dir(tmp_path, monkeypatch):
    import refacdir.backup.backup_mapping as bm

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(bm, "_FAILURE_LOG", None)
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(cache_dir))
    src = tmp_path / "s"
    tgt = tmp_path / "t"
    src.mkdir()
    tgt.mkdir()

    m = BackupMapping(name="x", source_dir=str(src), target_dir=str(tgt), mode=BackupMode.PUSH)
    m.failures.append([FailureType.MOVE_FILE, "simulated", "dest", "src"])
    m.report_failures()

    assert (cache_dir / "backup_failures.json").is_file()
