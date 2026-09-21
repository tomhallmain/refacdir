"""Unit tests for the Qt-free AppActions build."""

import pytest

from refacdir.utils.app_actions import AppActions
from refacdir.utils.headless_app_actions import (
    DOMAIN_ACTIONS,
    HeadlessActionUnavailable,
    build_headless_app_actions,
    missing_domain_actions,
)


def test_builds_a_complete_app_actions_with_no_domain_actions():
    """AppActions rejects an incomplete dict, so building at all proves the
    partition covers every required action."""
    actions = build_headless_app_actions()
    assert isinstance(actions, AppActions)
    assert AppActions.REQUIRED_ACTIONS <= set(actions._actions)


def test_display_actions_are_callable_and_return_none():
    actions = build_headless_app_actions()
    assert actions.toast("hello") is None
    assert actions.alert("title", "body", "info") is None
    assert actions.progress_text("working") is None
    assert actions.progress_bar_update(None, 0.5) is None
    assert actions.progress_bar_reset() is None


def test_review_duplicates_declines_instead_of_blocking():
    """The whole point: a caller that would wait on a person gets 'no'."""
    actions = build_headless_app_actions()
    decision = actions.review_duplicates({"total_duplicate_files": 3})
    assert decision["action"] == "cancel"
    assert decision["files"] == []


def test_review_duplicates_answer_is_not_shared_between_calls():
    """A caller that edits what it got back must not change later answers."""
    actions = build_headless_app_actions()
    first = actions.review_duplicates({})
    first["files"].append("mutated")
    first["action"] = "remove_all"

    second = actions.review_duplicates({})
    assert second["action"] == "cancel"
    assert second["files"] == []


@pytest.mark.parametrize("name", DOMAIN_ACTIONS)
def test_unsupplied_domain_action_raises_naming_itself(name):
    actions = build_headless_app_actions()
    with pytest.raises(HeadlessActionUnavailable, match=name):
        getattr(actions, name)()


def test_supplied_domain_action_is_used():
    sentinel = object()
    actions = build_headless_app_actions({"get_batch_args": lambda: sentinel})
    assert actions.get_batch_args() is sentinel


def test_missing_domain_actions_reports_only_the_unsupplied():
    actions = build_headless_app_actions({"get_batch_args": lambda: None})
    assert missing_domain_actions(actions) == ["refresh_configs"]

    complete = build_headless_app_actions(
        {"get_batch_args": lambda: None, "refresh_configs": lambda: None}
    )
    assert missing_domain_actions(complete) == []


def test_unknown_action_name_is_rejected():
    """An unknown name would sit unused in the dict and read as wired up."""
    with pytest.raises(ValueError, match="not_an_action"):
        build_headless_app_actions({"not_an_action": lambda: None})


def test_display_action_can_be_overridden_for_capture():
    captured = []
    actions = build_headless_app_actions({"toast": captured.append})
    actions.toast("recorded")
    assert captured == ["recorded"]


def test_module_imports_no_qt():
    """Must stay importable with no PySide6 present.

    Asserted against the module's import statements, not sys.modules (other
    tests populate that with Qt) and not the raw source (the docstring names
    PySide6 to state this very rule).
    """
    import ast

    import refacdir.utils.headless_app_actions as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])

    assert "PySide6" not in roots
    assert "ui" not in roots
