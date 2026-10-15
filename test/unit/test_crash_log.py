"""refacdir/utils/crash_log.py. faulthandler.enable is stubbed, so the test
process's own fault handling (pytest's) is left as it is."""

import faulthandler

import pytest

from refacdir.utils import crash_log


@pytest.fixture
def fault_log(monkeypatch, tmp_path):
    """A fresh fault log state with the logs dir in tmp_path; returns the
    calls faulthandler.enable received."""
    enabled = []
    monkeypatch.setattr(crash_log, "user_logs_dir", lambda: str(tmp_path))
    monkeypatch.setattr(crash_log, "_fault_log", None)
    monkeypatch.setattr(faulthandler, "enable", lambda **kwargs: enabled.append(kwargs))
    yield enabled
    if crash_log._fault_log is not None:
        crash_log._fault_log.close()


def test_fault_log_writes_a_start_line_and_enables_faulthandler(fault_log, tmp_path):
    path = crash_log.enable_fault_log()
    assert path == str(tmp_path / crash_log.FAULT_LOG_NAME)
    text = (tmp_path / crash_log.FAULT_LOG_NAME).read_text(encoding="utf-8")
    assert text.startswith("--- started ")
    assert "RefacDir " in text
    assert len(fault_log) == 1
    assert fault_log[0]["all_threads"] is True


def test_fault_log_is_opened_once(fault_log):
    assert crash_log.enable_fault_log() == crash_log.enable_fault_log()
    assert len(fault_log) == 1


def test_fault_log_appends_to_a_small_file(fault_log, tmp_path):
    (tmp_path / crash_log.FAULT_LOG_NAME).write_text("earlier\n", encoding="utf-8")
    crash_log.enable_fault_log()
    crash_log._fault_log.flush()
    assert (tmp_path / crash_log.FAULT_LOG_NAME).read_text(encoding="utf-8").startswith("earlier\n")


def test_fault_log_starts_afresh_past_the_size_limit(fault_log, tmp_path, monkeypatch):
    monkeypatch.setattr(crash_log, "MAX_FAULT_LOG_BYTES", 4)
    (tmp_path / crash_log.FAULT_LOG_NAME).write_text("earlier\n", encoding="utf-8")
    crash_log.enable_fault_log()
    crash_log._fault_log.flush()
    assert "earlier" not in (tmp_path / crash_log.FAULT_LOG_NAME).read_text(encoding="utf-8")


def test_fault_log_name_is_outside_the_log_cleanup_pattern():
    """refacdir/utils/logger.py deletes old files matching refacdir_*.log."""
    import fnmatch

    assert not fnmatch.fnmatch(crash_log.FAULT_LOG_NAME, "refacdir_*.log")
