from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont

from refacdir.utils.logger import setup_logger

# Set up logger for toast notifications
logger = setup_logger('toast')

class ToastNotification(QWidget):
    """Custom toast notification widget"""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setFont(QFont("Helvetica", 10))
        self.label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.7);
                color: white;
                padding: 10px;
                border-radius: 5px;
            }
        """)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        
        # Hide initially
        self.hide()
        
    def show_message(self, message: str, duration: int = 3000):
        """Show a toast message for the specified duration"""
        logger.info(f"Showing toast message: {message}")
        self.label.setText(message)
        self.adjustSize()
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            screen.height() - self.height() - 50
        )
        
        # Show and start timer
        self.show()
        QTimer.singleShot(duration, self.hide)