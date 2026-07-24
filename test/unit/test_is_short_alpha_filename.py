"""Unit tests for ``is_short_alpha_filename`` in custom_file_name_search_funcs."""

import pytest

from custom_file_name_search_funcs import is_short_alpha_filename


@pytest.mark.parametrize(
    "filename",
    [
        "R.png",
        "O.jpg",
        "ab.txt",
        "R",  # no extension
    ],
)
def test_matches_short_all_letter_basenames(filename):
    assert is_short_alpha_filename(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        "abc.jpg",  # too long (default max_length=2)
        "report.pdf",  # not short
        "1.jpg",  # not letters
        "R (1).png",  # parenthetical suffix breaks pure-alpha basename
        "",
        # Regression: a basename with an unrelated "." well before the real
        # extension must not have everything after that first "." misread as
        # the extension, leaving a short-looking "stem" before it.
        "I._Heidelberg_Altstadt_Campus_Universitat_Heidelberg_Bunsen_Denkmal.jpg",
    ],
)
def test_rejects_non_matching_basenames(filename):
    assert is_short_alpha_filename(filename) is False


def test_max_length_is_configurable():
    assert is_short_alpha_filename("abc.jpg", max_length=3) is True
    assert is_short_alpha_filename("abc.jpg", max_length=2) is False


def test_directory_component_is_ignored():
    assert is_short_alpha_filename("/some/dir/R.png") is True
