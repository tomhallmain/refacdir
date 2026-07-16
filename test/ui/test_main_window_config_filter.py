"""
Regression tests for ``MainWindow._config_matches_filter``.

Item #8 in ``docs/IMPROVEMENTS.md``: the sidebar config filter previously only
matched at word boundaries (start of name, after a space, after an underscore),
so typing "backup" would not match "my_backup_jobs.yaml". It should be a plain
substring match, as users expect from a filter box.
"""

from __future__ import annotations

import pytest

from app_qt import MainWindow

pytestmark = pytest.mark.ui


@pytest.mark.parametrize(
    "path, text, expected",
    [
        # Empty/whitespace-only filter text matches everything.
        ("configs/my_backup_jobs.yaml", "", True),
        ("configs/my_backup_jobs.yaml", "   ", True),
        # Substring match anywhere in the basename, not just at a word boundary.
        ("configs/my_backup_jobs.yaml", "backup", True),
        ("configs/my_backup_jobs.yaml", "kup_jo", True),
        ("configs/my_backup_jobs.yaml", "jobs", True),
        # Case-insensitive.
        ("configs/My_Backup_Jobs.yaml", "BACKUP", True),
        # Exact basename and prefix matches still work.
        ("configs/backup.yaml", "backup.yaml", True),
        ("configs/backup.yaml", "back", True),
        # Leading/trailing whitespace in the filter text is trimmed.
        ("configs/my_backup_jobs.yaml", "  backup  ", True),
        # Non-matching text.
        ("configs/my_backup_jobs.yaml", "renamer", False),
    ],
)
def test_config_matches_filter_is_plain_substring_match(path, text, expected):
    assert MainWindow._config_matches_filter(path, text) is expected
