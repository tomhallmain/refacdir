"""Ask the person before an action changes files.

With ``app_actions`` the front end asks: a dialog in the GUI, a decline in the
headless build. Without them (the CLI) the question goes to stdin, and is
declined when stdin is not an interactive terminal -- a GUI started without a
console has nothing to read from.
"""

import sys
from typing import Optional

from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import _

logger = setup_logger("confirm")


def confirm_action(
    app_actions,
    title: str,
    message: str,
    details: Optional[str] = None,
    acknowledgement: Optional[str] = None,
) -> bool:
    """Return True if the person agreed.

    *details* is longer supporting text (mappings, locations). *acknowledgement*
    is a statement the person must also accept explicitly: a checkbox that
    enables Yes in the dialog, a second question on the CLI.
    """
    if app_actions is not None:
        return bool(
            app_actions.confirm(title, message, details=details, acknowledgement=acknowledgement)
        )
    if not _stdin_is_interactive():
        logger.warning(f"Declined '{title}': no interactive stdin to ask on")
        return False
    print(title)
    if details:
        print(details)
    if not _ask(message):
        return False
    if acknowledgement is not None and not _ask(acknowledgement):
        return False
    return True


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):  # closed or detached stream
        return False


def _ask(question: str) -> bool:
    return input(_("{0} (y/n): ").format(question)).strip().lower() == "y"
