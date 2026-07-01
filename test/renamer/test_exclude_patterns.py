"""Tests for rename-rule exclude_patterns."""

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.filename_ops import FilenameMappingDefinition


def test_construct_mappings_wraps_exclude_patterns_in_callable():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": "0[0-9][0-9][0-9][0-9]_",
                "exclude_patterns": "*_[0-9]*x[0-9]*.jpg",
                "rename_tag": "SDWebui_",
            }
        ]
    )
    assert len(mappings) == 1
    matcher = next(iter(mappings))
    assert callable(matcher)
    assert matcher("00042_prompt.png")
    assert not matcher("00000_abc_600x450.jpg")


def test_exclude_patterns_skip_dimension_thumbnails_but_rename_sd_style(tmp_path):
    (tmp_path / "00042_prompt.png").write_text("sd", encoding="utf-8")
    (tmp_path / "00000_abc_600x450.jpg").write_text("thumb", encoding="utf-8")

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
    br = BatchRenamer(
        "unit",
        mappings,
        [Location(str(tmp_path))],
        test=False,
        skip_confirm=True,
        recursive=False,
    )
    br.rename_by_ctime()

    assert (tmp_path / "00000_abc_600x450.jpg").exists()
    assert not (tmp_path / "00042_prompt.png").exists()
    assert any(f.name.startswith("SDWebui_") and f.suffix == ".png" for f in tmp_path.iterdir())


def test_exclude_patterns_apply_to_each_search_pattern_in_list():
    mappings = FilenameMappingDefinition.construct_mappings(
        [
            {
                "search_patterns": ["*.txt", "*.md"],
                "exclude_patterns": ["*.skip.txt", "*.skip.md"],
                "rename_tag": "x_",
            }
        ]
    )
    assert len(mappings) == 2
    matchers = list(mappings.keys())
    assert all(callable(m) for m in matchers)

    txt_matcher = next(m for m in matchers if m("notes.txt"))
    md_matcher = next(m for m in matchers if m("readme.md"))

    assert txt_matcher("notes.txt")
    assert not txt_matcher("notes.skip.txt")
    assert not txt_matcher("readme.md")

    assert md_matcher("readme.md")
    assert not md_matcher("readme.skip.md")
    assert not md_matcher("notes.txt")
