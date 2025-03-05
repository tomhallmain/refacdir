import os
from typing import Dict, Set, Tuple, Optional
from .safe_file_ops import SafeFileOps
from .backup_modes import BackupMode, HashMode
from .hash_manager import HashManager

class BackupState:
    """Validates and tracks backup state"""
    
    def __init__(self, mapping):
        self.mapping = mapping
        self.source_files: Set[str] = set()
        self.target_files: Set[str] = set()
        self.hash_manager = HashManager(mapping.hash_mode)
        
    def validate_source(self) -> Tuple[bool, Optional[str]]:
        """
        Validate source directory state.
        Builds list of source files and their hashes.
        """
        try:
            if not os.path.exists(self.mapping.source_dir):
                return False, f"Source directory does not exist: {self.mapping.source_dir}"
                
            for root, _, files in os.walk(self.mapping.source_dir):
                for name in files:
                    if name == "backup_mapping_data.pkl":  # Skip backup data file
                        continue
                    filepath = os.path.join(root, name)
                    if not self.mapping._is_file_excluded(filepath):
                        self.source_files.add(filepath)
                        # Pre-calculate hash if using SHA256
                        if self.mapping.hash_mode == HashMode.SHA256:
                            self.hash_manager.get_file_hash(filepath)
            return True, None
        except Exception as e:
            return False, f"Failed to validate source: {str(e)}"
            
    def validate_target(self) -> Tuple[bool, Optional[str]]:
        """
        Validate target directory state.
        Builds list of target files and their hashes.
        """
        try:
            if not os.path.exists(self.mapping.target_dir):
                return False, f"Target directory does not exist: {self.mapping.target_dir}"
                
            for root, _, files in os.walk(self.mapping.target_dir):
                for name in files:
                    filepath = os.path.join(root, name)
                    if not self.mapping._is_file_excluded(filepath):
                        self.target_files.add(filepath)
                        # Pre-calculate hash if using SHA256
                        if self.mapping.hash_mode == HashMode.SHA256:
                            self.hash_manager.get_file_hash(filepath)
            return True, None
        except Exception as e:
            return False, f"Failed to validate target: {str(e)}"
            
    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        """
        Verify integrity of backup operation based on backup mode.
        Ensures files exist in correct locations with matching hashes.
        """
        try:
            if self.mapping.mode in [BackupMode.PUSH, BackupMode.PUSH_DUPLICATES]:
                # All source files should exist in target
                for source_file in self.source_files:
                    target_file = self.mapping._build_target_path(source_file)
                    if not os.path.exists(target_file):
                        return False, f"Missing target file: {target_file}"
                    if not self.hash_manager.verify_files_match(source_file, target_file):
                        return False, f"Hash mismatch: {target_file}"
                            
            elif self.mapping.mode == BackupMode.MIRROR:
                # Source and target should be identical
                source_relative = {os.path.relpath(f, self.mapping.source_dir) 
                                 for f in self.source_files}
                target_relative = {os.path.relpath(f, self.mapping.target_dir) 
                                 for f in self.target_files}
                
                if source_relative != target_relative:
                    extra_in_source = source_relative - target_relative
                    extra_in_target = target_relative - source_relative
                    msg = []
                    if extra_in_source:
                        msg.append(f"Files missing in target: {extra_in_source}")
                    if extra_in_target:
                        msg.append(f"Extra files in target: {extra_in_target}")
                    return False, "\n".join(msg)
                    
                # Verify all files match
                for rel_path in source_relative:
                    source_file = os.path.join(self.mapping.source_dir, rel_path)
                    target_file = os.path.join(self.mapping.target_dir, rel_path)
                    if not self.hash_manager.verify_files_match(source_file, target_file):
                        return False, f"Hash mismatch: {rel_path}"
                            
            return True, None
        except Exception as e:
            return False, f"Failed to verify integrity: {str(e)}"
            
    def clear(self):
        """Clear the backup state"""
        self.source_files.clear()
        self.target_files.clear()
        self.hash_manager.clear_cache() 