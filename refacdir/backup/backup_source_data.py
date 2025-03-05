import datetime
import os
import pickle
from collections import defaultdict
from typing import Dict, List

class BackupSourceData:
    """Manages persistent backup source data"""
    
    FILEPATH = "backup_mapping_data.pkl"
    VERSION = 1  # For future compatibility

    def __init__(self, source_dir: str = "."):
        self.source_dir = source_dir
        self.filepath = os.path.normpath(os.path.join(source_dir, self.FILEPATH))
        self.hash_dict = defaultdict(list)  # hash -> list of files
        self.last_updated = datetime.datetime.now().toordinal()
        self.version = self.VERSION

    def save(self):
        """Save backup data to file"""
        with open(self.filepath, "wb") as store:
            pickle.dump(self, store)
        self.last_updated = datetime.datetime.now().toordinal()

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
                    # Perform any necessary upgrades here
                    data.version = BackupSourceData.VERSION
                    
                return data
            except Exception as e:
                print(f"Warning: Failed to load backup data: {str(e)}")
                # Fall through to create new data
                
        return BackupSourceData(source_dir=source_dir)
        
    def clear(self):
        """Clear backup data"""
        self.hash_dict.clear()
        self.last_updated = datetime.datetime.now().toordinal() 