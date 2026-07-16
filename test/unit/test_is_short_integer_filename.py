"""Unit tests for ``is_short_integer_filename`` in custom_file_name_search_funcs."""

import pytest

from custom_file_name_search_funcs import is_short_integer_filename


@pytest.mark.parametrize(
    "filename",
    [
        "1.jpg",
        "12.png",
        "123.txt",
        "1234.jpg",
        "12345.jpg",
        "12345",  # no extension
    ],
)
def test_matches_short_all_digit_basenames(filename):
    assert is_short_integer_filename(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        "123456.jpg",  # too long (default max_length=5)
        "report.pdf",  # not digits
        "img_1234.jpg",  # not purely digits
        "12a.jpg",  # mixed alnum
        "1234 (1).jpg",  # parenthetical suffix breaks pure-digit basename
        "",
    ],
)
def test_rejects_non_matching_basenames(filename):
    assert is_short_integer_filename(filename) is False


def test_max_length_is_configurable():
    assert is_short_integer_filename("123456.jpg", max_length=6) is True
    assert is_short_integer_filename("123456.jpg", max_length=5) is False


def test_directory_component_is_ignored():
    assert is_short_integer_filename("/some/dir/1234.jpg") is True
