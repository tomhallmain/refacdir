"""Tests for rename-rule exclude_patterns."""

import glob as glob_module

import pytest

import refacdir.file_renamer as file_renamer_module
from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.file_renamer import FileRenamer
from refacdir.filename_ops import FilenameMappingDefinition


@pytest.fixture
def restore_cwd():
    import os
    cwd = os.getcwd()
    yield
    try:
        os.chdir(cwd)
    except OSError:
        pass


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


# ---------------------------------------------------------------------------
# Regression: an exclude_patterns-wrapped matcher must not force
# FileRenamer.find_matches into its unfiltered whole-tree "**/*" fallback.
#
# That fallback exists for genuinely arbitrary custom matcher functions with no
# backing glob string. Before the fix, ANY exclude_patterns wrapping collapsed
# straight to it too — even for plain glob include patterns — so a recursive
# scan of a large directory (e.g. a real config's ``F:\img`` location) walked
# and stat-checked *every file and every directory at every depth* once per
# search pattern, instead of a glob scoped to that pattern. That is what made
# real runs appear to stall for many minutes on large locations.
# ---------------------------------------------------------------------------

def test_exclude_patterns_matcher_carries_forward_narrow_glob_pattern():
    """The wrapped matcher must remember the original glob string it was built from."""
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
    assert callable(matcher)
    assert matcher.glob_pattern == "0[0-9][0-9][0-9][0-9]_"


def test_find_matches_scopes_glob_instead_of_scanning_whole_tree(tmp_path, restore_cwd, monkeypatch):
    """
    End-to-end guard for the reported stall: FileRenamer.find_matches must issue
    a glob scoped to the mapping's pattern, not the "**/*" fallback, when the
    matcher is only wrapping exclude_patterns around a plain glob string.
    """
    (tmp_path / "00042_prompt.png").write_text("sd", encoding="utf-8")
    (tmp_path / "00000_abc_600x450.jpg").write_text("thumb", encoding="utf-8")
    # A big, deep, unrelated subtree standing in for a large real-world location
    # (e.g. "F:\\img"): if find_matches ever falls back to "**/*" here, it would
    # walk and test every one of these too instead of being scoped out by the glob.
    noise_dir = tmp_path / "unrelated" / "nested" / "deeper"
    noise_dir.mkdir(parents=True)
    for i in range(25):
        (noise_dir / f"noise_{i}.dat").write_text("noise", encoding="utf-8")

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

    seen_glob_exprs = []
    real_glob = glob_module.glob

    class _SpyGlobModule:
        @staticmethod
        def glob(pattern, **kwargs):
            seen_glob_exprs.append(pattern)
            return real_glob(pattern, **kwargs)

    # Replace the ``glob`` name only within file_renamer's own module namespace
    # (rather than patching the shared stdlib module's ``.glob`` attribute
    # globally), so the spy is scoped to this test.
    monkeypatch.setattr(file_renamer_module, "glob", _SpyGlobModule)

    fr = FileRenamer(str(tmp_path))
    matches = fr.find_matches(matcher, recursive=True)

    assert seen_glob_exprs, "glob.glob was never called"
    assert all(expr in ("**/0[0-9][0-9][0-9][0-9]_*",) for expr in seen_glob_exprs), (
        f"find_matches fell back to an unfiltered whole-tree scan instead of a "
        f"pattern-scoped glob: {seen_glob_exprs}"
    )
    assert matches == ["00042_prompt.png"]
