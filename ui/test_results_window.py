from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QProgressBar, QPushButton
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFileDialog, QMessageBox
from refacdir.utils.utils import Utils
from refacdir.utils.translations import I18N

_ = I18N._


class TestResultsWindow(QMainWindow):
    """Window for displaying test results"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Initialize the test results window UI"""
        self.setWindowTitle(_("Backup System Verification"))
        self.resize(800, 600)
        self.setMinimumSize(600, 400)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)
        
        # Header
        header = QLabel(_("Backup System Test Results"))
        header.setFont(QFont("Helvetica", 12, QFont.Bold))
        layout.addWidget(header)
        
        # Progress section
        progress_frame = QWidget()
        progress_layout = QVBoxLayout(progress_frame)
        
        self.status_label = QLabel(_("Initializing tests..."))
        progress_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(progress_frame)
        
        # Results section
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        layout.addWidget(self.results_text)
        
        # Summary section
        summary_frame = QWidget()
        summary_layout = QHBoxLayout(summary_frame)
        
        self.total_label = QLabel(_("Total Tests: 0"))
        summary_layout.addWidget(self.total_label)
        
        self.passed_label = QLabel(_("Passed: 0"))
        summary_layout.addWidget(self.passed_label)
        
        self.failed_label = QLabel(_("Failed: 0"))
        summary_layout.addWidget(self.failed_label)
        
        layout.addWidget(summary_frame)
        
        # Control buttons
        control_frame = QWidget()
        control_layout = QHBoxLayout(control_frame)
        
        self.close_button = QPushButton(_("Close"))
        self.close_button.clicked.connect(self.close)
        control_layout.addWidget(self.close_button)
        
        self.save_button = QPushButton(_("Save Results"))
        self.save_button.clicked.connect(self.save_results)
        self.save_button.setEnabled(False)
        control_layout.addWidget(self.save_button)
        
        layout.addWidget(control_frame)
        
    def run_tests(self):
        """Run the backup system tests"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(_("Running tests..."))
        
        def run_tests_thread():
            try:
                # TODO: Implement actual test running logic
                pass
            except Exception as e:
                self.alert("Error", str(e), "error")
            finally:
                self.progress_bar.setVisible(False)
                self.save_button.setEnabled(True)
                
        Utils.start_thread(run_tests_thread)
        
    def save_results(self):
        """Save test results to a file"""
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            _("Save Test Results"),
            "",
            _("Text Files (*.txt);;All Files (*)")
        )
        
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    f.write(self.results_text.toPlainText())
            except Exception as e:
                self.alert("Error", str(e), "error")
                
    def alert(self, title: str, message: str, kind: str = "info"):
        """Show an alert dialog"""
        if kind not in ("error", "warning", "info"):
            raise ValueError("Unsupported alert kind.")
            
        QMessageBox.critical(self, title, message) if kind == "error" else \
        QMessageBox.warning(self, title, message) if kind == "warning" else \
        QMessageBox.information(self, title, message)