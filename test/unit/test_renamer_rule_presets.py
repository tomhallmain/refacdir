"""Unit tests for the static ``common_pattern_presets`` catalog.

Unlike ``suggest_renamer_rules``, these presets are not derived from scanning
any directory — they're a fixed catalog of well-known filename shapes that a
user can pick from in the renamer rule suggester UI.
"""

from refacdir.filename_ops import FilenameMappingDefinition
from refacdir.renamer_rule_generation import common_pattern_presets


def test_returns_a_non_empty_list_of_presets():
    presets = common_pattern_presets()
    assert isinstance(presets, list)
    assert len(presets) > 0


def test_each_preset_has_the_expected_shape():
    for preset in common_pattern_presets():
        assert isinstance(preset.get("name"), str) and preset["name"]
        assert isinstance(preset.get("search_patterns"), str) and preset["search_patterns"]
        # rename_tag may be omitted (auto-derived per pattern by
        # FilenameMappingDefinition.construct_mappings) but must not be an
        # explicit blank string sitting in the catalog.
        rename_tag = preset.get("rename_tag")
        assert rename_tag is None or (isinstance(rename_tag, str) and rename_tag)
        assert isinstance(preset.get("reason"), str) and preset["reason"]
        assert isinstance(preset.get("function_hint"), str) and preset["function_hint"]


def test_includes_integer_basename_preset():
    presets = common_pattern_presets()
    names = [p["name"] for p in presets]
    assert "Integer Basename" in names
    integer_preset = next(p for p in presets if p["name"] == "Integer Basename")
    assert integer_preset["search_patterns"] == "{{is_short_integer_filename}}"


def test_notorious_default_preset_has_no_fixed_rename_tag():
    """
    Each literal basename in this preset should get its own auto-derived tag
    (see FilenameMappingDefinition.construct_mappings) rather than being
    collapsed under one shared generic tag.
    """
    presets = common_pattern_presets()
    preset = next(p for p in presets if p["name"] == "Notorious Default/Generic Filenames")
    assert "rename_tag" not in preset
    assert "maxresdefault" in preset["search_patterns"]


def test_returned_list_is_a_copy_not_shared_mutable_state():
    first = common_pattern_presets()
    first[0]["name"] = "mutated"
    second = common_pattern_presets()
    assert second[0]["name"] != "mutated"


def _notorious_preset_matchers():
    """
    Build the {matcher: rename_tag} mapping the app would build from the
    "Notorious Default/Generic Filenames" preset, splitting its comma-joined
    search_patterns the same way the rule editor UI does.
    """
    preset = next(
        p for p in common_pattern_presets()
        if p["name"] == "Notorious Default/Generic Filenames"
    )
    patterns = [part.strip() for part in preset["search_patterns"].split(",") if part.strip()]
    return FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": patterns,
                "chain_parenthetical_indices": preset.get("chain_parenthetical_indices", False),
            }
        ]
    )


def _notorious_match(basename):
    return any(matcher(basename) for matcher in _notorious_preset_matchers())


def test_notorious_default_preset_enables_chain_parenthetical_indices():
    presets = common_pattern_presets()
    preset = next(p for p in presets if p["name"] == "Notorious Default/Generic Filenames")
    assert preset["chain_parenthetical_indices"] is True


def test_notorious_default_preset_matches_exact_basename_plus_extension():
    assert _notorious_match("imgproxy.png")
    assert _notorious_match("image.json")
    assert _notorious_match("caption.txt")
    assert _notorious_match("screenshot.png")
    assert _notorious_match("capture.png")
    assert _notorious_match("untitled.png")


def test_notorious_default_preset_matches_chain_indexed_duplicates():
    assert _notorious_match("imgproxy (4).png")
    assert _notorious_match("imgproxy (5).png")
    assert _notorious_match("imgproxy (7).png")


def test_notorious_default_preset_does_not_match_unrelated_longer_names():
    # Regression: "image" must not match as a prefix of an unrelated filename
    # that merely starts with one of the notorious basenames.
    assert not _notorious_match("image_export_settings.json")
    assert not _notorious_match("images.json")
    assert not _notorious_match("imgproxy_report.csv")
    assert not _notorious_match("downloads.zip")
