"""
Unit tests for ``ImageCategorizer``.

Weidr supplies ``CompareEmbeddingClip`` and is not a dependency of this repo, so
these patch the two module-level names its import sets up: ``weidr_imported``
(the gate ``__init__`` checks) and ``CompareEmbeddingClip`` itself, which does
not exist as an attribute at all when Weidr is absent — hence ``raising=False``.
The stub stands in for the CLIP call, returning the same ``{text_key: score}``
shape ``single_text_compare`` does.
"""

import os

import pytest

import refacdir.image_categorizer as image_categorizer
from refacdir.image_categorizer import ImageCategorizer


class _StubCompare:
    """Scores each file by a lookup of basename -> winning category."""

    winners = {}

    @staticmethod
    def single_text_compare(media_path, texts_dict):
        import os

        winner = _StubCompare.winners.get(os.path.basename(media_path))
        return {key: (1.0 if key == winner else 0.0) for key in texts_dict}


@pytest.fixture
def weidr_stub(monkeypatch):
    monkeypatch.setattr(image_categorizer, "weidr_imported", True)
    monkeypatch.setattr(image_categorizer, "CompareEmbeddingClip", _StubCompare, raising=False)
    _StubCompare.winners = {}
    yield _StubCompare
    _StubCompare.winners = {}


def categorizer(source_dir, **kwargs):
    kwargs.setdefault("skip_confirm", True)
    kwargs.setdefault("test", False)
    kwargs.setdefault("categories", ["art", "photograph"])
    return ImageCategorizer(name="unit", source_dir=str(source_dir), **kwargs)


def test_raises_without_weidr(tmp_path, monkeypatch):
    monkeypatch.setattr(image_categorizer, "weidr_imported", False)
    with pytest.raises(Exception, match="Weidr not imported"):
        categorizer(tmp_path)


def test_moves_each_file_into_its_winning_category(tmp_path, weidr_stub):
    (tmp_path / "a.png").write_text("a", encoding="utf-8")
    (tmp_path / "b.png").write_text("b", encoding="utf-8")
    weidr_stub.winners = {"a.png": "art", "b.png": "photograph"}

    categorizer(tmp_path).run()

    assert (tmp_path / "art" / "a.png").exists()
    assert (tmp_path / "photograph" / "b.png").exists()
    assert not (tmp_path / "a.png").exists()


def test_empty_exclude_dirs_still_excludes_category_dirs(tmp_path, weidr_stub):
    """The category loop must not reuse the exclude_dirs loop variable: with no
    exclude_dirs that name is unbound, and the only entries are the categories."""
    instance = categorizer(tmp_path, exclude_dirs=[])

    assert sorted(os.path.basename(d) for d in instance.exclude_dirs) == ["art", "photograph"]


def test_dry_run_moves_nothing(tmp_path, weidr_stub):
    (tmp_path / "a.png").write_text("a", encoding="utf-8")
    weidr_stub.winners = {"a.png": "art"}

    categorizer(tmp_path, test=True).run()

    assert (tmp_path / "a.png").exists()
    assert not (tmp_path / "art").exists()


def test_already_categorized_files_are_not_rescanned(tmp_path, weidr_stub):
    """A category output folder is excluded, so a second run is a no-op."""
    (tmp_path / "a.png").write_text("a", encoding="utf-8")
    weidr_stub.winners = {"a.png": "art"}

    instance = categorizer(tmp_path)
    instance.run()
    assert (tmp_path / "art" / "a.png").exists()

    second = categorizer(tmp_path)
    assert list(second._get_files()) == []


def test_category_exclusion_does_not_match_on_name_prefix(tmp_path, weidr_stub):
    """`art` must not exclude a sibling directory named `artwork`."""
    (tmp_path / "artwork").mkdir()
    (tmp_path / "artwork" / "keep.png").write_text("k", encoding="utf-8")

    instance = categorizer(tmp_path)
    found = [str(p) for p in instance._get_files()]

    assert any("artwork" in f for f in found), found


def test_non_recursive_scans_the_source_directory(tmp_path, weidr_stub):
    """A source dir containing subdirectories must still yield its own files."""
    (tmp_path / "top.png").write_text("t", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.png").write_text("d", encoding="utf-8")

    instance = categorizer(tmp_path, recursive=False)
    found = [str(p) for p in instance._get_files()]

    assert any("top.png" in f for f in found), found
    assert not any("deep.png" in f for f in found), found


def test_recursive_scans_subdirectories(tmp_path, weidr_stub):
    (tmp_path / "top.png").write_text("t", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.png").write_text("d", encoding="utf-8")

    instance = categorizer(tmp_path, recursive=True)
    found = [str(p) for p in instance._get_files()]

    assert any("top.png" in f for f in found), found
    assert any("deep.png" in f for f in found), found


def test_each_file_is_yielded_once_across_multiple_file_types(tmp_path, weidr_stub):
    (tmp_path / "a.png").write_text("a", encoding="utf-8")
    (tmp_path / "b.jpg").write_text("b", encoding="utf-8")

    instance = categorizer(tmp_path, file_types=[".png", ".jpg", ".jpeg"])
    found = [str(p) for p in instance._get_files()]

    assert len(found) == len(set(found)) == 2, found


def test_tied_scores_move_the_file_once(tmp_path, weidr_stub):
    """Every category scores 0.0, so all tie at the max."""
    (tmp_path / "a.png").write_text("a", encoding="utf-8")
    weidr_stub.winners = {}

    instance = categorizer(tmp_path)
    instance.run()

    placed = [c for c, files in instance.segregation_map.items() if files]
    assert len(placed) == 1, instance.segregation_map


def test_no_images_is_not_an_error(tmp_path, weidr_stub):
    categorizer(tmp_path).run()
    assert not (tmp_path / "art").exists()


def test_invalid_exclude_dir_raises(tmp_path, weidr_stub):
    with pytest.raises(Exception, match="Invalid exclude directory"):
        categorizer(tmp_path, exclude_dirs=["does_not_exist"])


def test_no_categories_raises(tmp_path, weidr_stub):
    with pytest.raises(Exception, match="No categories provided"):
        categorizer(tmp_path, categories=[])
