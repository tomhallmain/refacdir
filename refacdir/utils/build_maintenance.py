"""Startup housekeeping that only a compiled build needs: removing older
builds' unpack folders and comparing the build with its source checkout.
Both can be slow (a large rmtree, several git calls), so they run on a
daemon thread."""

import threading
from typing import Callable, Optional

from refacdir.utils import app_paths
from refacdir.utils.logger import setup_logger

logger = setup_logger("build_maintenance")


def run_build_maintenance(unpack_prefix: str, on_drift: Optional[Callable[[str], None]] = None) -> None:
    """Remove stale unpack folders of the *unpack_prefix* kind, then log how
    the build compares with its checkout and pass the message to *on_drift*
    when the two differ. Logs instead of raising."""
    from refacdir.utils.unpack_cleanup import remove_stale_unpack_dirs
    from refacdir.utils.version import source_drift

    try:
        remove_stale_unpack_dirs(unpack_prefix)
    except Exception:
        logger.exception("Cleaning up old build folders failed")
    try:
        drift = source_drift()
    except Exception:
        logger.exception("Comparing this build with its source checkout failed")
        return
    if drift is None:
        return
    drifted, message = drift
    if not drifted:
        logger.info(message)
        return
    logger.warning(message)
    if on_drift is not None:
        try:
            on_drift(message)
        except Exception:
            logger.exception("Reporting the source drift failed")


def start_build_maintenance(unpack_prefix: str,
                            on_drift: Optional[Callable[[str], None]] = None) -> Optional[threading.Thread]:
    """Run run_build_maintenance on a daemon thread in a build; returns the
    thread, or None in a source checkout. *on_drift* is called on that thread."""
    if not app_paths.IS_BUILD:
        return None
    thread = threading.Thread(
        target=run_build_maintenance, args=(unpack_prefix, on_drift), daemon=True, name="build-maintenance",
    )
    thread.start()
    return thread
