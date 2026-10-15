"""Routes Qt's own messages (warnings, debug output) through Python logging.

Install it before creating the QApplication. Qt's default handler writes byte
strings to the C-level stderr. A Windows build made with
``--windows-console-mode=attach`` sets that stream to wide-character mode,
and the C runtime then aborts the process (``0xc0000409``) at the first Qt
warning, however harmless.
"""

import logging

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from refacdir.utils.logger import setup_logger

logger = setup_logger("qt")

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

_installed = False


def _handle_qt_message(mode, context, message) -> None:
    category = getattr(context, "category", None)
    prefix = f"{category}: " if category and category != "default" else ""
    logger.log(_LEVELS.get(mode, logging.WARNING), f"{prefix}{message}")


def install_qt_message_handler() -> None:
    """Install the handler once per process; later calls do nothing."""
    global _installed
    if not _installed:
        qInstallMessageHandler(_handle_qt_message)
        _installed = True


_PROBE_MESSAGE = "refacdir smoke test: Qt message routing"


def qt_message_reaches_logging() -> bool:
    """Emit a Qt warning and report whether this module's handler logged it,
    for the smoke test. In an affected build without the handler, the
    process aborts here instead."""
    from PySide6.QtCore import qWarning

    seen = []

    class _Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    collector = _Collect()
    logger.addHandler(collector)
    try:
        qWarning(_PROBE_MESSAGE)
    finally:
        logger.removeHandler(collector)
    return any(_PROBE_MESSAGE in message for message in seen)
