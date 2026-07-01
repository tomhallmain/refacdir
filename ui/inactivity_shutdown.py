"""
Shut down the application after a period without user input.

Qt does not expose a system idle-time API. This module installs an
application-wide event filter and restarts a single-shot timer whenever
keyboard, mouse, wheel, touch, or shortcut activity is observed.
"""

from PySide6.QtCore import QObject, QTimer, QEvent
from PySide6.QtWidgets import QApplication

from refacdir.utils.logger import setup_logger

logger = setup_logger("inactivity_shutdown")

DEFAULT_INACTIVITY_TIMEOUT_MINUTES = 30
DEFAULT_INACTIVITY_TIMEOUT_MS = DEFAULT_INACTIVITY_TIMEOUT_MINUTES * 60 * 1000

_ACTIVITY_EVENTS = frozenset({
    QEvent.Type.MouseMove,
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.Wheel,
    QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease,
    QEvent.Type.TouchBegin,
    QEvent.Type.TouchUpdate,
    QEvent.Type.TouchEnd,
    QEvent.Type.Shortcut,
    QEvent.Type.TabletPress,
    QEvent.Type.TabletRelease,
    QEvent.Type.TabletMove,
})


class InactivityShutdown(QObject):
    """Close the main window after ``timeout_ms`` without user activity."""

    def __init__(self, window, timeout_ms: int = DEFAULT_INACTIVITY_TIMEOUT_MS):
        super().__init__(window)
        self._window = window
        self._timeout_ms = timeout_ms
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        QApplication.instance().installEventFilter(self)
        self.reset_timer()
        logger.info(
            "Inactivity shutdown enabled (%s minute timeout)",
            timeout_ms // 60_000,
        )

    def pause(self):
        """Stop the idle timer while the app is doing work without user input."""
        self._paused = True
        self._timer.stop()

    def resume(self):
        """Restart the idle timer after paused work completes."""
        self._paused = False
        self.reset_timer()

    def set_timeout_minutes(self, minutes: int):
        """Update the idle timeout and restart the timer if active."""
        if minutes < 1:
            raise ValueError("Inactivity timeout must be at least 1 minute")
        self._timeout_ms = minutes * 60_000
        if not self._paused:
            self.reset_timer()

    def reset_timer(self):
        if self._paused:
            return
        self._timer.start(self._timeout_ms)

    def eventFilter(self, watched, event):
        if not self._paused and event.type() in _ACTIVITY_EVENTS:
            self.reset_timer()
        return super().eventFilter(watched, event)

    def _on_timeout(self):
        minutes = self._timeout_ms // 60_000
        logger.info(
            "No user activity for %s minute(s); shutting down application",
            minutes,
        )
        self._window.close()
