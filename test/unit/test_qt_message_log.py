"""ui/qt_message_log.py: Qt's messages reach Python logging."""

import logging

import pytest
from PySide6 import QtCore

from ui import qt_message_log


class _Context:
    def __init__(self, category):
        self.category = category


@pytest.mark.parametrize("mode, level", [
    (QtCore.QtMsgType.QtDebugMsg, logging.DEBUG),
    (QtCore.QtMsgType.QtWarningMsg, logging.WARNING),
    (QtCore.QtMsgType.QtCriticalMsg, logging.ERROR),
])
def test_messages_are_logged_at_the_matching_level(caplog, mode, level):
    with caplog.at_level(logging.DEBUG, logger=qt_message_log.logger.name):
        qt_message_log._handle_qt_message(mode, _Context("qt.svg"), "bad path")
    record = caplog.records[-1]
    assert record.levelno == level
    assert record.getMessage() == "qt.svg: bad path"


def test_the_default_category_is_left_out(caplog):
    with caplog.at_level(logging.DEBUG, logger=qt_message_log.logger.name):
        qt_message_log._handle_qt_message(QtCore.QtMsgType.QtWarningMsg, _Context("default"), "plain")
    assert caplog.records[-1].getMessage() == "plain"


def test_installed_once_and_routes_qt_warnings(monkeypatch):
    previous = []

    def install(handler):
        previous.append(QtCore.qInstallMessageHandler(handler))

    monkeypatch.setattr(qt_message_log, "qInstallMessageHandler", install)
    monkeypatch.setattr(qt_message_log, "_installed", False)
    try:
        qt_message_log.install_qt_message_handler()
        qt_message_log.install_qt_message_handler()
        assert len(previous) == 1
        assert qt_message_log.qt_message_reaches_logging()
    finally:
        # Hands Qt back the handler it had, e.g. pytest-qt's capture.
        QtCore.qInstallMessageHandler(previous[0] if previous else None)
