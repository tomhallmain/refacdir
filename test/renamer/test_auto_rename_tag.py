"""
Tests for auto-derived rename_tag: a mapping may omit rename_tag when every
one of its search_patterns is a plain literal string. Each pattern then gets
its own tag (the pattern with any "*" removed, plus a trailing "_") instead
of being collapsed under one shared tag.

See FilenameMappingDefinition.construct_mappings / _derive_rename_tag.
"""

import pytest

from refacdir.filename_ops import FilenameMappingDefinition


def test_single_literal_pattern_without_rename_tag_derives_tag():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "maxresdefault"}]
    )
    assert mappings == {"maxresdefault": "maxresdefault_"}


def test_derivation_strips_existing_asterisks_before_appending_underscore():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "0[0-9][0-9][0-9][0-9]_*"}]
    )
    tag = next(iter(mappings.values()))
    assert tag == "0[0-9][0-9][0-9][0-9]__"


def test_derivation_strips_trailing_dot_star_as_a_unit():
    # A trailing ".*" (used to anchor a literal to a whole basename, e.g. the
    # Notorious Default/Generic Filenames preset's "imgproxy.*") should derive
    # "imgproxy_", not leave a stray "." behind ("imgproxy._").
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "imgproxy.*"}]
    )
    tag = next(iter(mappings.values()))
    assert tag == "imgproxy_"


def test_list_of_literal_patterns_each_get_their_own_derived_tag():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": ["maxresdefault", "hqdefault", "thumb"]}]
    )
    assert mappings == {
        "maxresdefault": "maxresdefault_",
        "hqdefault": "hqdefault_",
        "thumb": "thumb_",
    }


def test_dict_form_entry_without_rename_tag_derives_from_its_pattern():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": [
                    {"pattern": "report.pdf", "chain_parenthetical_indices": True},
                ],
            }
        ]
    )
    matcher = next(iter(mappings))
    assert callable(matcher)  # wrapped for parenthetical chaining
    assert mappings[matcher] == "report.pdf_"


def test_explicit_rename_tag_takes_precedence_over_derivation():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "maxresdefault", "rename_tag": "yt_"}]
    )
    assert mappings == {"maxresdefault": "yt_"}


def test_templated_pattern_without_rename_tag_raises():
    with pytest.raises(Exception):
        FilenameMappingDefinition.construct_mappings(
            [{"search_patterns": "{{is_short_integer_filename}}"}]
        )


def test_callable_pattern_without_rename_tag_raises():
    with pytest.raises(Exception):
        FilenameMappingDefinition.construct_mappings(
            [{"search_patterns": lambda f: True}]
        )
