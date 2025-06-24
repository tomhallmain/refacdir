import os
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import platform
import glob
from datetime import datetime, timedelta
from typing import List

# Global variable to track if the root logger has been configured
_root_logger_configured = False

class CustomFormatter(logging.Formatter):
    """Custom formatter that provides colored output for console and clean output for files."""
    
    # ANSI color codes
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    
    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors
        
        if use_colors:
            self.FORMATS = {
                logging.DEBUG: self.grey + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + self.reset,
                logging.INFO: self.blue + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + self.reset,
                logging.WARNING: self.yellow + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + self.reset,
                logging.ERROR: self.red + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + self.reset,
                logging.CRITICAL: self.bold_red + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + self.reset
            }
        else:
            self.FORMATS = {
                logging.DEBUG: "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                logging.INFO: "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                logging.WARNING: "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                logging.ERROR: "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                logging.CRITICAL: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
    
    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

def get_log_directory():
    """Get the appropriate log directory based on the operating system."""
    system = platform.system().lower()
    
    if system == 'windows':
        # Use AppData\Local for Windows
        appdata = os.getenv('LOCALAPPDATA')
        if not appdata:
            appdata = os.path.expanduser('~\\AppData\\Local')
        log_dir = Path(appdata) / 'refacdir' / 'logs'
    else:
        # Use ~/.local/share for Linux/Mac
        log_dir = Path.home() / '.local' / 'share' / 'refacdir' / 'logs'
    
    # Create directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir

def _cleanup_old_logs(log_dir: Path, logger: logging.Logger) -> None:
    """
    Clean up log files that are older than 30 days if there are more than 10 log files.
    
    Args:
        log_dir: Path object pointing to the directory containing log files
        logger: Logger instance to use for logging cleanup operations
    """
    try:
        log_files: List[Path] = list(log_dir.glob('refacdir_*.log'))
        if len(log_files) <= 10:
            return

        current_time: datetime = datetime.now()
        cutoff_date: datetime = current_time - timedelta(days=30)
        
        for log_file in log_files:
            try:
                # Extract date from filename (format: refacdir_YYYY-MM-DD.log)
                date_str: str = log_file.stem.split('_')[-1]
                file_date: datetime = datetime.strptime(date_str, '%Y-%m-%d')
            except (ValueError, IndexError):
                # If filename doesn't contain a valid date, use the file's last modified date
                file_date = datetime.fromtimestamp(log_file.stat().st_mtime)
            
            if file_date < cutoff_date:
                log_file.unlink()
                logger.debug(f"Deleted old log file: {log_file}")
    except Exception as e:
        logger.error(f"Error cleaning up old log files: {e}")

def _configure_root_logger():
    """Configure the root logger with file and console handlers.
    This should only be called once per application."""
    global _root_logger_configured
    
    if _root_logger_configured:
        return
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Don't add handlers if they already exist
    if root_logger.handlers:
        _root_logger_configured = True
        return
    
    # Create log directory
    log_dir = get_log_directory()
    
    # Clean up old logs before creating new one
    _cleanup_old_logs(log_dir, root_logger)
    
    # Create daily log file with date in filename
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f'refacdir_{date_str}.log'
    
    # Create file handler
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    file_formatter = CustomFormatter(use_colors=False)
    console_formatter = CustomFormatter(use_colors=True)
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    _root_logger_configured = True

def setup_logger(name, log_file='refacdir.log'):
    """Set up a logger for a specific module.
    
    Args:
        name: Name of the logger (module name)
        log_file: Name of the log file (deprecated, kept for compatibility)
    
    Returns:
        logging.Logger: Configured logger instance
    """
    # Configure root logger if not already done
    _configure_root_logger()
    
    # Get logger with module name
    logger = logging.getLogger(f"refacdir.{name}")
    logger.setLevel(logging.DEBUG)
    
    # Allow propagation to root logger for file logging
    logger.propagate = True
    
    # If handlers are already set up for this logger, return it
    if logger.handlers:
        return logger
    
    # Note: We don't add console handlers to individual loggers
    # because the root logger already has a console handler
    # This prevents duplicate console output while ensuring
    # all logs go to the file through propagation
    
    return logger 