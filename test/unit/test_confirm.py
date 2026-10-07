"""``confirm_action``: through app_actions, on an interactive stdin, or declined."""

from __future__ import annotations

import io

import pytest

import refacdir.utils.confirm as confirm_module
from refacdir.utils.confirm import confirm_action


class _Actions:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, title, message, details=None, acknowledgement=None):
        self.calls.append((title, message, details, acknowledgement))
        return self.answer


class _Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def tty_answers(monkeypatch):
    """An interactive stdin whose input() calls return *answers* in order."""
    def install(*answers):
        monkeypatch.setattr(confirm_module.sys, "stdin", _Tty())
        remaining = list(answers)
        asked = []

        def fake_input(prompt=""):
            asked.append(prompt)
            return remaining.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        return asked
    return install


@pytest.mark.parametrize("answer", [True, False])
def test_app_actions_answer_is_returned(answer):
    actions = _Actions(answer)
    assert confirm_action(actions, "T", "M", details="D", acknowledgement="A") is answer
    assert actions.calls == [("T", "M", "D", "A")]


def test_interactive_yes(tty_answers):
    tty_answers("y")
    assert confirm_action(None, "T", "Proceed?") is True


def test_interactive_no(tty_answers):
    tty_answers("n")
    assert confirm_action(None, "T", "Proceed?") is False


def test_acknowledgement_is_a_second_question(tty_answers):
    asked = tty_answers("y", "n")
    assert confirm_action(None, "T", "Proceed?", acknowledgement="Checked?") is False
    assert len(asked) == 2

    tty_answers("y", "y")
    assert confirm_action(None, "T", "Proceed?", acknowledgement="Checked?") is True


def test_no_stdin_declines_without_asking(monkeypatch):
    monkeypatch.setattr(confirm_module.sys, "stdin", None)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("input() called"))
    assert confirm_action(None, "T", "Proceed?") is False


def test_non_interactive_stdin_declines_without_asking(monkeypatch):
    monkeypatch.setattr(confirm_module.sys, "stdin", io.StringIO("y\n"))
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("input() called"))
    assert confirm_action(None, "T", "Proceed?") is False
