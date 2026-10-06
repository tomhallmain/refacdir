import json
import os
import shutil
import tempfile
import threading

from refacdir.lib.position_data import PositionData
from refacdir.utils.constants import AppInfo
from refacdir.utils.encryptor import encrypt_data_to_file, decrypt_data_from_file
from refacdir.utils.logger import setup_logger

logger = setup_logger('app_info_cache')


class AppInfoCache:
    META_INFO_KEY = "info"
    DIRECTORIES_KEY = "directories"
    NUM_BACKUPS = 4  # Number of backup files to maintain
    # The refacdir package dir. REFACDIR_CACHE_DIR overrides it.
    DEFAULT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def __init__(self):
        self._lock = threading.RLock()
        self._cache = self._empty_cache()
        # Set when cache files exist but none could be read. Storing would then
        # replace the user's data with an empty cache, so store() refuses for
        # the rest of the session and the files stay as they are.
        self._store_blocked = False
        # Set while the plaintext JSON cache on disk holds data not yet in the
        # encrypted file (read by load() or written by store()'s fallback). The
        # next successful encrypted store removes it; load() prefers the JSON
        # file, so leaving it would let older data win.
        self._plaintext_pending_removal = False
        cache_dir = os.environ.get("REFACDIR_CACHE_DIR") or AppInfoCache.DEFAULT_DIR
        self._cache_loc = os.path.join(cache_dir, "app_info_cache.enc")
        self._json_loc = os.path.join(cache_dir, "app_info_cache.json")
        self.load()
        self.validate()

    @staticmethod
    def _empty_cache() -> dict:
        return {AppInfoCache.META_INFO_KEY: {}, AppInfoCache.DIRECTORIES_KEY: {}}

    def _encrypt_to_path_atomically(self, cache_data: bytes, destination: str) -> None:
        """Encrypt to a temp file beside *destination*, then rename it into place.

        Writing the destination directly truncates it first, so a crash
        mid-write would leave an unreadable cache. The temp file shares the
        destination's directory so the rename stays on one filesystem.
        """
        destination_dir = os.path.dirname(destination) or "."
        os.makedirs(destination_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".app_info_cache_", suffix=".tmp", dir=destination_dir
        )
        os.close(fd)
        try:
            encrypt_data_to_file(
                cache_data,
                AppInfo.SERVICE_NAME,
                AppInfo.APP_IDENTIFIER,
                temp_path,
            )
            os.replace(temp_path, destination)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    def _write_plaintext_atomically(self, destination: str) -> None:
        """Write the cache as plain JSON via a temp file and rename."""
        destination_dir = os.path.dirname(destination) or "."
        os.makedirs(destination_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".app_info_cache_", suffix=".tmp", dir=destination_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
            os.replace(temp_path, destination)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    def store(self) -> bool:
        """Persist the cache. Returns True if it was written encrypted.

        If encryption fails, the cache is written as plain JSON instead so no
        data is lost, and False is returned; the next successful encrypted
        store removes the JSON file. Raises if that fallback fails too.

        Returns False without writing when persistence is disabled or when
        this session's load failed (see ``_store_blocked``).
        """
        with self._lock:
            if os.environ.get("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD"):
                logger.debug(
                    "Skipping persisted app info cache store (REFACDIR_DISABLE_APP_INFO_CACHE_LOAD is set)"
                )
                return False
            if self._store_blocked:
                logger.warning(
                    f"Not storing app info cache: it failed to load this session and "
                    f"writing would replace {self._cache_loc}"
                )
                return False
            try:
                cache_data = json.dumps(self._cache).encode('utf-8')
            except Exception as e:
                raise Exception("Error compiling app info cache") from e

            try:
                self._encrypt_to_path_atomically(cache_data, self._cache_loc)
                if self._plaintext_pending_removal:
                    self._plaintext_pending_removal = False
                    if os.path.exists(self._json_loc):
                        os.remove(self._json_loc)
                        logger.info(f"Removed plaintext cache file: {self._json_loc}")
                return True
            except Exception as e:
                # A Windows Credential Manager "not found" error (1168, 'CredRead')
                # can occur the first time keys are created; the next store works.
                logger.error(f"Error encrypting app info cache: {e}")

            logger.warning(f"Falling back to plaintext app info cache: {self._json_loc}")
            try:
                self._write_plaintext_atomically(self._json_loc)
            except Exception as e:
                raise Exception("Error storing app info cache") from e
            self._plaintext_pending_removal = True
            return False

    def _try_load_cache_from_file(self, path):
        """Attempt to load and decrypt the cache from the given file path. Raises on failure."""
        encrypted_data = decrypt_data_from_file(
            path,
            AppInfo.SERVICE_NAME,
            AppInfo.APP_IDENTIFIER
        )
        return json.loads(encrypted_data.decode('utf-8'))

    def load(self):
        """Load the cache, or start empty if there is none or it cannot be read.

        Never raises: the singleton loads at import time, so an exception here
        would stop the app from starting. An unreadable cache blocks ``store``
        for the session instead.
        """
        with self._lock:
            # Pytest sets REFACDIR_DISABLE_APP_INFO_CACHE_LOAD via test/conftest.py so imports
            # like ``batch`` → ``duplicate_remover`` do not read/write encrypted cache or touch
            # crypto. ``store`` uses the same guard. Unset to exercise real persistence.
            if os.environ.get("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD"):
                logger.debug(
                    "Skipping persisted app info cache load (REFACDIR_DISABLE_APP_INFO_CACHE_LOAD is set)"
                )
                return
            try:
                if os.path.exists(self._json_loc):
                    logger.info(f"Migrating plaintext cache file to encrypted store: {self._json_loc}")
                    with open(self._json_loc, "r", encoding="utf-8") as f:
                        self._cache = json.load(f)
                    self._plaintext_pending_removal = True
                    if not self.store():
                        logger.warning(
                            f"Encrypted store failed; keeping plaintext cache file until the "
                            f"next successful encrypted store: {self._json_loc}"
                        )
                    return

                # Try encrypted cache and backups in order
                cache_paths = [self._cache_loc] + self._get_backup_paths()
                any_exist = any(os.path.exists(path) for path in cache_paths)
                if not any_exist:
                    logger.info(f"No cache file found at {self._cache_loc}, creating new cache")
                    return

                for path in cache_paths:
                    if os.path.exists(path):
                        try:
                            self._cache = self._try_load_cache_from_file(path)
                            # Only rotate backups if we loaded from the main file
                            if path == self._cache_loc:
                                message = f"Loaded cache from {self._cache_loc}"
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
                logger.error(
                    f"Error loading cache, starting with an empty one and not saving "
                    f"this session: {e}"
                )
                self._cache = self._empty_cache()
                self._store_blocked = True

    def validate(self):
        with self._lock:
            return True

    def _get_directory_info(self):
        """Get directory info dict. Must be called from within a locked context."""
        if AppInfoCache.DIRECTORIES_KEY not in self._cache:
            self._cache[AppInfoCache.DIRECTORIES_KEY] = {}
        return self._cache[AppInfoCache.DIRECTORIES_KEY]

    def set(self, key, value):
        with self._lock:
            if AppInfoCache.META_INFO_KEY not in self._cache:
                self._cache[AppInfoCache.META_INFO_KEY] = {}
            self._cache[AppInfoCache.META_INFO_KEY][key] = value

    def get(self, key, default_val=None):
        with self._lock:
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
        """Store operation settings (checkboxes state)."""
        self.set("operation_settings", settings)
    
    def get_operation_settings(self):
        """Get the cached operation settings."""
        default_settings = {
            'recur': False,
            'test_mode': False,
            'skip_confirm': False,
            'only_observers': False,
            'inactivity_shutdown_timeout_minutes': 30,
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

    def get_batch_job_history(self):
        """Return the last batch job records (newest first), max 20."""
        return self.get("batch_job_history", default_val=[])

    def set_batch_job_history(self, history):
        """Replace the full batch job history list and persist."""
        self.set("batch_job_history", history)
        self.store()

    def prepend_batch_job_record(self, record):
        """Prepend a batch job record, keeping at most 20 entries."""
        from refacdir.batch_job_history import MAX_BATCH_JOB_HISTORY

        history = self.get_batch_job_history()
        history.insert(0, record)
        self.set("batch_job_history", history[:MAX_BATCH_JOB_HISTORY])
        self.store()

    @staticmethod
    def normalize_directory_key(directory):
        return os.path.normpath(os.path.abspath(directory))

    def export_as_json(self, json_path=None):
        """Export the current cache as a JSON file (not encrypted)."""
        if json_path is None:
            json_path = self._json_loc
        with self._lock:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        return json_path

    def clear_directory_cache(self, base_dir: str) -> None:
        """
        Clear all cache entries related to a specific base directory.
        This includes secondary_base_dirs, per-directory settings, and meta base_dir.
        """
        with self._lock:
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
            path = f"{self._cache_loc}.bak{index}"
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
        shutil.copy2(self._cache_loc, backup_paths[0])
        
        return rotated_count

app_info_cache = AppInfoCache()
