"""Unit tests for ``is_id`` and ``is_id_filename`` in custom_file_name_search_funcs."""

import pytest

from custom_file_name_search_funcs import is_id, is_id_filename


# ---------------------------------------------------------------------------
# is_id — cases that should return True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("s, description", [
    # Tier 1: alpha-digit-alpha interleaving within a segment
    ("ab3f6d",          "short hex-like with single-char digit groups embedded in alpha"),
    ("a3b9f2d1",        "pure alternating alpha-digit pattern"),
    ("a1b2c3",          "alternating alpha-digit, at minimum length"),
    ("R3fAc7xK2mP9qL",  "mixed case with many embedded digit groups"),
    ("TKFqm8n2Xp",      "mixed case, leading alpha group longer than 3 chars but trailing is short"),
    ("x9y",             "three-char interleaved — too short for old min_length but clear pattern",),
    # Tier 2: pure hex fast-path (stripped length >= 8, contains alpha hex char)
    ("550e8400e29b41d4", "UUID segment — all lowercase hex"),
    ("deadbeef0123",     "all lowercase hex, 12 chars"),
    ("DEADBEEF0123",     "all uppercase hex, 12 chars"),
    ("a1b2c3d4e5f6",    "12-char lowercase hex, also has interleaving"),
    # Tier 3: entropy + structural heuristics (longer pure-alpha mixed-case)
    ("RkQmTvXnPwLz",    "mixed case pure-alpha, high case-transition density"),
    ("xKqMvNpRwLtZ",    "mixed case pure-alpha, every pair transitions"),
])
def test_is_id_returns_true(s, description):
    assert is_id(s) is True, description


# ---------------------------------------------------------------------------
# is_id — cases that should return False
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("s, description", [
    # Too short / digit not sandwiched
    ("ab3",             "three chars — digit at end only, no right alpha neighbour"),
    # Digits only at the end (word + sequential number)
    ("cad357",          "three-char word-like prefix plus trailing number"),
    ("backup2023",      "word plus four-digit year at end"),
    ("version2",        "word plus single trailing digit"),
    ("v2_backup",       "short version prefix plus word"),
    ("file001",         "word plus zero-padded sequence number"),
    # Digits only at the start
    ("2024report",      "year prefix plus word"),
    # Words and structured names
    ("myDocument",      "camelCase — two words"),
    ("MyDocumentName",  "PascalCase — three words"),
    ("file_backup",     "snake_case — two words"),
    ("CamelCaseWord",   "PascalCase — three words, low transition density"),
    ("MyFileBackup",    "PascalCase — two words, low transition density"),
    # Year or number sandwiched between full words
    ("backup2023final", "word plus year plus word — both neighbours are long"),
    ("Document5File",   "PascalCase word plus digit plus word, long neighbours"),
    # Structured camera / system filenames
    ("IMG_20231201",    "camera filename with date"),
    ("DSC_1234",        "camera filename with sequence number"),
    # Contains disallowed characters
    ("ab 3f6d",         "space inside string"),
    ("ab3f!6d",         "exclamation mark inside string"),
])
def test_is_id_returns_false(s, description):
    assert is_id(s) is False, description


# ---------------------------------------------------------------------------
# is_id — fixed_length parameter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("s, fixed_length, expected, description", [
    ("R3fAc7xK2mP9qL",  14, True,  "exact fixed_length match — should pass"),
    ("R3fAc7xK2mP9qL",  13, False, "one char too long for fixed_length"),
    ("R3fAc7xK2mP9qL",  15, False, "one char too short for fixed_length"),
    ("ab3f6d",           6,  True,  "short ID at exact fixed_length"),
    ("ab3f6d",           7,  False, "short ID one char below fixed_length"),
])
def test_is_id_fixed_length(s, fixed_length, expected, description):
    assert is_id(s, fixed_length=fixed_length) is expected, description


# ---------------------------------------------------------------------------
# is_id — min_length parameter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("s, min_length, expected, description", [
    # Tier 1 interleaving bypasses the min_length gate entirely
    ("a1b2c", 5, True,  "five-char interleaved — Tier 1 fires at any min_length"),
    ("a1b2c", 9, True,  "Tier 1 still fires even when min_length exceeds string length"),
    # min_length does gate Tier 2 (non-interleaved hex strings)
    ("abcd1234", 8, True,  "8-char trailing-digit hex at exact min_length"),
    ("abcd1234", 9, False, "8-char trailing-digit hex blocked by raised min_length"),
])
def test_is_id_min_length(s, min_length, expected, description):
    assert is_id(s, min_length=min_length) is expected, description


# ---------------------------------------------------------------------------
# is_id_filename — exercises the filename wrapper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename, fixed_length, expected, description", [
    ("R3fAc7xK2mP9qL7pQr8.jpg",  19, True,  "ID stem of length 19 with extension"),
    ("myDocument.txt",            19, False, "non-ID stem — wrong length and not an ID"),
    ("myDocument.txt",            10, False, "non-ID stem even at matching length"),
    ("/some/path/ab3f6d9k2m.png", 10, True,  "ID stem extracted from absolute path"),
    ("no_extension_ab3f",         None, False, "no extension, stem too short for default fixed_length=22"),
])
def test_is_id_filename(filename, fixed_length, expected, description):
    if fixed_length is None:
        assert is_id_filename(filename) is expected, description
    else:
        assert is_id_filename(filename, fixed_length=fixed_length) is expected, description
