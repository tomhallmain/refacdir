"""Qt-free implementation of the AppActions contract.

Most of AppActions is a presentation port: the batch layer calls it to tell the
user something or to move a progress bar. Those have no meaning without a GUI,
so here they become logging or no-ops.

The rest is not presentation. ``review_duplicates`` asks a question and waits
for the answer; ``get_batch_args`` and ``refresh_configs`` read and reshape real
state. Stubbing those silently would let a caller believe work happened when it
did not, so each is handled explicitly:

- ``review_duplicates`` returns the declining answer, the same value the Qt
  dialog yields when it is dismissed. A caller that would otherwise block on a
  person gets "no" rather than a wait that never ends.
- The domain actions must be supplied by the caller. An unsupplied one raises
  when called, naming itself, rather than returning a plausible None.

This module must not import PySide6, directly or transitively. AppActions
itself is safe to import: it pulls in nothing but ``typing``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from refacdir.utils.app_actions import AppActions
from refacdir.utils.logger import setup_logger

logger = setup_logger("headless_app_actions")


class HeadlessActionUnavailable(RuntimeError):
    """A domain action was called that the caller never supplied."""


# Message-bearing: the text is the whole point, so it is logged rather than
# dropped.
MESSAGE_ACTIONS = ("toast", "alert", "progress_text")

# Display-only: nothing to do without a screen, and nothing a caller observes.
NOOP_ACTIONS = ("progress_bar_update", "progress_bar_reset")

# Queried for a value that must not be invented. The value here is what the Qt
# side yields when the user dismisses the dialog, and DuplicateRemover already
# treats any action other than remove_all/remove_selected as cancelled -- so a
# duplicate scan still runs and reports, and removes nothing.
NEUTRAL_RETURN_ACTIONS: Dict[str, Any] = {
    "review_duplicates": {"action": "cancel", "files": []},
}

# Not presentation: these read or reshape real state and must come from the
# caller. ``get_batch_args`` hands back the session's own BatchArgs;
# ``refresh_configs`` re-reads the configs directory.
DOMAIN_ACTIONS = ("get_batch_args", "refresh_configs")


def _message_stub(name: str) -> Callable[..., Any]:
    def _log_message(*args, **kwargs):
        if name == "alert":
            title = args[0] if args else kwargs.get("title", "")
            body = args[1] if len(args) > 1 else kwargs.get("message", "")
            logger.warning('Alert - Title: "%s" Message: %s', title, body)
            return None
        text = args[0] if args else kwargs.get("message", "")
        logger.info("%s: %s", name, text)
        return None
    return _log_message


def _noop_stub(name: str) -> Callable[..., Any]:
    def _noop(*_args, **_kwargs):
        logger.debug("no-op display action: %s", name)
        return None
    return _noop


def _neutral_stub(name: str, value: Any) -> Callable[..., Any]:
    def _neutral(*_args, **_kwargs):
        logger.debug("neutral return for %s: %r", name, value)
        # A fresh copy per call: the stored value is mutable, and a caller that
        # edited what it got back would change every later answer.
        return copy.deepcopy(value)
    return _neutral


def _unavailable_stub(name: str) -> Callable[..., Any]:
    def _unavailable(*_args, **_kwargs):
        raise HeadlessActionUnavailable(
            f"Action '{name}' is not a display operation and has no headless "
            f"default. Pass it to build_headless_app_actions()."
        )
    return _unavailable


def build_headless_app_actions(
    domain_actions: Optional[Dict[str, Callable[..., Any]]] = None,
) -> AppActions:
    """Build an AppActions usable with no QApplication and no display.

    *domain_actions* supplies the entries in DOMAIN_ACTIONS. Anything omitted
    raises HeadlessActionUnavailable when called -- omitting one is only a
    problem for a caller that actually reaches it.

    Passing a name outside the known contract is rejected: it would otherwise
    sit unused in the dict and read as wired up.
    """
    supplied = dict(domain_actions or {})

    known = (
        set(MESSAGE_ACTIONS)
        | set(NOOP_ACTIONS)
        | set(NEUTRAL_RETURN_ACTIONS)
        | set(DOMAIN_ACTIONS)
    )
    unknown = sorted(set(supplied) - known)
    if unknown:
        raise ValueError(
            f"Unknown action names passed to build_headless_app_actions: {unknown}"
        )

    actions: Dict[str, Callable[..., Any]] = {}
    for name in MESSAGE_ACTIONS:
        actions[name] = _message_stub(name)
    for name in NOOP_ACTIONS:
        actions[name] = _noop_stub(name)
    for name, value in NEUTRAL_RETURN_ACTIONS.items():
        actions[name] = _neutral_stub(name, value)
    for name in DOMAIN_ACTIONS:
        actions[name] = supplied.get(name) or _unavailable_stub(name)

    # Overriding a display action is allowed but not the common case; it lets a
    # caller capture toasts or alerts for assertions.
    for name, func in supplied.items():
        actions[name] = func

    return AppActions(actions)


def missing_domain_actions(app_actions: AppActions) -> list:
    """Domain actions that would raise if called. Useful as a pre-flight check."""
    missing = []
    for name in DOMAIN_ACTIONS:
        func = app_actions._actions.get(name)
        if getattr(func, "__name__", "") == "_unavailable":
            missing.append(name)
    return missing
