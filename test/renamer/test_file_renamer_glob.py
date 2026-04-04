"""Unit tests for ``FileRenamer.get_glob_pattern`` (used with ``glob.glob``)."""

import pytest

from refacdir.file_renamer import FileRenamer


@pytest.mark.parametrize(
    "pattern, recursive, expected",
    [
        ("", False, "*"),
        ("*.txt", False, "*.txt*"),
        ("foo", False, "foo*"),
        ("", True, "**/*"),
        ("*.txt", True, "**/*.txt*"),
        ("sub", True, "**/sub*"),
    ],
)
def test_get_glob_pattern_appends_star_and_optional_recursive_prefix(pattern, recursive, expected):
    assert FileRenamer.get_glob_pattern(pattern, recursive=recursive) == expected
