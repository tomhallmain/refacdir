"""
Regression tests for the "With mapping patterns: ..." batch-run log line
(``BatchRenamer.execute`` -> ``Utils.stringify_dict(self.mappings, ...)``).

A wrapped matcher (``chain_parenthetical_indices`` and/or ``exclude_patterns``)
is a plain closure, so by default it would log as the unhelpful
``<function FilenameMappingDefinition._wrap_with_parenthetical_chaining.<locals>.matcher at 0x...>``.
Each wrapper now carries a ``pattern_description`` attribute describing what it
wraps, and ``Utils.stringify_dict`` prefers that description over the raw key
when present.
"""

from refacdir.filename_ops import FilenameMappingDefinition
from refacdir.utils.utils import Utils


# ---------------------------------------------------------------------------
# FilenameMappingDefinition._describe_pattern
# ---------------------------------------------------------------------------

def test_describe_pattern_plain_string_returned_as_is():
    assert FilenameMappingDefinition._describe_pattern("default") == "default"


def test_describe_pattern_uses_pattern_description_attribute_when_present():
    def matcher(path):
        return True
    matcher.pattern_description = "custom description"
    assert FilenameMappingDefinition._describe_pattern(matcher) == "custom description"


def test_describe_pattern_falls_back_to_qualname_for_bare_callable():
    def custom_matcher(path):
        return True
    assert FilenameMappingDefinition._describe_pattern(custom_matcher) == custom_matcher.__qualname__


# ---------------------------------------------------------------------------
# _wrap_with_parenthetical_chaining
# ---------------------------------------------------------------------------

def test_chain_parenthetical_wrapper_describes_wrapped_string_pattern():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "report.pdf",
                "chain_parenthetical_indices": True,
                "rename_tag": "seen_",
            }
        ]
    )
    matcher = next(iter(mappings))
    assert matcher.pattern_description == "chain_parenthetical_indices(report.pdf)"


def test_chain_parenthetical_wrapper_describes_wrapped_callable_pattern():
    def custom_matcher(path):
        return True

    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": custom_matcher,
                "chain_parenthetical_indices": True,
                "rename_tag": "seen_",
            }
        ]
    )
    matcher = next(iter(mappings))
    assert matcher.pattern_description == f"chain_parenthetical_indices({custom_matcher.__qualname__})"


# ---------------------------------------------------------------------------
# _wrap_with_exclude_patterns
# ---------------------------------------------------------------------------

def test_exclude_wrapper_describes_include_and_exclude_patterns():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "0[0-9][0-9][0-9][0-9]_",
                "exclude_patterns": "*_[0-9]*x[0-9]*.jpg",
                "rename_tag": "SDWebui_",
            }
        ]
    )
    matcher = next(iter(mappings))
    assert matcher.pattern_description == (
        "0[0-9][0-9][0-9][0-9]_ excluding [*_[0-9]*x[0-9]*.jpg]"
    )


def test_exclude_wrapper_lists_every_exclude_pattern():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "0[0-9][0-9][0-9][0-9]_",
                "exclude_patterns": [
                    "*_[0-9]*x[0-9]*.jpg",
                    "*_[0-9]*x[0-9]*.jpeg",
                ],
                "rename_tag": "SDWebui_",
            }
        ]
    )
    matcher = next(iter(mappings))
    assert matcher.pattern_description == (
        "0[0-9][0-9][0-9][0-9]_ excluding "
        "[*_[0-9]*x[0-9]*.jpg, *_[0-9]*x[0-9]*.jpeg]"
    )


def test_exclude_wrapper_around_chaining_wrapper_nests_descriptions():
    """Layered wrapping (chaining, then excludes) must describe both layers."""
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "report.pdf",
                "chain_parenthetical_indices": True,
                "exclude_patterns": "report_draft*",
                "rename_tag": "seen_",
            }
        ]
    )
    matcher = next(iter(mappings))
    assert matcher.pattern_description == (
        "chain_parenthetical_indices(report.pdf) excluding [report_draft*]"
    )


# ---------------------------------------------------------------------------
# Utils.stringify_dict
# ---------------------------------------------------------------------------

def test_stringify_dict_uses_pattern_description_for_wrapped_matcher():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "int_val",
                "chain_parenthetical_indices": True,
                "rename_tag": "int_",
            },
            {
                "search_patterns": "letter_val",
                "chain_parenthetical_indices": True,
                "rename_tag": "letter_",
            },
        ]
    )
    rendered = Utils.stringify_dict(mappings, do_print=False)

    assert "<function" not in rendered
    assert "chain_parenthetical_indices(int_val) : int_" in rendered
    assert "chain_parenthetical_indices(letter_val) : letter_" in rendered


def test_stringify_dict_leaves_plain_string_keys_unaffected():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "maxresdefault", "rename_tag": "yt_"}]
    )
    rendered = Utils.stringify_dict(mappings, do_print=False)
    assert "maxresdefault : yt_" in rendered
