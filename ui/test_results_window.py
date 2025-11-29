import os
import pytest
import sys
import traceback
from io import StringIO
import threading
from datetime import datetime

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QProgressBar, QPushButton
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox, QMenu, QApplication
from PySide6.QtCore import Signal, QObject, Qt
from refacdir.lib.multi_display import SmartWindow
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import I18N

_ = I18N._

# Set up logger for test results
logger = setup_logger('test_results')

class TestSignals(QObject):
    """Signals for thread-safe UI updates"""
    update_text = Signal(str, str)  # text, tag
    update_status = Signal(str)
    update_progress = Signal(int)
    update_stats = Signal(dict)
    test_complete = Signal()


class TestResultsWindow(SmartWindow):
    """Window for displaying test results"""
    def __init__(self, parent=None):
        # Initialize SmartWindow with automatic positioning
        super().__init__(
            persistent_parent=parent,
            position_parent=parent,
            title=_("Backup System Verification"),
            geometry="800x600",
            offset_x=50,
            offset_y=50
        )
        self.setMinimumSize(600, 400)
        
        self.signals = TestSignals()
        self.setup_ui()
        self.setup_signals()
        self.test_stats = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'start_time': datetime.now()
        }
        
    def setup_signals(self):
        """Connect signals to slots"""
        self.signals.update_text.connect(self.append_text)
        self.signals.update_status.connect(self.status_label.setText)
        self.signals.update_progress.connect(self.update_progress)
        self.signals.update_stats.connect(self.update_stats)
        self.signals.test_complete.connect(self.test_complete)
        
    def setup_ui(self):
        """Initialize the test results window UI"""
        # SmartWindow handles title and size via __init__ parameters
        # Since SmartWindow is a QWidget (not QMainWindow), we use direct layout
        layout = QVBoxLayout(self)
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
        
        # Progress bar with label
        progress_bar_frame = QWidget()
        progress_bar_layout = QHBoxLayout(progress_bar_frame)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_bar_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("0%")
        self.progress_label.setMinimumWidth(50)
        progress_bar_layout.addWidget(self.progress_label)
        
        progress_layout.addWidget(progress_bar_frame)
        layout.addWidget(progress_frame)
        
        # Results section
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont("Consolas", 10))
        self.results_text.setStyleSheet("""
            QTextEdit {
                background-color: #e0e0e0;
            }
        """)
        # Enable text selection and copying
        self.results_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_text.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.results_text)
        
        # Summary section
        summary_frame = QWidget()
        summary_layout = QHBoxLayout(summary_frame)
        
        self.total_label = QLabel(_("Total Tests: 0"))
        summary_layout.addWidget(self.total_label)
        
        self.passed_label = QLabel(_("Passed: 0"))
        self.passed_label.setStyleSheet("color: dark green;")
        summary_layout.addWidget(self.passed_label)
        
        self.failed_label = QLabel(_("Failed: 0"))
        self.failed_label.setStyleSheet("color: red;")
        summary_layout.addWidget(self.failed_label)
        
        self.time_label = QLabel(_("Time: 0:00"))
        summary_layout.addWidget(self.time_label)
        
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
                logger.info("Starting test suite execution")
                # Store original stdout and cwd to restore later
                original_stdout = sys.stdout
                original_cwd = os.getcwd()
                captured_output = StringIO()
                sys.stdout = captured_output
                
                # Run tests - use normalized paths
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                
                # Change to base directory and update Python path
                os.chdir(base_dir)
                if base_dir not in sys.path:
                    sys.path.insert(0, base_dir)
                    
                # Remove any other paths that might interfere
                sys.path = [p for p in sys.path if not p.endswith('simple_image_compare')]
                
                # Use proper directory name for tests
                test_dir = os.path.join(base_dir, "test", "backup")
                if not os.path.exists(test_dir):
                    raise Exception(_("Test directory not found: {0}").format(test_dir))
                
                # Ensure test files directory exists
                test_files_dir = os.path.join(test_dir, "test_files")
                if not os.path.exists(test_files_dir):
                    os.makedirs(test_files_dir)
                
                test_files = [
                    os.path.join(test_dir, "test_hash_manager.py"),
                    os.path.join(test_dir, "test_backup_state.py"),
                    os.path.join(test_dir, "test_backup_source_data.py"),
                    os.path.join(test_dir, "test_backup_transaction.py")
                ]
                
                # Debug info
                logger.info(f"Base directory: {base_dir}")
                logger.info(f"Test directory: {test_dir}")
                logger.info(f"Test files directory: {test_files_dir}")
                logger.info(f"Python path: {sys.path[0]}")
                
                self.signals.update_text.emit(_("Base directory: ") + f"{base_dir}\n", "important")
                self.signals.update_text.emit(_("Test directory: ") + f"{test_dir}\n", "important")
                self.signals.update_text.emit(_("Test files directory: ") + f"{test_files_dir}\n", "important")
                self.signals.update_text.emit(_("Python path: ") + f"{sys.path[0]}\n", "important")
                
                # Verify test files exist
                for test_file in test_files[:]:
                    if not os.path.exists(test_file):
                        error_msg = _("Test file not found: {0}").format(test_file) + "\n"
                        logger.error(error_msg)
                        print(error_msg, file=original_stdout)
                        self.signals.update_text.emit(error_msg, "error")
                        test_files.remove(test_file)
                    else:
                        logger.info(f"Found test file: {test_file}")
                        self.signals.update_text.emit(_("Found test file: ") + f"{test_file}\n", "important")
                
                if not test_files:
                    error_msg = _("No test files found!") + "\n"
                    print(error_msg, file=original_stdout)
                    self.signals.update_text.emit(error_msg, "error")
                    return
                
                total_tests = 0
                current_test = 0
                passed_tests = 0
                failed_tests = 0
                
                # First pass to count tests
                self.signals.update_status.emit(_("Analyzing test suite..."))
                for test_file in test_files:
                    try:
                        class TestCounter:
                            def __init__(self):
                                self.count = 0
                            
                            def pytest_collection_modifyitems(self, items):
                                self.count = len(items)
                        
                        counter = TestCounter()
                        pytest.main(['--collect-only', '-v', test_file], plugins=[counter])
                        
                        if counter.count > 0:
                            total_tests += counter.count
                            message = _("Found {0} tests in {1}").format(counter.count, os.path.basename(test_file))
                            print(message, file=original_stdout)
                            self.signals.update_text.emit(message + "\n", "important")
                    except Exception as e:
                        error_msg = _("Error collecting tests from {0}: {1}").format(test_file, str(e)) + "\n"
                        error_trace = traceback.format_exc()
                        print(error_msg + error_trace, file=original_stdout)
                        self.signals.update_text.emit(error_msg, "error")
                        self.signals.update_text.emit(error_trace, "error")
                        continue
                
                self.progress_bar.setMaximum(total_tests or 1)  # Prevent division by zero
                self.signals.update_stats.emit({
                    'total': total_tests,
                    'passed': 0,
                    'failed': 0
                })
                
                # Run actual tests
                for test_file in test_files:
                    try:
                        # Update status with current file
                        current_file = os.path.basename(test_file)
                        self.signals.update_status.emit(_("Running tests from {0}...").format(current_file))
                        
                        # Add header for test file
                        self.signals.update_text.emit("\n" + _("Running tests from {0}:").format(current_file) + "\n", "header")
                        
                        class ResultCollector:
                            def __init__(self, signals):
                                self.signals = signals
                            
                            def pytest_runtest_logreport(self, report):
                                nonlocal current_test, passed_tests, failed_tests
                                if report.when == "call":
                                    current_test += 1
                                    
                                    # Update progress
                                    self.signals.update_progress.emit(current_test)
                                    
                                    # Format test name
                                    test_name = report.nodeid.split("::")[-1]
                                    
                                    if report.passed:
                                        passed_tests += 1
                                        self.signals.update_text.emit(f"✓ {test_name}\n", "pass")
                                    elif report.failed:
                                        failed_tests += 1
                                        self.signals.update_text.emit(f"✗ {test_name}\n", "fail")
                                        if report.longrepr:
                                            error_text = str(report.longrepr)
                                            message = "\n" + _("Error in {0}:").format(test_name) + f"\n{error_text}\n"
                                            print(message, file=original_stdout)
                                            self.signals.update_text.emit(message, "error")
                                    
                                    # Update statistics
                                    self.signals.update_stats.emit({
                                        'total': total_tests,
                                        'passed': passed_tests,
                                        'failed': failed_tests
                                    })
                        
                        # Create plugin instance with access to signals
                        collector = ResultCollector(self.signals)
                        
                        # Run tests with proper config
                        pytest.main(['-v', test_file], plugins=[collector])
                        
                    except Exception as e:
                        error_msg = "\n" + _("Error running tests in {0}: {1}").format(test_file, str(e)) + "\n"
                        error_trace = traceback.format_exc()
                        # Print to both console and results window
                        print(error_msg + error_trace, file=original_stdout)
                        self.signals.update_text.emit(error_msg, "error")
                        self.signals.update_text.emit(error_trace, "error")
                
                # Restore stdout and cwd
                sys.stdout = original_stdout
                os.chdir(original_cwd)
                
                # Mark as done
                self.signals.test_complete.emit()
                
            except Exception as e:
                error_msg = "\n" + _("Unexpected error running tests: {0}").format(str(e)) + "\n"
                error_trace = traceback.format_exc()
                # Print to both console and results window
                print(error_msg + error_trace, file=original_stdout)
                self.signals.update_text.emit(error_msg, "error")
                self.signals.update_text.emit(error_trace, "error")
                self.signals.test_complete.emit()
                
            finally:
                # Always ensure stdout is restored
                if 'original_stdout' in locals():
                    sys.stdout = original_stdout
        
        # Run tests in separate thread
        threading.Thread(target=run_tests_thread, daemon=True).start()
        
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
        
    def update_progress(self, value: int):
        """Update progress bar and percentage"""
        if hasattr(self.progress_bar, "maximum"):
            percentage = int((value / self.progress_bar.maximum()) * 100)
            self.progress_bar.setValue(value)
            self.progress_label.setText(f"{percentage}%")
            
    def show_context_menu(self, pos):
        """Show context menu for text operations"""
        menu = QMenu(self)
        
        copy_action = menu.addAction(_("Copy"))
        copy_action.triggered.connect(self.copy_selected_text)
        
        select_all_action = menu.addAction(_("Select All"))
        select_all_action.triggered.connect(self.select_all_text)
        
        menu.exec_(self.results_text.mapToGlobal(pos))
        
    def copy_selected_text(self):
        """Copy selected text to clipboard"""
        selected_text = self.results_text.textCursor().selectedText()
        if selected_text:
            QApplication.clipboard().setText(selected_text)
            
    def select_all_text(self):
        """Select all text in the results window"""
        self.results_text.selectAll()
        
    def append_text(self, text: str, tags: str = None):
        """Append text to results with optional tags"""
        cursor = self.results_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        if tags:
            format = QTextCharFormat()
            format.setForeground(QColor(self.get_tag_color(tags)))
            if tags == "error":
                format.setFontUnderline(True)
            cursor.insertText(text, format)
        else:
            cursor.insertText(text)
            
        self.results_text.setTextCursor(cursor)
        self.results_text.ensureCursorVisible()
        
    def get_tag_color(self, tag: str) -> str:
        """Get color for a text tag"""
        colors = {
            'pass': 'dark green',
            'fail': 'red',
            'error': 'red',
            'header': 'blue',
            'important': '#a0660b'
        }
        return colors.get(tag, 'black')
        
    def update_stats(self, stats: dict):
        """Update test statistics"""
        self.test_stats.update(stats)
        self.total_label.setText(_("Total Tests: {0}").format(stats['total']))
        self.passed_label.setText(_("Passed: {0}").format(stats['passed']))
        self.failed_label.setText(_("Failed: {0}").format(stats['failed']))
        
        # Update time elapsed
        elapsed = datetime.now() - self.test_stats['start_time']
        minutes = elapsed.seconds // 60
        seconds = elapsed.seconds % 60
        self.time_label.setText(_("Time: {0}:{1:02d}").format(minutes, seconds))
        
    def test_complete(self):
        """Handle test completion"""
        elapsed = datetime.now() - self.test_stats['start_time']
        minutes = elapsed.seconds // 60
        seconds = elapsed.seconds % 60
        
        # Add summary to results
        self.append_text("\n" + "="*50 + "\n", "header")
        self.append_text(_("Test Run Complete - ") + f"{minutes}:{seconds:02d}\n", "header")
        self.append_text(_("Total Tests: ") + f"{self.test_stats['total']}\n")
        self.append_text(_("Passed: ") + f"{self.test_stats['passed']}\n", "pass")
        self.append_text(_("Failed: ") + f"{self.test_stats['failed']}\n", "fail" if self.test_stats['failed'] > 0 else None)
        
        # Update status
        status = _("All tests passed successfully!") if self.test_stats['failed'] == 0 else _("Some tests failed - check results")
        self.status_label.setText(status)
        
        # Enable save button
        self.save_button.setEnabled(True)
        self.progress_bar.setVisible(False)