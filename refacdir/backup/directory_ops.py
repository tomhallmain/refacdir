import os
import shutil
from typing import List, Set, Dict, Optional
from .safe_file_ops import SafeFileOps

class DirectoryOps:
    """Utility class for directory operations with safety checks"""
    
    @staticmethod
    def ensure_dir_exists(directory: str) -> None:
        """Create directory if it doesn't exist"""
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
    
    @staticmethod
    def is_subpath(parent: str, child: str) -> bool:
        """Check if child path is a subpath of parent path"""
        parent = os.path.abspath(parent)
        child = os.path.abspath(child)
        return os.path.commonpath([parent]) == os.path.commonpath([parent, child])
    
    @staticmethod
    def list_files(directory: str, recursive: bool = True) -> List[str]:
        """List all files in directory, optionally recursively"""
        files = []
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                files.append(file_path)
            if not recursive:
                break
        return files
    
    @staticmethod
    def get_relative_path(base_path: str, full_path: str) -> str:
        """Get path relative to base path"""
        return os.path.relpath(full_path, base_path)
    
    @staticmethod
    def build_target_path(source_path: str, source_base: str, target_base: str) -> str:
        """Build target path by replacing source base with target base"""
        rel_path = DirectoryOps.get_relative_path(source_base, source_path)
        return os.path.join(target_base, rel_path)
    
    @staticmethod
    def copy_file_safe(source: str, target: str, overwrite: bool = False) -> bool:
        """Copy file with safety checks"""
        if not os.path.exists(source):
            return False
            
        if os.path.exists(target) and not overwrite:
            return False
            
        target_dir = os.path.dirname(target)
        DirectoryOps.ensure_dir_exists(target_dir)
        
        return SafeFileOps.copy_file(source, target)
    
    @staticmethod
    def move_file_safe(source: str, target: str, overwrite: bool = False) -> bool:
        """Move file with safety checks"""
        if not os.path.exists(source):
            return False
            
        if os.path.exists(target) and not overwrite:
            return False
            
        target_dir = os.path.dirname(target)
        DirectoryOps.ensure_dir_exists(target_dir)
        
        return SafeFileOps.move_file(source, target)
    
    @staticmethod
    def remove_empty_dirs(directory: str, remove_root: bool = False) -> None:
        """Remove empty directories recursively"""
        if not os.path.isdir(directory):
            return
            
        # Remove empty subdirectories
        files = os.listdir(directory)
        for f in files:
            fullpath = os.path.join(directory, f)
            if os.path.isdir(fullpath):
                DirectoryOps.remove_empty_dirs(fullpath, True)
                
        # If directory is empty, delete it
        files = os.listdir(directory)
        if len(files) == 0 and remove_root:
            os.rmdir(directory) 