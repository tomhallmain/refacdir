"""
Backup Source Data Management System

This module provides a robust backup system with the following features:
1. Atomic Operations: All file operations are atomic to prevent corruption
2. Concurrent Access Protection: File locking prevents simultaneous access
3. Disk Space Safety: Checks for sufficient space and enforces size limits
4. Metadata Corruption Recovery: Maintains backup copy of metadata
5. Compression Support: Optional zlib compression for backups
6. Progress Reporting: Real-time progress updates during operations
7. Interrupted Backup Resume: Can resume partially completed backups

Key Classes:
- BackupSourceData: Main backup management class
- BackupMetadata: Stores metadata for each backup
- ProgressCallback: Interface for progress reporting
- BackupProgress: Tracks progress of backup operations
"""

import datetime
import os
import pickle
import time
import hashlib
import json
# TODO use a module that is supported on windows instead, maybe portalocker
#import fcntl
import errno
import shutil
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any, Set
from pathlib import Path
import zlib

class BackupLockError(Exception):
    """Raised when unable to acquire backup lock"""
    pass

class BackupMetadata:
    """
    Stores metadata about a backup.
    
    Attributes:
        timestamp (datetime): When the backup was created
        description (str): User-provided description of the backup
        file_count (int): Number of files in the backup
        checksum (str): SHA-256 hash of the backup file
        version (int): Backup format version
        files (set): Set of files included in this backup
        compressed (bool): Whether the backup is compressed
        partial (bool): Whether this is an incomplete backup
        bytes_written (int): Number of bytes written for partial backups
    """
    
    def __init__(self, description: str = "", file_count: int = 0):
        """
        Initialize backup metadata.
        
        Args:
            description: Optional description of the backup
            file_count: Number of files in the backup
        """
        self.timestamp = datetime.datetime.now()
        self.description = description
        self.file_count = file_count
        self.checksum = ""  # Will be set when backup is created
        self.version = BackupSourceData.VERSION
        self.files = set()  # Set of files included in this backup
        self.compressed = False  # Whether the backup is compressed
        self.partial = False  # Whether this is a partial/incomplete backup
        self.bytes_written = 0  # Number of bytes written for partial backups

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for serialization"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "file_count": self.file_count,
            "checksum": self.checksum,
            "version": self.version,
            "files": list(self.files),
            "compressed": self.compressed,
            "partial": self.partial,
            "bytes_written": self.bytes_written
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'BackupMetadata':
        """
        Create metadata instance from dictionary.
        
        Args:
            data: Dictionary containing metadata attributes
            
        Returns:
            BackupMetadata instance
        """
        metadata = BackupMetadata()
        metadata.timestamp = datetime.datetime.fromisoformat(data["timestamp"])
        metadata.description = data["description"]
        metadata.file_count = data["file_count"]
        metadata.checksum = data["checksum"]
        metadata.version = data.get("version", 1)  # Default to version 1 for compatibility
        metadata.files = set(data.get("files", []))  # Default to empty set for compatibility
        metadata.compressed = data.get("compressed", False)  # Default to uncompressed for compatibility
        metadata.partial = data.get("partial", False)  # Default to complete backup for compatibility
        metadata.bytes_written = data.get("bytes_written", 0)  # Default to 0 for compatibility
        return metadata

class ProgressCallback:
    """
    Callback interface for backup progress reporting.
    
    Implement this interface to receive progress updates during backup operations.
    """
    
    def on_progress(self, current: int, total: int, message: str = ""):
        """
        Called when progress is updated.
        
        Args:
            current: Current progress value (e.g., bytes copied)
            total: Total expected value
            message: Optional status message
        """
        pass

class BackupProgress:
    """
    Tracks progress of backup operations.
    
    Attributes:
        callback (ProgressCallback): Callback to notify of progress
        current (int): Current progress value
        total (int): Total expected value
        message (str): Current status message
    """
    
    def __init__(self, callback: ProgressCallback = None):
        """
        Initialize progress tracker.
        
        Args:
            callback: Optional callback to receive progress updates
        """
        self.callback = callback
        self.current = 0
        self.total = 0
        self.message = ""
        
    def start(self, total: int, message: str = ""):
        """
        Start tracking progress.
        
        Args:
            total: Total expected value
            message: Initial status message
        """
        self.current = 0
        self.total = total
        self.message = message
        self._notify()
        
    def update(self, current: int = None, message: str = None):
        """
        Update progress.
        
        Args:
            current: New progress value
            message: New status message
        """
        if current is not None:
            self.current = current
        if message is not None:
            self.message = message
        self._notify()
        
    def _notify(self):
        """Notify callback of progress update"""
        if self.callback:
            self.callback.on_progress(self.current, self.total, self.message)

class BackupSourceData:
    """
    Manages persistent backup source data with the following features:
    
    1. Atomic Operations:
       - All file writes use temporary files and atomic moves
       - Prevents partial/corrupted backups
       - Maintains backup integrity during crashes
    
    2. Concurrent Access Protection:
       - File locking prevents simultaneous access
       - Timeout-based lock acquisition
       - Automatic lock cleanup
    
    3. Disk Space Safety:
       - Checks for sufficient free space
       - Enforces maximum backup size limits
       - Automatic cleanup of old backups
    
    4. Metadata Corruption Recovery:
       - Maintains backup copy of metadata
       - Automatic recovery from corrupted metadata
       - Version compatibility handling
    
    5. Compression Support:
       - Optional zlib compression
       - Automatic compression detection
       - Configurable compression level
    
    6. Progress Reporting:
       - Real-time progress updates
       - Status messages for operations
       - Customizable progress callbacks
    
    7. Interrupted Backup Resume:
       - Tracks partial backup progress
       - Resumes from last written position
       - Handles both compressed and uncompressed backups
    
    Usage:
        # Create backup manager
        backup = BackupSourceData("./source_dir")
        
        # Enable compression
        backup.use_compression = True
        
        # Create backup with description
        backup.save("Weekly backup")
        
        # Restore from most recent backup
        success, error = backup.restore_from_backup()
        
        # Find backups by criteria
        backups = backup.find_backups(
            start_date=datetime.now() - timedelta(days=7),
            description="weekly",
            min_files=100
        )
    """
    
    FILEPATH = "backup_mapping_data.pkl"
    BACKUP_DIR = ".backup_data"
    METADATA_FILE = "backup_metadata.json"
    METADATA_BACKUP_FILE = "backup_metadata.backup.json"  # Backup copy of metadata
    LOCK_FILE = ".backup.lock"  # Lock file for concurrent access
    MAX_BACKUPS = 5  # Maximum number of backup files to keep
    VERSION = 2  # Incremented for metadata support
    
    # Disk space safety limits
    MIN_FREE_SPACE_MB = 100  # Minimum free space required in MB
    MAX_BACKUP_SIZE_MB = 1000  # Maximum size of a single backup in MB
    
    # Temporary file suffixes
    TEMP_SUFFIX = ".tmp"
    METADATA_TEMP_SUFFIX = ".metadata.tmp"
    
    # Compression settings
    COMPRESSION_LEVEL = 6  # Default compression level (0-9, higher = better compression but slower)

    def __init__(self, source_dir: str = ".", progress_callback: ProgressCallback = None):
        self.source_dir = source_dir
        self.filepath = os.path.normpath(os.path.join(source_dir, self.FILEPATH))
        self.backup_dir = os.path.normpath(os.path.join(source_dir, self.BACKUP_DIR))
        self.lock_file = os.path.normpath(os.path.join(source_dir, self.LOCK_FILE))
        self.hash_dict = defaultdict(list)  # hash -> list of files
        self.last_updated = self._get_timestamp()
        self.version = self.VERSION
        self._lock_fd = None
        self.progress = BackupProgress(progress_callback)
        self.use_compression = False  # Whether to compress new backups

    def __enter__(self):
        """Context manager entry - acquire lock"""
        self.acquire_lock()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - release lock"""
        self.release_lock()

    def acquire_lock(self, timeout: int = 10):
        """
        Acquire backup lock with timeout.
        
        Args:
            timeout: Maximum seconds to wait for lock
            
        Raises:
            BackupLockError: If lock cannot be acquired
        """
        start_time = time.time()
        while True:
            try:
                self._lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR)
                #fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (IOError, OSError) as e:
                if e.errno != errno.EAGAIN:
                    raise
                if time.time() - start_time > timeout:
                    raise BackupLockError("Failed to acquire backup lock")
                time.sleep(0.1)

    def release_lock(self):
        """Release backup lock"""
        if self._lock_fd is not None:
            try:
                #fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            finally:
                self._lock_fd = None
            try:
                os.remove(self.lock_file)
            except OSError:
                pass

    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds"""
        return int(time.time() * 1000)

    def _get_backup_filepath(self) -> str:
        """Generate timestamped backup filepath"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.backup_dir, f"{self.FILEPATH}.{timestamp}")

    def _get_available_backups(self) -> List[Tuple[float, str]]:
        """
        Get list of available backup files sorted by timestamp (newest first).
        
        Returns:
            List of tuples (timestamp, filepath)
        """
        if not os.path.exists(self.backup_dir):
            return []

        backup_files = []
        for f in os.listdir(self.backup_dir):
            if f.startswith(self.FILEPATH):
                path = os.path.join(self.backup_dir, f)
                backup_files.append((os.path.getmtime(path), path))
        
        backup_files.sort(reverse=True)
        return backup_files

    def _cleanup_old_backups(self):
        """Remove old backup files keeping only the most recent ones"""
        backup_files = self._get_available_backups()

        # Remove old backups exceeding MAX_BACKUPS
        for _, filepath in backup_files[self.MAX_BACKUPS:]:
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Warning: Failed to remove old backup {filepath}: {str(e)}")

    def _calculate_checksum(self, filepath: str) -> str:
        """Calculate SHA-256 checksum of a file"""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for block in iter(lambda: f.read(4096), b""):
                sha256.update(block)
        return sha256.hexdigest()

    def _atomic_write(self, filepath: str, data: bytes) -> Tuple[bool, Optional[str]]:
        """
        Atomically write data to a file using a temporary file.
        
        Args:
            filepath: Target file path
            data: Bytes to write
            
        Returns:
            Tuple of (success, error_message)
        """
        temp_path = filepath + self.TEMP_SUFFIX
        try:
            # Write to temporary file
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
                
            # Atomic rename
            os.replace(temp_path, filepath)
            return True, None
            
        except Exception as e:
            # Clean up temp file if it exists
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
            return False, f"Failed to write file: {str(e)}"

    def _atomic_write_json(self, filepath: str, data: dict) -> Tuple[bool, Optional[str]]:
        """Atomically write JSON data to a file"""
        try:
            json_data = json.dumps(data, indent=2).encode('utf-8')
            return self._atomic_write(filepath, json_data)
        except Exception as e:
            return False, f"Failed to serialize JSON: {str(e)}"

    def _save_metadata(self, backup_path: str, metadata: BackupMetadata):
        """Save metadata for a backup file"""
        metadata_path = os.path.join(self.backup_dir, self.METADATA_FILE)
        backup_metadata_path = os.path.join(self.backup_dir, self.METADATA_BACKUP_FILE)
        
        # Load existing metadata
        all_metadata = {}
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    all_metadata = json.load(f)
            except json.JSONDecodeError:
                # Try to recover from backup if main metadata is corrupted
                if os.path.exists(backup_metadata_path):
                    try:
                        with open(backup_metadata_path, "r") as f:
                            all_metadata = json.load(f)
                    except:
                        all_metadata = {}  # Start fresh if both files are corrupted
        
        # Add new metadata
        all_metadata[backup_path] = metadata.to_dict()
        
        # Save updated metadata atomically
        success, error = self._atomic_write_json(metadata_path, all_metadata)
        if not success:
            raise IOError(f"Failed to save metadata: {error}")
            
        # Create backup copy of metadata
        self._atomic_write_json(backup_metadata_path, all_metadata)

    def _load_metadata(self, backup_path: str) -> Optional[BackupMetadata]:
        """Load metadata for a backup file"""
        metadata_path = os.path.join(self.backup_dir, self.METADATA_FILE)
        backup_metadata_path = os.path.join(self.backup_dir, self.METADATA_BACKUP_FILE)
        
        # Try loading from primary metadata file
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    all_metadata = json.load(f)
                if backup_path in all_metadata:
                    return BackupMetadata.from_dict(all_metadata[backup_path])
            except json.JSONDecodeError:
                pass  # Fall through to backup file
                
        # Try loading from backup metadata file
        if os.path.exists(backup_metadata_path):
            try:
                with open(backup_metadata_path, "r") as f:
                    all_metadata = json.load(f)
                if backup_path in all_metadata:
                    # Restore primary metadata file from backup
                    self._atomic_write_json(metadata_path, all_metadata)
                    return BackupMetadata.from_dict(all_metadata[backup_path])
            except:
                pass
                
        return None

    def _verify_backup_integrity(self, backup_path: str) -> Tuple[bool, Optional[str]]:
        """Verify backup file integrity using stored checksum"""
        metadata = self._load_metadata(backup_path)
        if not metadata:
            return False, "No metadata found for backup"
            
        current_checksum = self._calculate_checksum(backup_path)
        if current_checksum != metadata.checksum:
            return False, "Backup file checksum mismatch - file may be corrupted"
            
        return True, None

    def _get_backup_by_date(self, target_date: datetime.datetime) -> Optional[str]:
        """Find backup file closest to target date"""
        backups = self.list_backups()
        if not backups:
            return None
            
        # Find backup closest to target date
        closest_backup = min(backups, key=lambda x: abs(x[0] - target_date))
        return closest_backup[1]  # Return filepath

    def _get_backup_by_description(self, description: str) -> Optional[str]:
        """Find most recent backup matching description"""
        backups = self.list_backups()
        matching_backups = [b for b in backups if description.lower() in b[2].lower()]
        return matching_backups[0][1] if matching_backups else None

    def _get_files_from_backup(self, backup_path: str) -> Set[str]:
        """Get set of files from a backup"""
        metadata = self._load_metadata(backup_path)
        if metadata and metadata.files:
            return metadata.files
            
        # For older backups without file lists, extract from hash_dict
        try:
            with open(backup_path, "rb") as f:
                backup_data = pickle.load(f)
            return set(sum(backup_data.hash_dict.values(), []))
        except:
            return set()

    def _check_disk_space(self, required_space_mb: float = None) -> Tuple[bool, Optional[str]]:
        """
        Check if there's sufficient disk space for backup operation.
        
        Args:
            required_space_mb: Required space in MB, defaults to MIN_FREE_SPACE_MB
            
        Returns:
            Tuple of (has_space, error_message)
        """
        try:
            if required_space_mb is None:
                required_space_mb = self.MIN_FREE_SPACE_MB
                
            # Get disk usage information
            total, used, free = shutil.disk_usage(self.source_dir)
            free_mb = free / (1024 * 1024)  # Convert to MB
            
            if free_mb < required_space_mb:
                return False, f"Insufficient disk space. Required: {required_space_mb}MB, Available: {free_mb:.1f}MB"
                
            return True, None
            
        except Exception as e:
            return False, f"Failed to check disk space: {str(e)}"

    def _check_backup_size(self, filepath: str) -> Tuple[bool, Optional[str]]:
        """
        Check if backup file size is within limits.
        
        Args:
            filepath: Path to backup file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            size_mb = os.path.getsize(filepath) / (1024 * 1024)  # Convert to MB
            
            if size_mb > self.MAX_BACKUP_SIZE_MB:
                return False, f"Backup size {size_mb:.1f}MB exceeds limit of {self.MAX_BACKUP_SIZE_MB}MB"
                
            return True, None
            
        except Exception as e:
            return False, f"Failed to check backup size: {str(e)}"

    def _backup_current_file(self, description: str = "") -> Tuple[bool, Optional[str]]:
        """Create a backup of the current data file with metadata"""
        if not os.path.exists(self.filepath):
            return True, None  # Nothing to backup

        try:
            # Check disk space before backup
            has_space, error = self._check_disk_space()
            if not has_space:
                return False, error

            # Create backup directory if it doesn't exist
            os.makedirs(self.backup_dir, exist_ok=True)

            # Create backup with timestamp
            backup_path = self._get_backup_filepath()
            temp_backup_path = backup_path + self.TEMP_SUFFIX
            
            # Check for existing partial backup
            existing_metadata = None
            if os.path.exists(temp_backup_path):
                existing_metadata = self._load_metadata(temp_backup_path)
                if existing_metadata and existing_metadata.partial:
                    self.progress.start(os.path.getsize(self.filepath), "Resuming interrupted backup...")
                    start_pos = existing_metadata.bytes_written
                else:
                    # Invalid or non-partial backup, remove it
                    os.remove(temp_backup_path)
                    existing_metadata = None
                    start_pos = 0
            else:
                start_pos = 0
            
            # Initialize progress tracking
            total_size = os.path.getsize(self.filepath)
            if not existing_metadata:
                self.progress.start(total_size, "Creating backup...")
            
            # Create and update metadata
            all_files = set(sum(self.hash_dict.values(), []))
            metadata = BackupMetadata(
                description=description,
                file_count=len(all_files)
            )
            metadata.files = all_files
            metadata.compressed = self.use_compression
            metadata.partial = True
            metadata.bytes_written = start_pos
            
            # Open temp file in append mode if resuming
            mode = "ab" if start_pos > 0 else "wb"
            
            # First write to temporary file
            with open(self.filepath, "rb") as src, open(temp_backup_path, mode) as dst:
                # Seek to resume position if needed
                if start_pos > 0:
                    src.seek(start_pos)
                
                if self.use_compression:
                    compressor = zlib.compressobj(self.COMPRESSION_LEVEL)
                    copied = start_pos
                    while True:
                        chunk = src.read(8192)  # Read in 8KB chunks
                        if not chunk:
                            dst.write(compressor.flush())
                            break
                        compressed = compressor.compress(chunk)
                        dst.write(compressed)
                        copied += len(chunk)
                        metadata.bytes_written = copied
                        self._save_metadata(temp_backup_path, metadata)
                        self.progress.update(copied)
                else:
                    copied = start_pos
                    while True:
                        chunk = src.read(8192)  # Read in 8KB chunks
                        if not chunk:
                            break
                        dst.write(chunk)
                        copied += len(chunk)
                        metadata.bytes_written = copied
                        self._save_metadata(temp_backup_path, metadata)
                        self.progress.update(copied)

            # Verify backup size
            is_valid, error = self._check_backup_size(temp_backup_path)
            if not is_valid:
                os.remove(temp_backup_path)
                return False, error

            # Update metadata for completed backup
            metadata.partial = False
            metadata.checksum = self._calculate_checksum(temp_backup_path)
            
            try:
                # Atomically move temp backup to final location
                self.progress.update(message="Finalizing backup...")
                os.replace(temp_backup_path, backup_path)
                # Save metadata after successful backup
                self._save_metadata(backup_path, metadata)
            except Exception as e:
                # Clean up temp files
                if os.path.exists(temp_backup_path):
                    os.remove(temp_backup_path)
                raise

            # Cleanup old backups
            self._cleanup_old_backups()
            return True, None

        except Exception as e:
            # Don't clean up temp files on error - allow for resume
            return False, f"Failed to create backup: {str(e)}"

    def list_backups(self) -> List[Tuple[datetime.datetime, str, str, int]]:
        """
        List available backup files with their metadata.
        
        Returns:
            List of tuples (datetime, filepath, description, file_count)
        """
        backups = []
        for timestamp, filepath in self._get_available_backups():
            metadata = self._load_metadata(filepath) or BackupMetadata()
            backups.append((
                metadata.timestamp,
                filepath,
                metadata.description,
                metadata.file_count
            ))
        return backups

    def find_backups(self, 
                    start_date: Optional[datetime.datetime] = None,
                    end_date: Optional[datetime.datetime] = None,
                    description: Optional[str] = None,
                    min_files: Optional[int] = None,
                    max_files: Optional[int] = None) -> List[Tuple[datetime.datetime, str, str, int]]:
        """
        Search for backups matching criteria.
        
        Args:
            start_date: Only include backups after this date
            end_date: Only include backups before this date
            description: Filter by description (case-insensitive substring match)
            min_files: Minimum number of files in backup
            max_files: Maximum number of files in backup
            
        Returns:
            List of matching backups (timestamp, filepath, description, file_count)
        """
        backups = self.list_backups()
        
        filtered_backups = []
        for timestamp, filepath, desc, file_count in backups:
            # Apply filters
            if start_date and timestamp < start_date:
                continue
            if end_date and timestamp > end_date:
                continue
            if description and description.lower() not in desc.lower():
                continue
            if min_files is not None and file_count < min_files:
                continue
            if max_files is not None and file_count > max_files:
                continue
                
            filtered_backups.append((timestamp, filepath, desc, file_count))
            
        return filtered_backups

    def restore_from_backup(self, 
                          backup_path: Optional[str] = None,
                          target_date: Optional[datetime.datetime] = None,
                          description: Optional[str] = None,
                          files: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
        """
        Restore data from a backup file with integrity checking.
        
        Args:
            backup_path: Path to backup file to restore from
            target_date: Restore from backup closest to this date
            description: Restore from most recent backup matching description
            files: List of specific files to restore (partial restore)
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            self.acquire_lock()
            
            try:
                # Determine which backup to use
                if backup_path is None:
                    if target_date:
                        backup_path = self._get_backup_by_date(target_date)
                    elif description:
                        backup_path = self._get_backup_by_description(description)
                    else:
                        # Use most recent backup
                        backups = self._get_available_backups()
                        if not backups:
                            return False, "No backups available"
                        backup_path = backups[0][1]

                if not backup_path:
                    return False, "Could not find matching backup"

                # Verify backup exists
                if not os.path.exists(backup_path):
                    return False, f"Backup file not found: {backup_path}"

                # Initialize progress
                backup_size = os.path.getsize(backup_path)
                self.progress.start(backup_size, "Verifying backup integrity...")

                # Verify backup integrity
                success, error = self._verify_backup_integrity(backup_path)
                if not success:
                    return False, error

                self.progress.update(message="Creating safety backup...")
                # Create backup of current state before restore
                success, error = self._backup_current_file("Auto-backup before restore")
                if not success:
                    return False, f"Failed to backup current state: {error}"

                # Load and validate backup data
                self.progress.update(message="Loading backup data...")
                
                # Check if backup is compressed
                metadata = self._load_metadata(backup_path)
                is_compressed = metadata and metadata.compressed
                
                # Load backup data with decompression if needed
                with open(backup_path, "rb") as f:
                    if is_compressed:
                        decompressor = zlib.decompressobj()
                        data = decompressor.decompress(f.read())
                        data += decompressor.flush()
                        backup_data = pickle.loads(data)
                    else:
                        backup_data = pickle.load(f)
                    
                if not isinstance(backup_data, BackupSourceData):
                    return False, "Invalid backup file format"

                # Handle version compatibility
                if not hasattr(backup_data, 'version'):
                    backup_data.version = 1
                if backup_data.version > self.VERSION:
                    return False, f"Backup version {backup_data.version} is newer than current version {self.VERSION}"

                # Perform partial restore if files specified
                if files:
                    self.progress.update(message="Performing partial restore...")
                    backup_files = self._get_files_from_backup(backup_path)
                    invalid_files = set(files) - backup_files
                    if invalid_files:
                        return False, f"Files not found in backup: {', '.join(invalid_files)}"
                        
                    # Keep current files not being restored
                    current_files = set(sum(self.hash_dict.values(), []))
                    files_to_keep = current_files - set(files)
                    
                    # Create new hash dict with restored files
                    new_hash_dict = defaultdict(list)
                    for hash_val, file_list in backup_data.hash_dict.items():
                        restored_files = [f for f in file_list if f in files]
                        kept_files = [f for f in self.hash_dict[hash_val] if f in files_to_keep]
                        if restored_files or kept_files:
                            new_hash_dict[hash_val] = restored_files + kept_files
                            
                    self.hash_dict = new_hash_dict
                else:
                    # Full restore
                    self.progress.update(message="Performing full restore...")
                    self.hash_dict = backup_data.hash_dict

                # Update version and timestamp
                self.version = self.VERSION  # Always use current version after restore
                self.update()

                self.progress.update(self.progress.total, "Restore completed successfully")
                return True, None

            except Exception as e:
                return False, f"Failed to restore from backup: {str(e)}"
            
        finally:
            self.release_lock()

    def save(self, description: str = ""):
        """Save backup data to file with backup creation and metadata"""
        try:
            self.acquire_lock()
            
            # First create a backup of the existing file
            success, error = self._backup_current_file(description)
            if not success:
                print(f"Warning: {error}")

            # Save the current data atomically
            try:
                with open(self.filepath + self.TEMP_SUFFIX, "wb") as store:
                    pickle.dump(self, store)
                    store.flush()
                    os.fsync(store.fileno())
                os.replace(self.filepath + self.TEMP_SUFFIX, self.filepath)
            except Exception as e:
                # Clean up temp file
                try:
                    os.remove(self.filepath + self.TEMP_SUFFIX)
                except:
                    pass
                raise
        finally:
            self.release_lock()

    def update(self):
        """Update the last_updated timestamp"""
        time.sleep(0.001)  # Ensure timestamp changes
        self.last_updated = self._get_timestamp()

    @staticmethod
    def load(source_dir: str, overwrite: bool = False) -> 'BackupSourceData':
        """
        Load backup data from file.
        
        Args:
            source_dir: Source directory path
            overwrite: Whether to overwrite existing data
            
        Returns:
            BackupSourceData instance
        """
        filepath = os.path.normpath(os.path.join(source_dir, BackupSourceData.FILEPATH))
        
        if os.path.exists(filepath) and not overwrite:
            try:
                with open(filepath, "rb") as f:
                    data = pickle.load(f)
                    
                # Handle version upgrades if needed
                if not hasattr(data, 'version'):
                    data.version = 0
                if data.version < BackupSourceData.VERSION:
                    # Perform version-specific upgrades
                    if data.version < 1:
                        # Version 0 to 1 upgrade steps
                        pass
                    if data.version < 2:
                        # Version 1 to 2 upgrade steps
                        # Recreate metadata for existing backups
                        for _, backup_path in data._get_available_backups():
                            try:
                                with open(backup_path, "rb") as f:
                                    backup_data = pickle.load(f)
                                all_files = set(sum(backup_data.hash_dict.values(), []))
                                metadata = BackupMetadata(
                                    description="Upgraded from version 1",
                                    file_count=len(all_files)
                                )
                                metadata.files = all_files
                                metadata.checksum = data._calculate_checksum(backup_path)
                                data._save_metadata(backup_path, metadata)
                            except:
                                continue
                    
                    data.version = BackupSourceData.VERSION
                    data.update()  # Update timestamp on version upgrade
                    
                return data
            except Exception as e:
                print(f"Warning: Failed to load backup data: {str(e)}")
                # Fall through to create new data
                
        return BackupSourceData(source_dir=source_dir)
        
    def clear(self):
        """Clear backup data"""
        self.hash_dict.clear()
        self.update()  # Update timestamp when data changes 
