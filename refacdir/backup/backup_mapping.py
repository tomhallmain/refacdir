import os
from typing import List, Tuple, Optional

from .backup_modes import BackupMode, FileMode, HashMode, FailureType
from .backup_source_data import BackupSourceData
from .backup_state import BackupState
from .directory_ops import DirectoryOps
from .hash_manager import HashManager
from .safe_file_ops import SafeFileOps
from refacdir.utils.logger import setup_logger

# Set up logger for backup mapping
logger = setup_logger('backup_mapping')

try:
    from send2trash import send2trash
except Exception:
    logger.error("Could not import trashing utility - all deleted files will be deleted instantly")


def remove_file(path: str) -> bool:
    """Remove a file, preferably by moving to trash"""
    try:
        send2trash(os.path.normpath(path))
        return True
    except Exception as e:
        logger.error(f"Failed to send file to trash: {str(e)}")
        logger.error("Run pip install send2trash to enable trash functionality.")
        try:
            os.remove(path)
            return True
        except Exception as e:
            logger.error(f"Failed to remove file: {str(e)}")
            return False


def exception_as_dict(ex):
    return dict(type=ex.__class__.__name__,
                errno=ex.errno, message=ex.message,
                strerror=exception_as_dict(ex.strerror)
                if isinstance(ex.strerror, Exception) else ex.strerror)


class BackupTransaction:
    """Tracks backup operations and provides rollback capability"""
    
    def __init__(self):
        self.operations = []  # List of (operation, args, rollback_func) tuples
        self.completed = []  # List of completed operations for rollback
        
    def add_operation(self, operation, args, rollback_func):
        """Add an operation to the transaction"""
        self.operations.append((operation, args, rollback_func))
        
    def execute(self) -> Tuple[bool, Optional[str]]:
        """Execute all operations in the transaction"""
        try:
            for operation, args, _ in self.operations:
                success, error = operation(*args)
                if not success:
                    self.rollback()
                    return False, f"Operation failed: {error}"
                self.completed.append((operation, args))
            return True, None
        except Exception as e:
            self.rollback()
            return False, str(e)
            
    def rollback(self):
        """Roll back all completed operations in reverse order"""
        for operation, args in reversed(self.completed):
            try:
                # Find the rollback function for this operation
                for op, op_args, rollback_func in self.operations:
                    if op == operation and op_args == args:
                        if rollback_func:
                            rollback_func(*args)
                        break
            except Exception as e:
                logger.warning(f"Warning: Rollback operation failed: {str(e)}")


class BackupMapping:
    """Maps source directory to target directory for backup operations"""

    def __init__(self, name: str = "BackupMapping", 
                 source_dir: Optional[str] = None, 
                 target_dir: Optional[str] = None,
                 file_types: List[str] = [],
                 mode: BackupMode = BackupMode.PUSH,
                 file_mode: FileMode = FileMode.FILES_AND_DIRS,
                 hash_mode: HashMode = HashMode.SHA256,
                 exclude_dirs: List[str] = [],
                 exclude_removal_dirs: List[str] = [],
                 will_run: bool = True):
        """
        Initialize backup mapping.
        
        Args:
            name: Name of the backup mapping
            source_dir: Source directory path
            target_dir: Target directory path
            file_types: List of file extensions to include (empty for all)
            mode: Backup mode (PUSH, MIRROR, etc.)
            file_mode: File operation mode
            hash_mode: Hash mode for file comparison
            exclude_dirs: Directories to exclude from backup
            exclude_removal_dirs: Directories to exclude from removal
            will_run: Whether this mapping will be executed
        """
        if source_dir is None or target_dir is None:
            raise ValueError("Source and target directories must be specified")
            
        self.name = name
        self.source_dir = os.path.normpath(source_dir)
        self.target_dir = os.path.normpath(target_dir)
        self.file_types = file_types
        self.allows_all_file_types = len(self.file_types) == 0
        self.exclude_dirs = exclude_dirs
        self.exclude_removal_dirs = exclude_removal_dirs
        self.mode = mode
        self.file_mode = file_mode
        self.hash_mode = hash_mode
        self.will_run = will_run
        
        # Internal state
        self._source_data = BackupSourceData(source_dir)
        self._hash_manager = HashManager(hash_mode)
        self._source_dirs = []
        self._target_dirs = []
        self.modified_target_files = []
        self.failures = []
        self.transaction = None
        self.state = None

    def _file_type_match(self, filename: str) -> bool:
        """Check if a file matches the allowed file types"""
        if self.allows_all_file_types:
            return True
            
        for ext in self.file_types:
            if filename.endswith(ext):
                return True
                
        if "." in filename:
            extension = filename[filename.rfind("."):]
            return extension.lower() in self.file_types
            
        return False

    def _build_target_path(self, source_filepath: str) -> str:
        """Build target file path from source file path"""
        relative_path = source_filepath.replace(os.path.join(self.source_dir, ""), "")
        if relative_path.startswith(self.source_dir):
            raise ValueError(f"Failed to build target path: source filepath was {source_filepath}, source dir was {self.source_dir}")
        return os.path.join(self.target_dir, relative_path)

    def _create_dirs(self, target_path: str, test: bool = True) -> None:
        """Create target directory structure"""
        parent = os.path.dirname(target_path)
        if parent and not os.path.exists(parent):
            logger.info(f"Creating directory: {parent}")
            if not test:
                success, error = DirectoryOps.atomic_create_dir(parent)
                if not success:
                    raise Exception(f"Failed to create directory: {error}")

    def _is_file_excluded(self, filepath: str) -> bool:
        """Check if a file should be excluded from backup"""
        if self.file_mode == FileMode.DIRS_ONLY and not os.path.isdir(filepath):
            return True
        return any(filepath.startswith(d) or filepath == d for d in self.exclude_dirs)

    def _is_file_removal_excluded(self, filepath: str) -> bool:
        """Check if a file should be excluded from removal"""
        return any(filepath.startswith(d) for d in self.exclude_removal_dirs)

    def _move_file(self, source_path: str, external_source: Optional[str] = None,
                   move_func = SafeFileOps.move, test: bool = True) -> None:
        """Move or copy a file with proper rollback support"""
        target_path = self._build_target_path(source_path)
        self._create_dirs(target_path, test=test)
        
        def rollback_copy(src: str, dst: str) -> None:
            if os.path.exists(dst):
                os.unlink(dst)
                
        def rollback_move(src: str, dst: str) -> None:
            if os.path.exists(dst):
                SafeFileOps.move(dst, src)
        
        try:
            if external_source:
                logger.info(f"Moving file within external dir to: {target_path} - previous location: {external_source}")
                source_path = external_source
            elif os.path.exists(target_path):
                logger.info(f"Replacing file: {target_path}")
            else:
                logger.info(f"Creating file: {target_path}")
                
            if not test:
                rollback = rollback_move if move_func == SafeFileOps.move else rollback_copy
                self.transaction.add_operation(move_func, (source_path, target_path), rollback)
                self.modified_target_files.append(target_path)
                
        except Exception as e:
            self.failures.append([FailureType.MOVE_FILE, str(e), target_path, source_path])

    def _remove_source_file(self, source_path: str, target_path: str, test: bool = True) -> None:
        """Remove a source file after successful backup"""
        if self._is_file_removal_excluded(source_path):
            return
            
        if not os.path.exists(target_path):
            msg = f"Could not remove source file {source_path} - target file {target_path} not found"
            logger.error(msg)
            self.failures.append([FailureType.REMOVE_SOURCE_FILE_TARGET_NOEXIST, msg, target_path, source_path])
            return
            
        logger.info(f"Removing file already backed up: {source_path}")
        if not test:
            try:
                if not remove_file(source_path):
                    raise Exception("Failed to remove file")
            except Exception as e:
                self.failures.append([FailureType.REMOVE_SOURCE_FILE, str(e), target_path, source_path])

    def backup(self, test: bool = True) -> None:
        """
        Perform backup operation with transaction support and state validation.
        
        Args:
            test: Whether to run in test mode (no actual changes)
        """
        try:
            # Initialize state tracking
            self.state = BackupState(self)
            success, error = self.state.validate_source()
            if not success:
                raise Exception(error)
                
            # Initialize transaction
            self.transaction = BackupTransaction()
            
            if self.is_push_mode():
                move_func = SafeFileOps.move if self.mode == BackupMode.PUSH_AND_REMOVE else SafeFileOps.copy
                self._push(move_func=move_func, test=test)
            elif self.is_mirror_mode():
                self._source_data.save()
                self._mirror(test=test)
                
            if not test:
                # Execute transaction
                success, error = self.transaction.execute()
                if not success:
                    raise Exception(error)
                    
                # Validate final state
                success, error = self.state.validate_target()
                if not success:
                    raise Exception(error)
                    
                success, error = self.state.verify_integrity()
                if not success:
                    self.transaction.rollback()
                    raise Exception(error)
                    
        except Exception as e:
            self.failures.append([FailureType.BACKUP_OPERATION, str(e), 
                                "Backup operation failed", str(e)])
            if not test and self.transaction:
                self.transaction.rollback()
        finally:
            self.transaction = None
            self.state = None

    def is_push_mode(self) -> bool:
        """Check if backup is in push mode"""
        return self.mode in [BackupMode.PUSH, BackupMode.PUSH_DUPLICATES, BackupMode.PUSH_AND_REMOVE]

    def is_mirror_mode(self) -> bool:
        """Check if backup is in mirror mode"""
        return self.mode in [BackupMode.MIRROR, BackupMode.MIRROR_DUPLICATES]

    def clean(self) -> None:
        """Clean up backup state"""
        self.failures.clear()
        self.modified_target_files.clear()
        if self.state:
            self.state.clear()
        self._hash_manager.clear_cache()

    def __str__(self) -> str:
        return f"""BackupMapping{{
    Name: {self.name}
    Source: {self.source_dir}
    Target: {self.target_dir}
    Mode: {self.mode}
    File types: {self.file_types}
    Exclude dirs: {self.exclude_dirs}
    Exclude removal dirs: {self.exclude_removal_dirs}
}}"""
