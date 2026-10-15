"""A live view of the app's log in the main window.

``LogPanel.attach`` adds one more handler to the root logger, beside the file
and console handlers ``refacdir/utils/logger.py`` installs; those are left as
they are, so the log file is written exactly as without the panel.

Records arrive on any thread (a batch runs on a background thread). The
handler only formats each record into a bounded queue; a timer on the GUI
thread moves queued lines into the view in batches. That keeps a busy run from
flooding the event loop with one update per record, and a record logged after
the window has gone touches no Qt object.
"""

import logging
from collections import deque

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import _

# Configures the root logger's file and console handlers before attach() can
# add a handler there: _configure_root_logger skips its setup when the root
# logger already has any handler.
logger = setup_logger("log_panel")

# Lines the view keeps; older ones are dropped from the top.
MAX_VIEW_LINES = 2500
# Lines held between two flushes; when the GUI thread falls behind, the
# oldest are dropped rather than growing without bound. More than the view
# keeps would only be dropped there.
MAX_PENDING_LINES = MAX_VIEW_LINES
FLUSH_INTERVAL_MS = 200

# Monospace faces tried in order: Windows, macOS, then Linux. Qt falls back
# to its own monospace pick when none is installed.
LOG_FONT_FAMILIES = (
    "Cascadia Mono", "Consolas",
    "SF Mono", "Menlo",
    "DejaVu Sans Mono", "Liberation Mono",
)
LOG_FONT_POINT_SIZE = 10

_APP_LOGGER_PREFIX = "refacdir."


class _PanelFormatter(logging.Formatter):
    """``12:34:56 INFO    batch: message``, with the app's logger prefix dropped."""

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if name.startswith(_APP_LOGGER_PREFIX):
            name = name[len(_APP_LOGGER_PREFIX):]
        text = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {name}: {record.getMessage()}"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return text


def _log_font() -> QFont:
    font = QFont()
    font.setFamilies(list(LOG_FONT_FAMILIES))
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(LOG_FONT_POINT_SIZE)
    return font


class QueueingLogHandler(logging.Handler):
    """Formats records from any thread into a bounded queue for the GUI thread to drain."""

    def __init__(self, max_pending: int = MAX_PENDING_LINES):
        super().__init__()
        self.setFormatter(_PanelFormatter())
        self._pending = deque(maxlen=max_pending)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._pending.append(self.format(record))
        except Exception:
            self.handleError(record)

    def drain(self) -> list:
        """Remove and return the queued lines, oldest first."""
        lines = []
        while True:
            try:
                lines.append(self._pending.popleft())
            except IndexError:
                return lines


class LogPanel(QFrame):
    """Log view with a level filter and a Clear button."""

    # The chosen level, for the window to store with its other settings.
    level_changed = Signal(int)

    LEVELS = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logFrame")
        self.setFrameStyle(QFrame.StyledPanel)
        self._handler = QueueingLogHandler()
        self._handler.setLevel(logging.INFO)
        self._attached_to = None

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(_("Log"))
        title.setFont(QFont("Helvetica", 12, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel(_("Level")))
        self.level_combo = QComboBox()
        level_names = {
            logging.DEBUG: _("Debug"),
            logging.INFO: _("Info"),
            logging.WARNING: _("Warning"),
            logging.ERROR: _("Error"),
        }
        for level in self.LEVELS:
            self.level_combo.addItem(level_names[level], level)
        self.level_combo.setCurrentIndex(self.LEVELS.index(logging.INFO))
        self.level_combo.currentIndexChanged.connect(self._on_level_selected)
        header.addWidget(self.level_combo)
        self.clear_btn = QPushButton(_("Clear"))
        self.clear_btn.clicked.connect(self.clear)
        header.addWidget(self.clear_btn)
        layout.addLayout(header)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(MAX_VIEW_LINES)
        self.view.setFont(_log_font())
        layout.addWidget(self.view)

        self._timer = QTimer(self)
        self._timer.setInterval(FLUSH_INTERVAL_MS)
        self._timer.timeout.connect(self.flush)

    def attach(self, target: logging.Logger = None) -> None:
        """Start showing records that reach *target* (the root logger by default)."""
        if self._attached_to is not None:
            return
        target = target if target is not None else logging.getLogger()
        target.addHandler(self._handler)
        self._attached_to = target
        self._timer.start()

    def detach(self) -> None:
        """Stop showing records; the handler leaves the logger it was added to."""
        if self._attached_to is None:
            return
        self._attached_to.removeHandler(self._handler)
        self._attached_to = None
        self._timer.stop()

    def level(self) -> int:
        return self._handler.level

    def set_level(self, level: int) -> None:
        """Show records at *level* and above; an unknown level falls back to INFO."""
        if level not in self.LEVELS:
            level = logging.INFO
        # Restoring a stored level is not a new choice to store.
        self.level_combo.blockSignals(True)
        self.level_combo.setCurrentIndex(self.LEVELS.index(level))
        self.level_combo.blockSignals(False)
        self._handler.setLevel(level)

    def _on_level_selected(self, index: int) -> None:
        level = self.level_combo.itemData(index)
        self._handler.setLevel(level)
        self.level_changed.emit(level)

    def clear(self) -> None:
        self._handler.drain()
        self.view.clear()

    def flush(self) -> None:
        """Move queued lines into the view. Keeps following the end only when
        the view was already scrolled to it, so reading earlier lines is not
        interrupted."""
        lines = self._handler.drain()
        if not lines:
            return
        scrollbar = self.view.verticalScrollBar()
        at_end = scrollbar.value() >= scrollbar.maximum()
        self.view.appendPlainText("\n".join(lines))
        if at_end:
            scrollbar.setValue(scrollbar.maximum())
