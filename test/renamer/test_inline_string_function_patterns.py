"""
Tests for the inline ``{{type:arg1:arg2}}`` StringFunction syntax in
``refacdir/filename_ops.py`` — e.g. ``{{digits:4}}`` or ``{{hex:64}}`` — which
lets a pattern use any digit-count/length directly without a config having to
pre-declare a named ``filename_mapping_functions`` entry (four_digits,
five_digits, six_digits, ...) for every value it needs.
"""

from refacdir.filename_ops import FilenameMappingDefinition, StringFunction


# ---------------------------------------------------------------------------
# Low-level: compiled() produces the same glob fragment as the equivalent
# named filename_mapping_functions declaration would have.
# ---------------------------------------------------------------------------

def test_inline_digits_matches_named_equivalent():
    inline = FilenameMappingDefinition.compiled("{{digits:4}}")
    named = StringFunction.DIGITS(4)
    assert inline == named == "[0-9][0-9][0-9][0-9]"


def test_inline_hex_defaults_to_uppercase():
    inline = FilenameMappingDefinition.compiled("{{hex:64}}")
    assert inline == StringFunction.HEX(64)
    assert inline == "[0-9A-F]" * 64


def test_inline_hex_lowercase_flag():
    inline = FilenameMappingDefinition.compiled("{{hex:8:true}}")
    assert inline == StringFunction.HEX(8, True)
    assert inline == "[0-9a-f]" * 8


def test_inline_alnum_lowercase():
    inline = FilenameMappingDefinition.compiled("{{alnum:6:true}}")
    assert inline == StringFunction.ALNUM(6, True)
    assert inline == "[0-9a-z]" * 6


def test_inline_alnum_lowercase_with_extra_chars():
    inline = FilenameMappingDefinition.compiled("{{alnum:8:true:_}}")
    assert inline == StringFunction.ALNUM(8, True, "_")
    assert "_" in inline


def test_inline_alnum_mixed_case_token():
    inline = FilenameMappingDefinition.compiled("{{alnum:4:mixed}}")
    assert inline == StringFunction.ALNUM(4, None)
    assert inline == "[0-9A-Za-z]" * 4


def test_inline_rep():
    inline = FilenameMappingDefinition.compiled("{{rep:AB:3}}")
    assert inline == "ABABAB"


def test_inline_syntax_works_embedded_in_a_larger_pattern():
    inline = FilenameMappingDefinition.compiled("tmp{{alnum:8:true:_}}.png")
    assert inline.startswith("tmp[")
    assert inline.endswith("].png")


def test_multiple_inline_groups_in_one_pattern():
    inline = FilenameMappingDefinition.compiled("{{digits:2}}-{{hex:4}}")
    assert inline == "[0-9][0-9]-[0-9A-F][0-9A-F][0-9A-F][0-9A-F]"


# ---------------------------------------------------------------------------
# Regression: plain (no ":") names are unaffected, still resolved via
# NAMED_FUNCTIONS / custom_file_name_search_funcs as before.
# ---------------------------------------------------------------------------

def test_plain_named_function_without_colon_still_works():
    FilenameMappingDefinition.add_named_functions(
        [{"name": "four_digits", "type": "DIGITS", "args": [4]}]
    )
    try:
        result = FilenameMappingDefinition.compiled("{{four_digits}}")
        assert result == "[0-9][0-9][0-9][0-9]"
    finally:
        FilenameMappingDefinition.reset_registration_state()


def test_unrecognized_type_prefix_falls_through_to_named_lookup_error():
    """"foo:4" isn't a known StringFunction type, so it must behave exactly as
    an unresolvable name did before this feature existed (a clear error, not a
    silent/incorrect match)."""
    try:
        FilenameMappingDefinition.compiled("{{foo:4}}")
        assert False, "expected an Exception for an unresolvable pattern"
    except Exception as exc:
        assert "foo:4" in str(exc)


# ---------------------------------------------------------------------------
# Integration: construct_mappings + matching against real filenames.
# ---------------------------------------------------------------------------

def test_construct_mappings_inline_digits_matches_expected_filenames():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "{{digits:4}}", "rename_tag": "num_"}]
    )
    pattern = next(iter(mappings))
    assert pattern == "[0-9][0-9][0-9][0-9]"
