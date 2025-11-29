from copy import deepcopy
import os
import signal
import traceback

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QProgressBar, QFrame,
    QMessageBox, QScrollArea, QSizePolicy, QTextEdit, QFileDialog, QLineEdit, QGridLayout, QStyle
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread
from PySide6.QtGui import QFont, QPalette, QColor

from run import main
from extensions.refacdir_server import RefacDirServer
from refacdir.batch import BatchArgs
from refacdir.config import config as _config
from refacdir.job_queue import JobQueue
from refacdir.lib.multi_display import SmartMainWindow
from refacdir.running_tasks_registry import start_thread, periodic, RecurringActionConfig
from refacdir.utils.app_info_cache import app_info_cache
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import I18N
from refacdir.utils.utils import Utils
from ui import AppActions, ThemeManager, ThemeColors, ToastNotification, TestResultsWindow

_ = I18N._

# Set up logger for UI
logger = setup_logger('ui')

class ProgressListener:
    def __init__(self, update_func):
        self.update_func = update_func

    def update(self, context, percent_complete):
        self.update_func(context, percent_complete)

    def update_status(self, status):
        self.update_func(None, None, status)


class MainWindow(SmartMainWindow):
    """Main application window"""
    
    # Define signals for progress updates
    progress_text_signal = Signal(str)
    progress_bar_update_signal = Signal(float)
    progress_bar_reset_signal = Signal()
    
    def __init__(self):
        # Initialize SmartMainWindow with geometry persistence using app_info_cache
        super().__init__(restore_geometry=True)
        self.configs = {}
        self.filtered_configs = {}
        self.filter_text = ""
        self.progress_bar = None
        self.job_queue = JobQueue()
        self.server = self.setup_server()
        self.recurring_action_config = RecurringActionConfig()
        self._toast = ToastNotification()
        self.is_dark_theme = True

        app_actions = {
            "toast": self.toast,
            "alert": self.alert,
            "progress_text": self.progress_text,
            "progress_bar_update": self.progress_bar_update,
            "progress_bar_reset": self.progress_bar_reset,
        }
        self.app_actions = AppActions(app_actions)
        
        # Connect signals to slots
        self.progress_text_signal.connect(self._progress_text)
        self.progress_bar_update_signal.connect(self._progress_bar_update)
        self.progress_bar_reset_signal.connect(self._progress_bar_reset)
        
        self.setup_ui()
        self.setup_connections()
        self.load_configs()
        
        # Restore UI settings from app_info_cache
        self.restore_ui_settings()
        
        # Restore window geometry after UI is set up
        if self._restore_geometry:
            self.restore_window_geometry()
        
    def setup_ui(self):
        """Initialize the main UI components"""
        self.setWindowTitle(_("RefacDir"))
        self.resize(1000, 700)  # Slightly larger default size
        self.setMinimumSize(800, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins for full-width design
        main_layout.setSpacing(0)  # Remove spacing between main sections
        
        # Create sections
        self._create_sidebar(main_layout)
        self._create_main_content(main_layout)
        
        # Apply initial theme (will be overridden by restore_ui_settings if cached)
        self.apply_theme(is_dark=True)
        
    def _create_sidebar(self, parent_layout):
        """Create the sidebar with action buttons and configs"""
        sidebar = QWidget()
        sidebar.setFixedWidth(280)  # Wider sidebar for better readability
        sidebar.setObjectName("sidebar")  # For styling
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 20, 20, 20)
        sidebar_layout.setSpacing(15)
        
        # Logo/Title section
        title_section = QWidget()
        title_layout = QVBoxLayout(title_section)
        title_layout.setContentsMargins(0, 0, 0, 20)
        
        title = QLabel("RefacDir")
        title.setFont(QFont("Helvetica", 16, QFont.Bold))
        title_layout.addWidget(title)
        
        subtitle = QLabel(_("File Management"))
        subtitle.setFont(QFont("Helvetica", 10))
        subtitle.setStyleSheet("color: gray;")
        title_layout.addWidget(subtitle)
        
        sidebar_layout.addWidget(title_section)
        
        # Action buttons in a frame
        actions_frame = QFrame()
        actions_frame.setObjectName("actionsFrame")
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setSpacing(10)
        
        self.toggle_theme_btn = QPushButton(_("Toggle Theme"))
        self.toggle_theme_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.toggle_theme_btn.clicked.connect(self.toggle_theme)
        actions_layout.addWidget(self.toggle_theme_btn)
        
        self.test_runner_btn = QPushButton(_("Run Backup Tests"))
        self.test_runner_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.test_runner_btn.clicked.connect(self.run_tests)
        actions_layout.addWidget(self.test_runner_btn)
        
        self.run_btn = QPushButton(_("Run Operations"))
        self.run_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.run_btn.clicked.connect(self.run)
        actions_layout.addWidget(self.run_btn)
        
        sidebar_layout.addWidget(actions_frame)
        
        # Search box
        search_frame = QFrame()
        search_frame.setObjectName("searchFrame")
        search_layout = QVBoxLayout(search_frame)
        
        search_label = QLabel(_("Search Configurations"))
        search_label.setFont(QFont("Helvetica", 10, QFont.Bold))
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Type to filter..."))
        self.search_input.textChanged.connect(self.filter_configs)
        search_layout.addWidget(self.search_input)
        
        sidebar_layout.addWidget(search_frame)
        
        # Config checkboxes container with title
        config_section = QWidget()
        config_layout = QVBoxLayout(config_section)
        config_layout.setSpacing(10)
        
        config_header = QLabel(_("Available Configurations"))
        config_header.setFont(QFont("Helvetica", 10, QFont.Bold))
        config_layout.addWidget(config_header)
        
        self.config_scroll = QScrollArea()
        self.config_scroll.setWidgetResizable(True)
        self.config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.config_scroll.setObjectName("configScroll")
        
        config_container = QWidget()
        self.config_layout = QVBoxLayout(config_container)
        self.config_layout.setSpacing(8)
        self.config_scroll.setWidget(config_container)
        
        config_layout.addWidget(self.config_scroll)
        sidebar_layout.addWidget(config_section)
        
        parent_layout.addWidget(sidebar)
        
    def _create_main_content(self, parent_layout):
        """Create the main content area"""
        main_content = QWidget()
        main_content.setObjectName("mainContent")
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)
        
        # Header section
        self._create_header_section(main_layout)
        
        # Options section
        self._create_options_section(main_layout)
        
        # Progress section
        self._create_progress_section(main_layout)
        
        # Add stretch to push everything up
        main_layout.addStretch()
        
        parent_layout.addWidget(main_content)
        
    def _create_header_section(self, parent_layout):
        """Create the header section with title and description"""
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setSpacing(10)
        
        title = QLabel(_("File Management Dashboard"))
        title.setFont(QFont("Helvetica", 24, QFont.Bold))
        header_layout.addWidget(title)
        
        description = QLabel(_("Configure and run file management operations with ease. Select configurations from the sidebar and customize options below."))
        description.setWordWrap(True)
        description.setStyleSheet("color: gray;")
        header_layout.addWidget(description)
        
        parent_layout.addWidget(header)
        
    def _create_options_section(self, parent_layout):
        """Create the options section with checkboxes"""
        options_frame = QFrame()
        options_frame.setObjectName("optionsFrame")
        options_frame.setFrameStyle(QFrame.StyledPanel)
        options_layout = QVBoxLayout(options_frame)
        options_layout.setSpacing(15)
        
        # Options title
        options_title = QLabel(_("Operation Settings"))
        options_title.setFont(QFont("Helvetica", 14, QFont.Bold))
        options_layout.addWidget(options_title)
        
        # Configuration options in a grid
        options_grid = QGridLayout()
        options_grid.setSpacing(15)
        
        self.recur_check = QCheckBox(_("Recur Selected Actions"))
        self.recur_check.stateChanged.connect(self.set_recurring_action)
        options_grid.addWidget(self.recur_check, 0, 0)
        
        self.test_check = QCheckBox(_("Test Mode"))
        self.test_check.stateChanged.connect(lambda: self.store_ui_settings())
        options_grid.addWidget(self.test_check, 0, 1)
        
        self.skip_confirm_check = QCheckBox(_("Skip Confirmations"))
        self.skip_confirm_check.stateChanged.connect(lambda: self.store_ui_settings())
        options_grid.addWidget(self.skip_confirm_check, 1, 0)
        
        self.only_observers_check = QCheckBox(_("Only Observers"))
        self.only_observers_check.stateChanged.connect(lambda: self.store_ui_settings())
        options_grid.addWidget(self.only_observers_check, 1, 1)
        
        options_layout.addLayout(options_grid)
        parent_layout.addWidget(options_frame)
        
    def _create_progress_section(self, parent_layout):
        """Create the progress section with status and progress bar"""
        progress_frame = QFrame()
        progress_frame.setObjectName("progressFrame")
        progress_frame.setFrameStyle(QFrame.StyledPanel)
        progress_layout = QVBoxLayout(progress_frame)
        progress_layout.setSpacing(15)
        
        # Progress title
        progress_title = QLabel(_("Operation Status"))
        progress_title.setFont(QFont("Helvetica", 14, QFont.Bold))
        progress_layout.addWidget(progress_title)
        
        self.status_label = QLabel(_("Ready"))
        self.status_label.setFont(QFont("Helvetica", 10))
        progress_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)
        
        parent_layout.addWidget(progress_frame)
        
    def apply_theme(self, is_dark: bool):
        """Apply the selected theme to the application"""
        self.is_dark_theme = is_dark
        ThemeManager.apply_theme(QApplication.instance(), is_dark)
        # Save theme preference
        app_info_cache.set_ui_theme(is_dark)

    def toggle_theme(self):
        """Toggle between light and dark themes"""
        self.apply_theme(not self.is_dark_theme)
        self.toast.show_message(
            "Theme switched to light." if not self.is_dark_theme else "Theme switched to dark."
        )
        # Save settings when theme changes
        self.store_ui_settings()

    def setup_connections(self):
        """Set up signal/slot connections"""
        # TODO: Implement signal connections
        
    def load_configs(self):
        """Load initial configurations"""
        BatchArgs.setup_configs(recache=False)
        self.configs = deepcopy(BatchArgs.configs)
        self.filtered_configs = deepcopy(BatchArgs.configs)
        self.add_config_widgets()
        
    def setup_server(self):
        """Initialize the server component"""
        server = RefacDirServer(self.server_run_callback)
        try:
            Utils.start_thread(server.start)
            logger.info("Server started successfully")
            return server
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
        return None
        
    def server_run_callback(self, args):
        """Handle server callbacks"""
        if len(args) > 0:
            logger.info(f"Server callback received with args: {args}")
            self.update()
        self.run()
        return {}

    def add_config_widgets(self):
        """Add configuration checkboxes to sidebar"""
        # Clear existing widgets
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Add new checkboxes
        for config, will_run in self.filtered_configs.items():
            checkbox = QCheckBox(config)
            checkbox.setChecked(will_run if will_run is not None else False)
            checkbox.stateChanged.connect(lambda state, c=config: self.toggle_config(c, state))
            self.config_layout.addWidget(checkbox)
            
    def toggle_config(self, config: str, state: int):
        """Handle config checkbox state changes"""
        if config in self.filtered_configs:
            self.filtered_configs[config] = state == Qt.Checked
            self.configs[config] = self.filtered_configs[config]
            BatchArgs.update_config_state(config, self.filtered_configs[config])
            logger.info(f"Config {config} set to {self.filtered_configs[config]}")
            # Save settings when config selection changes
            self.store_ui_settings()
            
    def filter_configs(self, text: str):
        """Filter configurations based on search text"""
        if not text.strip():
            self.filtered_configs = deepcopy(self.configs)
        else:
            self.filtered_configs = {}
            for path in self.configs:
                basename = os.path.basename(os.path.normpath(path))
                if (basename.lower() == text.lower() or
                    basename.lower().startswith(text.lower()) or
                    f" {text.lower()}" in basename.lower() or
                    f"_{text.lower()}" in basename.lower()):
                    self.filtered_configs[path] = self.configs[path]
        
        self.add_config_widgets()
        
    def run(self):
        """Run the selected operations"""
        if self.progress_bar.isVisible():
            return
            
        args = BatchArgs(recache_configs=False)
        args.test = self.test_check.isChecked()
        args.skip_confirm = self.skip_confirm_check.isChecked()
        args.only_observers = self.only_observers_check.isChecked()
        args.app_actions = self.app_actions
        
        # Only run filtered configs
        BatchArgs.override_configs(self.filtered_configs)
        
        # Show progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(_("Running operations..."))
        
        # Run operations in background
        def run_async():
            try:
                main(args)
            except Exception as e:
                self.alert("Error", str(e), "error")
                self.status_label.setText(_("Operation failed"))
            finally:
                self.status_label.setText(_("Ready"))
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
                
        Utils.start_thread(run_async)
        
    def set_recurring_action(self, state: int):
        """Handle recurring action checkbox state changes"""
        self.recurring_action_config.set(state == Qt.Checked)
        if self.recurring_action_config.is_running:
            self.skip_confirm_check.setChecked(True)
            start_thread(self.run_recurring_actions)
        # Save settings when operation settings change
        self.store_ui_settings()
            
    @periodic("recurring_action_config")
    async def run_recurring_actions(self, **kwargs):
        self.run()
        
    def run_tests(self):
        """Run backup system tests"""
        test_window = TestResultsWindow(self)
        test_window.show()
        test_window.run_tests()
        
    def run_config(self, config: str):
        """Run operations for a specific config"""
        if not os.path.isdir(config):
            self.alert("Error", _("Failed to set target directory to receive marked files."), "error")
            return
            
        self.filtered_configs = {config: True}
        self.run()

    def toast(self, message: str):
        """Show a toast notification"""
        self._toast.show_message(message)

    def alert(self, title: str, message: str, kind: str = "info"):
        """Show an alert dialog"""
        if kind not in ("error", "warning", "info"):
            raise ValueError("Unsupported alert kind.")
            
        logger.info(f"Alert - Title: \"{title}\" Message: {message}")
        
        # Use theme colors for message boxes
        if kind == "error":
            QMessageBox.critical(self, title, message)
        elif kind == "warning":
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.information(self, title, message)
        
    def restore_ui_settings(self):
        """Restore UI settings from app_info_cache"""
        try:
            # Restore theme preference
            cached_theme = app_info_cache.get_ui_theme(default=True)
            if cached_theme != self.is_dark_theme:
                self.apply_theme(cached_theme)
            
            # Restore operation settings (checkboxes)
            operation_settings = app_info_cache.get_operation_settings()
            self.recur_check.setChecked(operation_settings.get('recur', False))
            self.test_check.setChecked(operation_settings.get('test_mode', False))
            self.skip_confirm_check.setChecked(operation_settings.get('skip_confirm', False))
            self.only_observers_check.setChecked(operation_settings.get('only_observers', False))
            
            # Restore selected configurations
            cached_configs = app_info_cache.get_selected_configs()
            if cached_configs:
                # Update configs dict with cached selections
                for config_path, enabled in cached_configs.items():
                    if config_path in self.configs:
                        self.configs[config_path] = enabled
                        self.filtered_configs[config_path] = enabled
                        BatchArgs.update_config_state(config_path, enabled)
                # Refresh the UI to reflect restored selections
                self.add_config_widgets()
            
            # Restore search filter text (optional - might be annoying)
            # Uncomment if you want to restore search text:
            # cached_filter = app_info_cache.get_search_filter()
            # if cached_filter:
            #     self.filter_text = cached_filter
            #     self.search_input.setText(cached_filter)
            #     self.filter_configs(cached_filter)
            
            logger.debug("UI settings restored from app_info_cache")
        except Exception as e:
            logger.error(f"Error restoring UI settings: {e}")
    
    def store_ui_settings(self):
        """Save current UI settings to app_info_cache"""
        try:
            # Save theme preference
            app_info_cache.set_ui_theme(self.is_dark_theme)
            
            # Save operation settings
            operation_settings = {
                'recur': self.recur_check.isChecked(),
                'test_mode': self.test_check.isChecked(),
                'skip_confirm': self.skip_confirm_check.isChecked(),
                'only_observers': self.only_observers_check.isChecked()
            }
            app_info_cache.set_operation_settings(operation_settings)
            
            # Save selected configurations (only enabled ones)
            selected_configs = {
                config_path: enabled 
                for config_path, enabled in self.configs.items() 
                if enabled
            }
            app_info_cache.set_selected_configs(selected_configs)
            
            # Save search filter text (optional)
            # app_info_cache.set_search_filter(self.filter_text)
            
            # Persist to disk (handles credential errors gracefully)
            app_info_cache.store()
            
            logger.debug("UI settings saved to app_info_cache")
        except Exception as e:
            # Log but don't raise - UI settings save failures shouldn't crash the app
            error_str = str(e)
            error_repr = repr(e)
            
            # Check for Windows Credential Manager errors
            is_cred_error = (
                'CredRead' in error_str or 
                'CredRead' in error_repr or
                'Element not found' in error_str or 
                '1168' in error_str or
                (isinstance(e, tuple) and len(e) >= 2 and 'CredRead' in str(e[1]))
            )
            
            if is_cred_error:
                logger.debug(f"Credential manager error saving UI settings (likely first run): {e}")
            else:
                logger.error(f"Error saving UI settings: {e}")
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Save UI settings before closing
        self.store_ui_settings()
        
        if self.server is not None:
            try:
                self.server.stop()
                logger.info("Server stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
        # Call parent closeEvent to save window geometry
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Handle keyboard events"""
        # Handle Shift+R for running operations
        if event.key() == Qt.Key_R and event.modifiers() & Qt.ShiftModifier:
            self.run()
            return
            
        # Handle Enter for running filtered config
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.filter_text.strip():
                if len(self.filtered_configs) == 1:
                    config = next(iter(self.filtered_configs))
                    self.run_config(config)
                else:
                    self.run()
            return
            
        # Handle Backspace for filtering
        if event.key() == Qt.Key_Backspace:
            if self.filter_text:
                self.filter_text = self.filter_text[:-1]
                self.filter_configs(self.filter_text)
            return
            
        # Handle regular text input for filtering
        if event.text():
            self.filter_text += event.text()
            self.filter_configs(self.filter_text)

    def progress_text(self, text: str):
        """Update the progress status text (thread-safe)"""
        self.progress_text_signal.emit(text)
        
    def _progress_text(self, text: str):
        """Handle progress text update on main thread"""
        self.status_label.setText(text)
        
    def progress_bar_update(self, context: str, percent_complete: float):
        """Update the progress bar with completion percentage (thread-safe)"""
        self.progress_bar_update_signal.emit(percent_complete)
        
    def _progress_bar_update(self, percent_complete: float):
        """Handle progress bar update on main thread"""
        if not self.progress_bar.isVisible():
            self.progress_bar.setVisible(True)
        self.progress_bar.setValue(int(percent_complete * 100))
        
    def progress_bar_reset(self):
        """Reset the progress bar and hide it (thread-safe)"""
        self.progress_bar_reset_signal.emit()
        
    def _progress_bar_reset(self):
        """Handle progress bar reset on main thread"""
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.status_label.setText(_("Ready"))


if __name__ == "__main__":
    try:
        # Set up signal handlers for graceful shutdown
        def graceful_shutdown(signum, frame):
            logger.info("Caught signal, shutting down gracefully...")
            app.close()
            exit(0)
            
        signal.signal(signal.SIGINT, graceful_shutdown)
        signal.signal(signal.SIGTERM, graceful_shutdown)
        
        # Create and run application
        app = QApplication([])
        window = MainWindow()
        window.show()
        exit(app.exec())
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc() 