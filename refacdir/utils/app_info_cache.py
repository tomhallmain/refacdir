import json
import os
import shutil
import sys

from refacdir.lib.position_data import PositionData
from refacdir.utils.constants import AppInfo
from refacdir.utils.encryptor import encrypt_data_to_file, decrypt_data_from_file
from refacdir.utils.logger import setup_logger

logger = setup_logger('app_info_cache')


class AppInfoCache:
    CACHE_LOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_info_cache.enc")
    JSON_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.json")
    META_INFO_KEY = "info"
    DIRECTORIES_KEY = "directories"
    NUM_BACKUPS = 4  # Number of backup files to maintain

    def __init__(self):
        self._cache = {AppInfoCache.META_INFO_KEY: {}, AppInfoCache.DIRECTORIES_KEY: {}}
        self.load()
        self.validate()

    def store(self):
        """
        Store the cache to disk with encryption.
        Handles credential manager errors gracefully (e.g., on first run when keys don't exist yet).
        """
        try:
            cache_data = json.dumps(self._cache).encode('utf-8')
            encrypt_data_to_file(
                cache_data,
                AppInfo.SERVICE_NAME,
                AppInfo.APP_IDENTIFIER,
                AppInfoCache.CACHE_LOC
            )
        except Exception as e:
            # Check if it's a Windows Credential Manager error (credential not found)
            # This can happen on first run when keys haven't been generated yet
            # Error format: (1168, 'CredRead', 'Element not found.')
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
                logger.debug(f"Credential manager error (likely first run): {e}. Keys will be generated on next access.")
                # Don't raise - this is expected on first run
                return
            else:
                logger.error(f"Error storing cache: {e}")
                # Only raise for unexpected errors
                raise e

    def _try_load_cache_from_file(self, path):
        """Attempt to load and decrypt the cache from the given file path. Raises on failure."""
        encrypted_data = decrypt_data_from_file(
            path,
            AppInfo.SERVICE_NAME,
            AppInfo.APP_IDENTIFIER
        )
        return json.loads(encrypted_data.decode('utf-8'))

    def load(self):
        try:
            if os.path.exists(AppInfoCache.JSON_LOC):
                logger.info(f"Removing old cache file: {AppInfoCache.JSON_LOC}")
                # Get the old data first
                with open(AppInfoCache.JSON_LOC, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self.store() # store encrypted cache
                os.remove(AppInfoCache.JSON_LOC)
                return

            # Try encrypted cache and backups in order
            cache_paths = [self.CACHE_LOC] + self._get_backup_paths()
            any_exist = any(os.path.exists(path) for path in cache_paths)
            if not any_exist:
                logger.info(f"No cache file found at {self.CACHE_LOC}, creating new cache")
                return

            for path in cache_paths:
                if os.path.exists(path):
                    try:
                        self._cache = self._try_load_cache_from_file(path)
                        # Only rotate backups if we loaded from the main file
                        if path == self.CACHE_LOC:
                            message = f"Loaded cache from {self.CACHE_LOC}"
                            rotated_count = self._rotate_backups()
                            if rotated_count > 0:
                                message += f", rotated {rotated_count} backups"
                            logger.info(message)
                        else:
                            logger.warning(f"Loaded cache from backup: {path}")
                        return
                    except Exception as e:
                        logger.error(f"Failed to load cache from {path}: {e}")
                        continue
            # If we get here, all attempts failed (but at least one file existed)
            raise Exception(f"Failed to load cache from all locations: {cache_paths}")
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            raise e

    def validate(self):
        return True

    def _get_directory_info(self):
        if AppInfoCache.DIRECTORIES_KEY not in self._cache:
            self._cache[AppInfoCache.DIRECTORIES_KEY] = {}
        return self._cache[AppInfoCache.DIRECTORIES_KEY]

    def set(self, key, value):
        if AppInfoCache.META_INFO_KEY not in self._cache:
            self._cache[AppInfoCache.META_INFO_KEY] = {}
        self._cache[AppInfoCache.META_INFO_KEY][key] = value

    def get(self, key, default_val=None):
        if AppInfoCache.META_INFO_KEY not in self._cache or key not in self._cache[AppInfoCache.META_INFO_KEY]:
            return default_val
        return self._cache[AppInfoCache.META_INFO_KEY][key]

    def set_display_position(self, master):
        """Store the main window's display position and size."""
        self.set("display_position", PositionData.from_master(master).to_dict())
    
    def set_virtual_screen_info(self, master):
        """Store the virtual screen information."""
        try:
            self.set("virtual_screen_info", PositionData.from_master_virtual_screen(master).to_dict())
        except Exception as e:
            logger.warning(f"Failed to store virtual screen info: {e}")
    
    def get_virtual_screen_info(self):
        """Get the cached virtual screen info, returns None if not set or invalid."""
        virtual_screen_data = self.get("virtual_screen_info")
        if not virtual_screen_data:
            return None
        return PositionData.from_dict(virtual_screen_data)

    def get_display_position(self):
        """Get the cached display position, returns None if not set or invalid."""
        position_data = self.get("display_position")
        if not position_data:
            return None
        return PositionData.from_dict(position_data)

    # UI Settings persistence methods
    
    def set_ui_theme(self, is_dark: bool):
        """Store the UI theme preference (True for dark, False for light)."""
        self.set("ui_theme_dark", is_dark)
    
    def get_ui_theme(self, default=True):
        """Get the cached UI theme preference, returns default if not set."""
        return self.get("ui_theme_dark", default_val=default)
    
    def set_operation_settings(self, settings: dict):
        """
        Store operation settings (checkboxes state).
        
        Args:
            settings: Dict with keys: 'recur', 'test_mode', 'skip_confirm', 'only_observers'
        """
        self.set("operation_settings", settings)
    
    def get_operation_settings(self):
        """
        Get the cached operation settings.
        
        Returns:
            dict with keys: 'recur', 'test_mode', 'skip_confirm', 'only_observers'
            Returns dict with all False if not set.
        """
        default_settings = {
            'recur': False,
            'test_mode': False,
            'skip_confirm': False,
            'only_observers': False
        }
        cached = self.get("operation_settings", default_val=default_settings)
        # Merge with defaults to ensure all keys exist
        return {**default_settings, **cached}
    
    def set_selected_configs(self, configs: dict):
        """
        Store which configurations are selected/enabled.
        
        Args:
            configs: Dict mapping config path (str) to enabled state (bool)
        """
        self.set("selected_configs", configs)
    
    def get_selected_configs(self):
        """
        Get the cached selected configurations.
        
        Returns:
            dict mapping config path to enabled state, or empty dict if not set.
        """
        return self.get("selected_configs", default_val={})
    
    def set_search_filter(self, filter_text: str):
        """Store the search filter text."""
        self.set("search_filter", filter_text)
    
    def get_search_filter(self):
        """Get the cached search filter text, returns empty string if not set."""
        return self.get("search_filter", default_val="")

    @staticmethod
    def normalize_directory_key(directory):
        return os.path.normpath(os.path.abspath(directory))

    def export_as_json(self, json_path=None):
        """Export the current cache as a JSON file (not encrypted)."""
        if json_path is None:
            json_path = AppInfoCache.JSON_LOC
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
        return json_path

    def clear_directory_cache(self, base_dir: str) -> None:
        """
        Clear all cache entries related to a specific base directory.
        This includes secondary_base_dirs, per-directory settings, and meta base_dir.
        """
        normalized_base_dir = self.normalize_directory_key(base_dir)
        
        # Remove from secondary_base_dirs
        try:
            secondary_base_dirs = self.get("secondary_base_dirs", default_val=[])
            if base_dir in secondary_base_dirs:
                secondary_base_dirs = [d for d in secondary_base_dirs if d != base_dir]
                self.set("secondary_base_dirs", secondary_base_dirs)
        except Exception as e:
            logger.error(f"Error updating secondary base dirs during delete: {e}")

        # Clear per-directory cached settings (favorites, cursors, etc.)
        try:
            directory_info = self._get_directory_info()
            if normalized_base_dir in directory_info:
                del directory_info[normalized_base_dir]
        except Exception as e:
            logger.error(f"Error clearing directory cache during delete: {e}")

        # If this was the stored main base_dir, clear it
        try:
            if self.get("base_dir") == base_dir:
                self.set("base_dir", "")
        except Exception as e:
            logger.error(f"Error clearing meta base_dir during delete: {e}")

    def _get_backup_paths(self):
        """Get list of backup file paths in order of preference"""
        backup_paths = []
        for i in range(1, self.NUM_BACKUPS + 1):
            index = "" if i == 1 else f"{i}"
            path = f"{self.CACHE_LOC}.bak{index}"
            backup_paths.append(path)
        return backup_paths

    def _rotate_backups(self):
        """Rotate backup files: move each backup to the next position, oldest gets overwritten"""
        backup_paths = self._get_backup_paths()
        rotated_count = 0
        
        # Remove the oldest backup if it exists
        if os.path.exists(backup_paths[-1]):
            os.remove(backup_paths[-1])
        
        # Shift backups: move each backup to the next position
        for i in range(len(backup_paths) - 1, 0, -1):
            if os.path.exists(backup_paths[i - 1]):
                shutil.copy2(backup_paths[i - 1], backup_paths[i])
                rotated_count += 1
        
        # Copy main cache to first backup position
        shutil.copy2(self.CACHE_LOC, backup_paths[0])
        
        return rotated_count

app_info_cache = AppInfoCache()
