import os
import shutil
import hashlib
import tempfile
import datetime
import sys
from typing import Optional, Tuple

if sys.platform == "win32":
    import win32file
    import pywintypes

class SafeFileOps:
    """Provides atomic file operations with verification for backup operations"""
    
    @staticmethod
    def calculate_file_hash(file_path: str, chunk_size: int = 65536) -> str:
        """Calculate SHA256 hash of a file in chunks"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    
    @staticmethod
    def verify_files_match(source_path: str, target_path: str) -> bool:
        """Verify that two files have identical content using SHA256"""
        if not (os.path.exists(source_path) and os.path.exists(target_path)):
            return False
            
        if os.path.getsize(source_path) != os.path.getsize(target_path):
            return False
            
        return SafeFileOps.calculate_file_hash(source_path) == SafeFileOps.calculate_file_hash(target_path)
    
    @staticmethod
    def atomic_copy(source_path: str, target_path: str, verify: bool = True) -> Tuple[bool, Optional[str]]:
        """
        Perform an atomic copy operation with verification.
        
        Args:
            source_path: Path to source file
            target_path: Path to target file
            verify: Whether to verify the copy using SHA256
            
        Returns:
            Tuple of (success, error_message)
        """
        if not os.path.exists(source_path):
            return False, f"Source file does not exist: {source_path}"
            
        # Create target directory if it doesn't exist
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
            
        # Create temporary file in the same directory as target
        temp_fd, temp_path = tempfile.mkstemp(dir=target_dir)
        os.close(temp_fd)  # Close file descriptor
        
        try:
            # Copy to temporary file
            shutil.copy2(source_path, temp_path)
            
            # Verify copy if requested
            if verify:
                if not SafeFileOps.verify_files_match(source_path, temp_path):
                    os.unlink(temp_path)
                    return False, "Verification failed: copied file does not match source"
            
            # Atomic rename
            os.replace(temp_path, target_path)
            return True, None
            
        except Exception as e:
            # Clean up temporary file if it exists
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return False, str(e)
    
    @staticmethod
    def atomic_move(source_path: str, target_path: str, verify: bool = True) -> Tuple[bool, Optional[str]]:
        """
        Perform an atomic move operation with verification.
        
        Args:
            source_path: Path to source file
            target_path: Path to target file
            verify: Whether to verify the move using SHA256
            
        Returns:
            Tuple of (success, error_message)
        """
        success, error = SafeFileOps.atomic_copy(source_path, target_path, verify)
        if success:
            try:
                os.unlink(source_path)
            except Exception as e:
                # If we can't delete the source, we should roll back
                try:
                    os.unlink(target_path)
                except:
                    pass
                return False, f"Failed to remove source file after copy: {str(e)}"
        return success, error

    @staticmethod
    def copy(source_path: str, target_path: str) -> Tuple[bool, Optional[str]]:
        """
        Copy a file while preserving metadata.
        
        Args:
            source_path: Path to source file
            target_path: Path to target file
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            stat_obj = os.stat(source_path)
            creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
            modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
            
            # Use atomic copy for safety
            success, error = SafeFileOps.atomic_copy(source_path, target_path)
            if not success:
                return False, error
                
            # Update timestamps using platform-specific method
            SafeFileOps.change_fileinfo_times(target_path, creation_datetime, modification_datetime)
            
            return True, None
        except Exception as e:
            return False, str(e)
            
    @staticmethod
    def move(source_path: str, target_path: str) -> Tuple[bool, Optional[str]]:
        """
        Move a file while preserving metadata.
        
        Args:
            source_path: Path to source file
            target_path: Path to target file
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            stat_obj = os.stat(source_path)
            creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
            modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
            
            # Use atomic move for safety
            success, error = SafeFileOps.atomic_move(source_path, target_path)
            if not success:
                return False, error
                
            # Update timestamps using platform-specific method
            SafeFileOps.change_fileinfo_times(target_path, creation_datetime, modification_datetime)
            
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def change_fileinfo_times(path: str, creation_datetime: datetime.datetime, modification_datetime: Optional[datetime.datetime] = None) -> None:
        """
        Change file creation and modification times with proper OS-specific handling.
        
        Args:
            path: Path to the file
            creation_datetime: The creation time to set
            modification_datetime: The modification time to set (defaults to creation_datetime if None)
        """
        if not isinstance(creation_datetime, datetime.datetime):
            raise Exception(f"Invalid creation time: must be datetime object, got object of type {type(creation_datetime)}")
            
        if modification_datetime is None:
            modification_datetime = creation_datetime
        elif not isinstance(modification_datetime, datetime.datetime):
            raise Exception(f"Invalid modification time: must be datetime object, got object of type {type(modification_datetime)}")

        # Update modification time (works on all platforms)
        os.utime(path, (creation_datetime.timestamp(), modification_datetime.timestamp()))

        if sys.platform == "win32":
            try:
                # Open file with proper access for Windows API
                handle = win32file.CreateFile(
                    path,
                    win32file.GENERIC_WRITE,
                    0,  # No sharing
                    None,  # No security
                    win32file.OPEN_EXISTING,
                    0,  # Normal file attribute
                    0  # No template
                )

                try:
                    # Create PyTime object for the creation time
                    creation_time = pywintypes.Time(creation_datetime.timestamp())
                    
                    # Set the creation time
                    win32file.SetFileTime(handle, creation_time)
                finally:
                    # Always close the handle
                    handle.Close()
            except Exception as e:
                print(f"Warning: Failed to set creation time on Windows: {str(e)}")
        else:
            # TODO: Add specific handling for other operating systems if needed
            # Currently, only modification time is reliably settable on Unix-like systems
            pass 