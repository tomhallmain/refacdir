from enum import Enum

class FileMode(Enum):
    """File operation modes for backup"""
    FILES_AND_DIRS = 0  # Process both files and directories
    DIRS_ONLY = 1      # Process only directories

class HashMode(Enum):
    """Hash modes for file comparison"""
    FILENAME = 0                # Compare by filename only
    FILENAME_AND_PARENT = 1     # Compare by filename and parent directory
    SHA256 = 2                 # Compare by SHA256 hash of contents

class BackupMode(Enum):
    """Backup operation modes"""
    PUSH_AND_REMOVE = 0    # Copy files to target and remove from source
    PUSH = 1              # Copy files to target
    PUSH_DUPLICATES = 2   # Copy files to target, allowing duplicates
    MIRROR = 3           # Make target identical to source
    MIRROR_DUPLICATES = 4 # Make target identical to source, allowing duplicates

class FailureType(str, Enum):
    """Types of failures that can occur during backup"""
    MOVE_FILE = "move_file"
    REMOVE_SOURCE_FILE = "remove_source_file"
    REMOVE_SOURCE_FILE_TARGET_NOEXIST = "remove_source_file_target_noexist"
    REMOVE_STALE_FILE = "remove_stale_file"
    REMOVE_STALE_DIRECTORY = "remove_stale_directory"
    BACKUP_OPERATION = "backup_operation"
    HASH_VERIFICATION = "hash_verification"
    DIRECTORY_OPERATION = "directory_operation" 