"""ui/log_panel.py: the main window's live log view. Panel tests attach to a
private logger, so the root logger's handlers are untouched."""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from refacdir.utils.translations import _
from test.ui.conftest import destroy_widget
from ui.log_panel import LogPanel, QueueingLogHandler

pytestmark = pytest.mark.ui


@pytest.fixture
def source_logger(request):
    log = logging.getLogger(f"test_log_panel.{request.node.name}")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    yield log
    for handler in list(log.handlers):
        log.removeHandler(handler)


@pytest.fixture
def panel(qtbot, source_logger):
    widget = LogPanel()
    widget.attach(source_logger)
    yield widget
    widget.detach()
    destroy_widget(widget)


def _lines(panel):
    return panel.view.toPlainText().splitlines()


def test_handler_drops_the_app_prefix_and_keeps_order():
    handler = QueueingLogHandler()
    app_log = logging.getLogger("refacdir.batch")
    for message in ("first", "second"):
        handler.handle(app_log.makeRecord(app_log.name, logging.INFO, __file__, 1, message, None, None))
    lines = handler.drain()
    assert [line.split(" ", 1)[1] for line in lines] == ["INFO    batch: first", "INFO    batch: second"]
    assert handler.drain() == []


def test_handler_keeps_only_the_newest_lines_when_not_drained():
    handler = QueueingLogHandler(max_pending=3)
    log = logging.getLogger("other")
    for i in range(5):
        handler.handle(log.makeRecord(log.name, logging.INFO, __file__, 1, f"m{i}", None, None))
    assert [line.rsplit(" ", 1)[1] for line in handler.drain()] == ["m2", "m3", "m4"]


def test_handler_includes_the_traceback():
    handler = QueueingLogHandler()
    log = logging.getLogger("other")
    try:
        raise ValueError("bad value")
    except ValueError:
        record = log.makeRecord(log.name, logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    handler.handle(record)
    (line,) = handler.drain()
    assert "failed" in line and "ValueError: bad value" in line


def test_records_from_a_worker_thread_appear_after_a_flush(panel, source_logger):
    worker = threading.Thread(target=source_logger.info, args=("from the batch thread",))
    worker.start()
    worker.join(5)
    assert _lines(panel) == []
    panel.flush()
    assert _lines(panel)[-1].endswith("from the batch thread")


def test_the_timer_flushes_on_its_own(qtbot, panel, source_logger):
    source_logger.warning("eventually shown")
    qtbot.waitUntil(lambda: any("eventually shown" in line for line in _lines(panel)), timeout=3000)


def test_level_filter(panel, source_logger):
    source_logger.debug("hidden at info")
    source_logger.info("shown at info")
    panel.set_level(logging.DEBUG)
    source_logger.debug("shown at debug")
    panel.flush()
    text = panel.view.toPlainText()
    assert "hidden at info" not in text
    assert "shown at info" in text
    assert "shown at debug" in text


def test_choosing_a_level_reports_it_but_restoring_one_does_not(panel):
    chosen = []
    panel.level_changed.connect(chosen.append)
    panel.set_level(logging.WARNING)
    assert chosen == []
    assert panel.level() == logging.WARNING
    panel.level_combo.setCurrentIndex(LogPanel.LEVELS.index(logging.ERROR))
    assert chosen == [logging.ERROR]
    assert panel.level() == logging.ERROR


def test_an_unknown_stored_level_falls_back_to_info(panel):
    panel.set_level(5)
    assert panel.level() == logging.INFO


def test_clear_drops_shown_and_pending_lines(panel, source_logger):
    source_logger.info("shown")
    panel.flush()
    source_logger.info("pending")
    panel.clear()
    panel.flush()
    assert _lines(panel) == []


def test_detach_stops_collecting(panel, source_logger):
    panel.detach()
    assert source_logger.handlers == []
    source_logger.info("after detach")
    panel.flush()
    assert _lines(panel) == []


def test_header_text_is_translated(panel):
    assert panel.clear_btn.text() == _("Clear")
    assert panel.level_combo.itemText(LogPanel.LEVELS.index(logging.INFO)) == _("Info")


def test_main_window_shows_the_log_beside_the_file_handler(main_window):
    root = logging.getLogger()
    assert main_window.log_panel._handler in root.handlers
    # The file handler refacdir/utils/logger.py installs is still there.
    assert any(isinstance(h, logging.FileHandler) for h in root.handlers)

    logging.getLogger("refacdir.ui").info("visible in the window")
    main_window.log_panel.flush()
    assert any("ui: visible in the window" in line for line in _lines(main_window.log_panel))


def test_closing_the_main_window_detaches_the_log(main_window):
    handler = main_window.log_panel._handler
    main_window.close()
    assert handler not in logging.getLogger().handlers


def test_the_chosen_level_is_stored_with_the_operation_settings(main_window, monkeypatch):
    import app_qt

    stored = {}
    monkeypatch.setattr(app_qt.app_info_cache, "set_operation_settings", stored.update)
    monkeypatch.setattr(app_qt.app_info_cache, "store", lambda: None)
    main_window.log_panel.set_level(logging.DEBUG)
    main_window.store_ui_settings()
    assert stored["log_panel_level"] == logging.DEBUG


def test_view_keeps_the_configured_number_of_lines(panel):
    from ui import log_panel

    assert panel.view.maximumBlockCount() == log_panel.MAX_VIEW_LINES == 2500


def test_view_uses_the_preferred_monospace_faces(panel):
    from ui import log_panel

    font = panel.view.font()
    assert list(font.families()) == list(log_panel.LOG_FONT_FAMILIES)
    assert font.pointSize() == log_panel.LOG_FONT_POINT_SIZE
