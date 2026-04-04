"""``os_stat_rename_func`` — mtime/ctime naming, 17-digit timestamp preservation."""

import os

import pytest

from refacdir.file_renamer import FileRenamer


def test_os_stat_rename_preserves_existing_seventeen_digit_timestamp_preserve_alpha(tmp_path):
    """Basename already contains ``_<17 digits>_<rest>``; digits and tail are kept."""
    root = str(tmp_path)
    fr = FileRenamer(root, test=True, preserve_alpha=True)
    fn = fr.os_stat_rename_func("st_mtime", "img_")
    rel = "shot_12345678901234567_tail.txt"
    (tmp_path / rel).write_text("x", encoding="utf-8")
    path = os.path.join(root, rel)
    assert fn(path) == "img_12345678901234567_tail.txt"


def test_os_stat_rename_preserves_timestamp_without_preserve_alpha(tmp_path):
    """With ``preserve_alpha=False``, ``rest`` after the timestamp is still appended."""
    root = str(tmp_path)
    fr = FileRenamer(root, test=True, preserve_alpha=False)
    fn = fr.os_stat_rename_func("st_mtime", "z_")
    rel = "a_99999999999999999_suffix.txt"
    (tmp_path / rel).write_text("x", encoding="utf-8")
    path = os.path.join(root, rel)
    assert fn(path) == "z_99999999999999999_suffix.txt"


def test_os_stat_rename_uses_stat_mtime_when_no_timestamp_in_basename(tmp_path):
    """No ``_<17d>`` match: ``st_mtime`` (or ctime) is padded to 17 digits."""
    root = str(tmp_path)
    fr = FileRenamer(root, test=True, preserve_alpha=True)
    fn = fr.os_stat_rename_func("st_mtime", "pfx_")
    rel = "plain.txt"
    p = tmp_path / rel
    p.write_text("x", encoding="utf-8")
    fixed = 1_700_000_000.0
    os.utime(p, (fixed, fixed))
    out = fn(str(p))
    assert out.startswith("pfx_")
    assert out.endswith(".txt")
    # Padded stat string replaces dots; length is rename_base + 17 + alpha + ext
    stat_str = str(os.stat(str(p)).st_mtime).replace(".", "")
    while len(stat_str) < 17:
        stat_str += "0"
    assert stat_str in out


def test_os_stat_rename_ctime_attr_uses_st_ctime(tmp_path):
    root = str(tmp_path)
    fr = FileRenamer(root, test=True, preserve_alpha=False)
    fn = fr.os_stat_rename_func("st_ctime", "c_")
    rel = "only.txt"
    p = tmp_path / rel
    p.write_text("y", encoding="utf-8")
    stat_str = str(os.stat(str(p)).st_ctime).replace(".", "")
    while len(stat_str) < 17:
        stat_str += "0"
    assert fn(str(p)) == f"c_{stat_str}.txt"


def test_os_stat_rename_collision_increment_adjusts_time_str():
    """``increment`` / ``positive`` branch mutates the 17-digit time string."""
    fr = FileRenamer(".", test=True, preserve_alpha=True)
    fn = fr.os_stat_rename_func("st_mtime", "x_")
    # Synthetic path only — no stat read on this branch if timestamp_match
    out = fn("dir_11111111111111111_a.txt", increment=2, positive=True)
    assert "11111111111111113" in out
