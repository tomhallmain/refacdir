"""Tests for the ``chain_parenthetical_indices`` renamer mapping option.

Auto-chains a search pattern to also match OS/browser "duplicate download"
naming — e.g. a pattern that matches "report.pdf" also matches "report (1).pdf",
"report (2).pdf", etc. — without the user having to define a second pattern.
"""

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.filename_ops import FilenameMappingDefinition, _strip_parenthetical_index


# ---------------------------------------------------------------------------
# _strip_parenthetical_index
# ---------------------------------------------------------------------------

def test_strip_parenthetical_index_with_extension():
    assert _strip_parenthetical_index("report (1).pdf") == "report.pdf"


def test_strip_parenthetical_index_multi_digit():
    assert _strip_parenthetical_index("report (12).pdf") == "report.pdf"


def test_strip_parenthetical_index_no_extension():
    assert _strip_parenthetical_index("my report (2)") == "my report"


def test_strip_parenthetical_index_leaves_non_indexed_names_unchanged():
    assert _strip_parenthetical_index("report.pdf") == "report.pdf"


def test_strip_parenthetical_index_ignores_non_numeric_parens():
    # "(a)" isn't a duplicate-download index, so this should not be touched.
    assert _strip_parenthetical_index("notes (a).txt") == "notes (a).txt"


def test_strip_parenthetical_index_preserves_directory():
    assert _strip_parenthetical_index("subdir/report (1).pdf") == "subdir/report.pdf"


# ---------------------------------------------------------------------------
# construct_mappings — mapping-level default
# ---------------------------------------------------------------------------

def test_construct_mappings_chains_parenthetical_indices_at_mapping_level():
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
    assert callable(matcher)
    assert matcher("report.pdf")
    assert matcher("report (1).pdf")
    assert matcher("report (2).pdf")
    assert not matcher("unrelated.pdf")


def test_construct_mappings_without_chain_flag_does_not_match_indexed_variant():
    mappings = FilenameMappingDefinition.construct_mappings(
        [{"search_patterns": "report.pdf", "rename_tag": "seen_"}]
    )
    matcher = next(iter(mappings))
    # No exclude_patterns and no chaining -> plain glob string, not wrapped in a callable.
    assert matcher == "report.pdf"


# ---------------------------------------------------------------------------
# construct_mappings — per-pattern override within a list
# ---------------------------------------------------------------------------

def test_construct_mappings_per_pattern_override_in_list():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": [
                    {"pattern": "report.pdf", "chain_parenthetical_indices": True},
                    "notes.txt",
                ],
                "rename_tag": "seen_",
            }
        ]
    )
    assert len(mappings) == 2
    matchers = list(mappings.keys())

    chained = next(m for m in matchers if callable(m) and m("report (1).pdf"))
    assert chained("report.pdf")

    plain = next(m for m in matchers if m != chained)
    assert plain == "notes.txt"


def test_construct_mappings_mapping_default_applies_to_all_list_entries_unless_overridden():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": [
                    "report.pdf",
                    {"pattern": "notes.txt", "chain_parenthetical_indices": False},
                ],
                "chain_parenthetical_indices": True,
                "rename_tag": "seen_",
            }
        ]
    )
    matchers = list(mappings.keys())

    report_matcher = next(m for m in matchers if callable(m) and m("report.pdf"))
    assert report_matcher("report (3).pdf")

    notes_matcher = next(m for m in matchers if m != report_matcher)
    assert notes_matcher == "notes.txt"  # override disabled chaining -> stays a plain string


# ---------------------------------------------------------------------------
# Integration: BatchRenamer actually renames both the base file and its
# parenthetical-indexed duplicates, while leaving unrelated files and any
# excluded duplicate alone.
# ---------------------------------------------------------------------------

def test_batch_renamer_renames_base_file_and_indexed_duplicates(tmp_path):
    (tmp_path / "report.pdf").write_text("a", encoding="utf-8")
    (tmp_path / "report (1).pdf").write_text("b", encoding="utf-8")
    (tmp_path / "report (2).pdf").write_text("c", encoding="utf-8")
    (tmp_path / "unrelated.pdf").write_text("d", encoding="utf-8")

    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "report.pdf",
                "chain_parenthetical_indices": True,
                "rename_tag": "Report_",
            }
        ]
    )
    br = BatchRenamer(
        "unit", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    br.rename_by_ctime()

    names = {p.name for p in tmp_path.iterdir()}
    assert "unrelated.pdf" in names
    assert not any(n.startswith("report") for n in names)
    renamed = [n for n in names if n.startswith("Report_")]
    assert len(renamed) == 3


def test_batch_renamer_chain_respects_exclude_patterns(tmp_path):
    (tmp_path / "report.pdf").write_text("a", encoding="utf-8")
    (tmp_path / "report (1).pdf").write_text("b", encoding="utf-8")
    (tmp_path / "report (2).pdf").write_text("c", encoding="utf-8")

    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "report.pdf",
                "chain_parenthetical_indices": True,
                "exclude_patterns": "report (2).pdf",
                "rename_tag": "Report_",
            }
        ]
    )
    br = BatchRenamer(
        "unit", mappings, [Location(str(tmp_path))],
        test=False, skip_confirm=True, recursive=False,
    )
    br.rename_by_ctime()

    names = {p.name for p in tmp_path.iterdir()}
    assert "report (2).pdf" in names  # excluded, untouched
    renamed = [n for n in names if n.startswith("Report_")]
    assert len(renamed) == 2
