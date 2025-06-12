from collections import defaultdict
import os
from typing import Dict, List
from .safe_file_ops import SafeFileOps
from .backup_modes import HashMode

class HashManager:
    """Manages file hashing and hash dictionaries for backup operations"""
    
    def __init__(self, hash_mode: HashMode):
        self.hash_mode = hash_mode
        self.hash_dict = defaultdict(list)  # hash -> list of files
        self.file_hash_cache = {}  # file -> hash cache
        
    def get_file_hash(self, filepath: str) -> str:
        """
        Get file hash based on the current hash mode.
        Caches results to avoid recalculating hashes.
        """
        if filepath in self.file_hash_cache:
            return self.file_hash_cache[filepath]
            
        if self.hash_mode == HashMode.FILENAME:
            result = str(os.path.basename(filepath))
        elif self.hash_mode == HashMode.FILENAME_AND_PARENT:
            parent_dir = os.path.basename(os.path.dirname(filepath))
            result = str(os.path.join(parent_dir, os.path.basename(filepath)))
        else:  # SHA256
            result = SafeFileOps.calculate_file_hash(filepath)
            
        self.file_hash_cache[filepath] = result
        return result
        
    def build_hash_dict(self, files: List[str]) -> Dict[str, List[str]]:
        """Build hash dictionary for a list of files"""
        result = defaultdict(list)
        for filepath in files:
            file_hash = self.get_file_hash(filepath)
            result[file_hash].append(filepath)
        return result
        
    def find_duplicates(self) -> List[List[str]]:
        """Find all duplicate files based on current hash mode"""
        duplicates = []
        for files in self.hash_dict.values():
            if len(files) > 1:
                duplicates.append(files)
        return duplicates
        
    def verify_files_match(self, source_file: str, target_file: str) -> bool:
        """Verify that two files match according to the current hash mode"""
        if not (os.path.exists(source_file) and os.path.exists(target_file)):
            return False
            
        source_hash = self.get_file_hash(source_file)
        target_hash = self.get_file_hash(target_file)
        return source_hash == target_hash
        
    def clear_cache(self):
        """Clear the hash cache"""
        self.file_hash_cache.clear() 