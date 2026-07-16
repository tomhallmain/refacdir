"""Unit tests for the static ``common_pattern_presets`` catalog.

Unlike ``suggest_renamer_rules``, these presets are not derived from scanning
any directory — they're a fixed catalog of well-known filename shapes that a
user can pick from in the renamer rule suggester UI.
"""

from refacdir.renamer_rule_generation import common_pattern_presets


def test_returns_a_non_empty_list_of_presets():
    presets = common_pattern_presets()
    assert isinstance(presets, list)
    assert len(presets) > 0


def test_each_preset_has_the_expected_shape():
    for preset in common_pattern_presets():
        assert isinstance(preset.get("name"), str) and preset["name"]
        assert isinstance(preset.get("search_patterns"), str) and preset["search_patterns"]
        assert isinstance(preset.get("rename_tag"), str) and preset["rename_tag"]
        assert isinstance(preset.get("reason"), str) and preset["reason"]
        assert isinstance(preset.get("function_hint"), str) and preset["function_hint"]


def test_includes_integer_basename_preset():
    presets = common_pattern_presets()
    names = [p["name"] for p in presets]
    assert "Integer Basename" in names
    integer_preset = next(p for p in presets if p["name"] == "Integer Basename")
    assert integer_preset["search_patterns"] == "{{is_short_integer_filename}}"


def test_returned_list_is_a_copy_not_shared_mutable_state():
    first = common_pattern_presets()
    first[0]["name"] = "mutated"
    second = common_pattern_presets()
    assert second[0]["name"] != "mutated"
