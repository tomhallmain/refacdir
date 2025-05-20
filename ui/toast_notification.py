from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer


class ToastNotification(QWidget):
    """Custom toast notification widget"""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.Tool)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        
    def show_message(self, message: str, duration: int = 2000):
        self.label.setText(message)
        self.adjustSize()
        
        # Position in top-right corner
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 20, 20)
        
        self.show()
        QTimer.singleShot(duration, self.close)