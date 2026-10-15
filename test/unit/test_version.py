"""refacdir/utils/version.py: the version, build info and source state a build records."""

import json

import pytest

from refacdir.utils import app_paths, version


@pytest.fixture
def resources(monkeypatch, tmp_path):
    """A resource root holding VERSION 1.2.3 and no build info."""
    monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(tmp_path))
    (tmp_path / version.VERSION_FILE).write_text("1.2.3\n", encoding="utf-8")
    return tmp_path


def test_checkout_version_is_the_repo_version_file():
    with open(app_paths.resource_path(version.VERSION_FILE), "r", encoding="utf-8") as f:
        assert version.app_version() == f.read().strip()


def test_checkout_has_no_build_info(resources):
    assert version.app_version() == "1.2.3"
    assert version.build_info() == {}
    assert version.describe() == "RefacDir 1.2.3 (source checkout)"


def test_describe_names_build_commit_and_packages(resources):
    (resources / version.BUILD_INFO_FILE).write_text(json.dumps({
        "version": "1.2.3", "build_id": "20261015-120000", "with_oqs": True, "python": "3.11.13",
        "packages": {"PySide6": "6.11.2", "Nuitka": "4.2.2"},
        "source": {"commit": "a" * 40, "changes": "x"},
    }), encoding="utf-8")
    line = version.describe()
    assert line.startswith("RefacDir 1.2.3, build 20261015-120000 from aaaaaaaaaa with uncommitted changes")
    assert "with OQS" in line
    assert "Python 3.11.13" in line
    assert "Nuitka 4.2.2, PySide6 6.11.2" in line


def test_describe_survives_a_missing_version_file(resources):
    (resources / version.VERSION_FILE).unlink()
    assert "version unreadable" in version.describe()


def test_describe_survives_unreadable_build_info(resources):
    (resources / version.BUILD_INFO_FILE).write_text("{not json", encoding="utf-8")
    assert "build info unreadable" in version.describe()


def test_read_git_commit_follows_a_branch_ref(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git / "refs" / "heads" / "master").write_text("c" * 40 + "\n", encoding="utf-8")
    assert version.read_git_commit(str(tmp_path)) == "c" * 40


def test_read_git_commit_falls_back_to_packed_refs(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git / "packed-refs").write_text(f"# pack-refs\n{'d' * 40} refs/heads/master\n", encoding="utf-8")
    assert version.read_git_commit(str(tmp_path)) == "d" * 40


def test_read_git_commit_reads_a_detached_head(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("e" * 40 + "\n", encoding="utf-8")
    assert version.read_git_commit(str(tmp_path)) == "e" * 40


def test_read_git_commit_without_a_checkout(tmp_path):
    assert version.read_git_commit(str(tmp_path)) == ""


def _fake_git(diff):
    def run_git(repo, *args):
        if args == ("rev-parse", "HEAD"):
            return "a" * 40 + "\n"
        if args == ("rev-parse", "HEAD^{tree}"):
            return "t" * 40 + "\n"
        if args[:2] == ("diff", "HEAD"):
            return diff
        return None
    return run_git


def test_source_state_of_a_clean_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "run_git", _fake_git(diff=""))
    assert version.source_state(str(tmp_path)) == {"commit": "a" * 40, "tree": "t" * 40, "changes": ""}


def test_source_state_fingerprints_uncommitted_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "run_git", _fake_git(diff="diff --git a/x b/x\n"))
    first = version.source_state(str(tmp_path))["changes"]
    monkeypatch.setattr(version, "run_git", _fake_git(diff="diff --git a/y b/y\n"))
    second = version.source_state(str(tmp_path))["changes"]
    assert first and second and first != second


def test_source_state_without_git(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "run_git", lambda repo, *args: None)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("f" * 40 + "\n", encoding="utf-8")
    assert version.source_state(str(tmp_path)) == {"commit": "f" * 40, "tree": "", "changes": None}


# source_drift

def _built_from(resources, checkout, commit="b" * 40, tree="t" * 40, changes=""):
    (resources / version.BUILD_INFO_FILE).write_text(json.dumps({
        "version": "1.2.3",
        "source": {"repo": str(checkout), "commit": commit, "tree": tree, "changes": changes},
    }), encoding="utf-8")


@pytest.fixture
def checkout(tmp_path):
    path = tmp_path / "checkout"
    (path / ".git").mkdir(parents=True)
    return path


def _checkout_at(monkeypatch, commit, tree="t" * 40, changes="", counts=None, has_commit=True):
    """Stub the checkout's state; *counts* maps a rev-list range to its count."""
    monkeypatch.setattr(version, "source_state",
                        lambda repo: {"commit": commit, "tree": tree, "changes": changes})

    def run_git(repo, *args):
        if args[:2] == ("rev-list", "--count"):
            return None if counts is None else f"{counts[args[2]]}\n"
        if args[:2] == ("cat-file", "-e"):
            return "" if has_commit else None
        return None

    monkeypatch.setattr(version, "run_git", run_git)


def test_source_drift_is_none_in_a_checkout(resources):
    assert version.source_drift() is None


def test_source_drift_matches_the_same_commit(resources, checkout, monkeypatch):
    _built_from(resources, checkout)
    _checkout_at(monkeypatch, "b" * 40)
    drifted, message = version.source_drift()
    assert drifted is False
    assert "matches" in message


def test_source_drift_notices_changed_uncommitted_work(resources, checkout, monkeypatch):
    _built_from(resources, checkout)
    _checkout_at(monkeypatch, "b" * 40, changes="f" * 40)
    drifted, message = version.source_drift()
    assert drifted is True
    assert "uncommitted" in message


def test_source_drift_counts_commits_both_ways(resources, checkout, monkeypatch):
    _built_from(resources, checkout)
    _checkout_at(monkeypatch, "c" * 40, tree="u" * 40,
                 counts={f"{'b' * 40}..{'c' * 40}": 3, f"{'c' * 40}..{'b' * 40}": 1})
    drifted, message = version.source_drift()
    assert drifted is True
    assert "3 commit(s) not in this build" in message
    assert "lacks 1 commit(s)" in message


def test_source_drift_accepts_a_rewritten_commit_with_the_same_files(resources, checkout, monkeypatch):
    _built_from(resources, checkout)
    _checkout_at(monkeypatch, "e" * 40, has_commit=False)
    drifted, message = version.source_drift()
    assert drifted is False
    assert "same files" in message


def test_source_drift_names_a_commit_missing_from_the_history(resources, checkout, monkeypatch):
    _built_from(resources, checkout)
    _checkout_at(monkeypatch, "e" * 40, tree="u" * 40, has_commit=False)
    drifted, message = version.source_drift()
    assert drifted is True
    assert "not in its history" in message


def test_source_drift_reports_a_missing_checkout(resources, tmp_path):
    _built_from(resources, tmp_path / "gone")
    drifted, message = version.source_drift()
    assert drifted is False
    assert "not found" in message
