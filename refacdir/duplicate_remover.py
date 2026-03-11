import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import os
import re
import stat
import sys
from typing import Iterable

from refacdir.utils.app_info_cache import app_info_cache
from refacdir.utils.utils import Utils
from refacdir.utils.logger import setup_logger

# Set up logger for duplicate remover
logger = setup_logger('duplicate_remover')

# TODO maybe option to not preserve/ignore duplicates if they exist in different subdirectories within the root

class DuplicateRemoverHashCache:
    HASH_CACHE_KEY = "cache"
    HASH_CACHE_LAST_UPDATE_KEY = "last_update"
    HASH_CACHE_META_KEY = "duplicate_remover_hash_cache"

    def __init__(self):
        self.cache_map = {}
        self.cached_hashes_for_source = {}
        self.last_cache_update_timestamp = None
        self.replacement_cache_for_source = {}

    def relative_path(self, source_folder, file_path):
        return os.path.normpath(os.path.relpath(file_path, source_folder))

    def normalize_directory_key(self, directory):
        return os.path.normpath(os.path.abspath(directory))

    def get_hash_cache(self):
        try:
            loaded_cache = app_info_cache.get(self.HASH_CACHE_META_KEY, default_val={})
            self.cache_map = loaded_cache if isinstance(loaded_cache, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load duplicate remover hash cache: {e}")
            self.cache_map = {}
        return self.cache_map

    def read_hash_cache_entry(self, source_folder):
        source_folder_key = self.normalize_directory_key(source_folder)
        directory_data = self.cache_map.get(source_folder_key, {})
        self.replacement_cache_for_source = {}
        if not isinstance(directory_data, dict):
            self.cached_hashes_for_source = {}
            self.last_cache_update_timestamp = None
            return self.cached_hashes_for_source
        cache = directory_data.get(self.HASH_CACHE_KEY, {})
        last_update = directory_data.get(self.HASH_CACHE_LAST_UPDATE_KEY)
        self.cached_hashes_for_source = cache if isinstance(cache, dict) else {}
        try:
            self.last_cache_update_timestamp = datetime.fromisoformat(last_update).timestamp() if last_update else None
        except Exception:
            self.last_cache_update_timestamp = None
        return self.cached_hashes_for_source

    def write_hash_cache_entry(self, source_folder):
        source_folder_key = self.normalize_directory_key(source_folder)
        existing = self.cache_map.get(source_folder_key, {})
        if not isinstance(existing, dict):
            existing = {}
        self.cache_map[source_folder_key] = {
            **existing,
            self.HASH_CACHE_KEY: dict(self.replacement_cache_for_source),
            self.HASH_CACHE_LAST_UPDATE_KEY: datetime.now().astimezone().isoformat()
        }

    def cleanup_hash_cache_entries(self, source_folders):
        active_keys = set(self.normalize_directory_key(d) for d in source_folders)
        stale_hash_cache_keys = []
        for directory_key, directory_data in self.cache_map.items():
            if not isinstance(directory_data, dict):
                continue
            if self.HASH_CACHE_KEY not in directory_data:
                continue
            if directory_key not in active_keys:
                stale_hash_cache_keys.append(directory_key)
        for stale_key in stale_hash_cache_keys:
            del self.cache_map[stale_key]

    def get_file_hash(self, source_folder, file_path, file_mtime, use_hash_cache):
        rel_path = self.relative_path(source_folder, file_path)
        if (use_hash_cache and
            rel_path in self.cached_hashes_for_source and
            self.last_cache_update_timestamp is not None and
            file_mtime is not None and
            file_mtime <= self.last_cache_update_timestamp):
            file_hash = self.cached_hashes_for_source[rel_path]
        else:
            hash_obj = hashlib.md5()
            with open(file_path, 'rb') as file:
                for chunk in iter(lambda: file.read(4096), b""):
                    hash_obj.update(chunk)
            file_hash = hash_obj.hexdigest()
        if use_hash_cache:
            self.replacement_cache_for_source[rel_path] = file_hash
        return file_hash

    def persist_hash_cache(self):
        app_info_cache.set(self.HASH_CACHE_META_KEY, self.cache_map)
        app_info_cache.store()

    def finalize_and_persist(self, source_folders):
        try:
            self.cleanup_hash_cache_entries(source_folders)
            self.persist_hash_cache()
        except Exception as e:
            logger.error(f"Failed to persist hash cache updates: {e}")


class DuplicateRemover:
    INDEX_REGEX = re.compile(r'\s\(\d+\)(.[a-z0-9]{1,5})?$') # regex to match files with indices like " (1)" or " (2)"
    NORMAL_FILE_CHARS_REGEX = re.compile(r'^[\w_\-. ]+$')
    STARTS_WITH_ALPHA_REGEX = re.compile(r'^[A-Za-z]')

    def __init__(self, name, source_folders, select_for_folder_depth=False, match_dir=False,
                 recursive=True, exclude_dirs=[], preferred_delete_dirs=[], skip_confirm=False,
                 app_actions=None, use_hash_cache=True):
        logger.info(f"Initializing duplicate remover: {name}")
        self.name = name
        self.source_folders = []
        for source_folder in source_folders:
            self.source_folders.append(os.path.abspath(source_folder))
        self.duplicates = {}
        self.select_for_folder_depth = select_for_folder_depth
        self.match_dir = match_dir
        self.recursive = recursive
        self.dir_separator_char = "\\" if sys.platform.startswith("win") else "/"
        self.exclude_dirs = []
        self.preferred_delete_dirs = []
        self.skip_confirm = skip_confirm
        self.app_actions = app_actions
        self.use_hash_cache = use_hash_cache
        self.hash_cache = DuplicateRemoverHashCache()
        self.skip_exclusion_check = len(exclude_dirs) == 0
        if not self.skip_exclusion_check:
            logger.info("Excluding directories from duplicates check:")
            for d in exclude_dirs:
                full_path = self._find_full_path(d)
                if not Utils.isdir_with_retry(full_path):
                    raise Exception("Invalid exclude directory: " + d)
                logger.info(full_path)
                self.exclude_dirs.append(full_path)
        if len(preferred_delete_dirs) > 0:
            logger.info("Preferring directories for deletion:")
            for d in preferred_delete_dirs:
                full_path = self._find_full_path(d)
                if not Utils.isdir_with_retry(full_path):
                    raise Exception("Invalid preferred delete directory: " + d)
                logger.info(full_path)
                self.preferred_delete_dirs.append(full_path)

    def _find_full_path(self, dirname):
        if "{{USER_HOME}}" in dirname:
            dirname = dirname.replace("{{USER_HOME}}", os.path.expanduser("~"))
        if os.path.abspath(dirname) == dirname:
            return dirname
        for d in self.source_folders:
            full_path = os.path.join(os.path.abspath(d), dirname)
            if os.path.isdir(full_path):
                return full_path
        return ""

    def run(self):
        logger.info(f"Running duplicate removal for: {self.source_folders}")
        if self.find_duplicates():
            if self.skip_confirm:
                logger.info("skip_confirm set. Removing all duplicates without prompt.")
                self.handle_duplicates(testing=False, skip_confirm=True)
                return

            if self.app_actions and hasattr(self.app_actions, "review_duplicates"):
                review_payload = self.build_review_payload()
                if review_payload.get("total_duplicate_files", 0) == 0:
                    logger.info("No duplicates found after review payload generation.")
                    return
                decision = self.app_actions.review_duplicates(review_payload)
                action = (decision or {}).get("action", "cancel")
                selected_files = set((decision or {}).get("files", []))
                if action == "remove_all":
                    self.remove_files(self.flatten_duplicate_files())
                    return
                if action == "remove_selected":
                    self.remove_files(selected_files)
                    return
                logger.info("Duplicate review cancelled by user.")
                return

            self.handle_duplicates(testing=True)
            confirm = input("Confirm all duplicates removal (Y/n): ")
            if confirm.lower().strip() == "y":
                logger.info("User confirmed removal of all duplicates")
                self.handle_duplicates(testing=False)
                return
            logger.info("No change made.")
            confirm = input("Remove duplicates with confirmation one by one? (Y/n): ")
            if confirm.lower().strip() == "y":
                logger.info("User chose to remove duplicates with individual confirmation")
                self.handle_duplicates(testing=False, skip_confirm=False)
                return
            logger.info("No change made.")
            confirm_report = input("Save duplicates report? (Y/n): ")
            if confirm_report.lower() == "y":
                logger.info("User chose to save duplicates report")
                self.save_report()
        else:
            logger.info("No duplicates found.")

    def _remove_index_suffix(self, basename_no_ext: str) -> str:
        return re.sub(r'\s\(\d+\)$', '', basename_no_ext)

    def is_obvious_index_duplicate(self, keep_file: str, duplicate_file: str) -> bool:
        keep_base, keep_ext = os.path.splitext(os.path.basename(keep_file))
        dup_base, dup_ext = os.path.splitext(os.path.basename(duplicate_file))
        if keep_ext.lower() != dup_ext.lower():
            return False
        keep_norm = self._remove_index_suffix(keep_base).strip().lower()
        dup_norm = self._remove_index_suffix(dup_base).strip().lower()
        if not keep_norm or not dup_norm:
            return False
        return keep_norm == dup_norm

    def build_review_payload(self) -> dict:
        groups = []
        obvious_count = 0
        non_obvious_count = 0

        for file_list in self.duplicates.values():
            keep_file, remove_files = self.determine_duplicates(file_list)
            if self.match_dir and len(remove_files) == 0:
                continue
            obvious = all(self.is_obvious_index_duplicate(keep_file, f) for f in remove_files)
            if obvious:
                obvious_count += len(remove_files)
            else:
                non_obvious_count += len(remove_files)
            groups.append({
                "keep_file": keep_file,
                "remove_files": remove_files,
                "obvious": obvious,
            })

        return {
            "total_duplicate_files": obvious_count + non_obvious_count,
            "obvious_count": obvious_count,
            "non_obvious_count": non_obvious_count,
            "groups": groups,
        }

    def flatten_duplicate_files(self) -> list[str]:
        payload = self.build_review_payload()
        files = []
        for group in payload["groups"]:
            files.extend(group["remove_files"])
        return files

    def remove_files(self, files: Iterable[str]):
        for file_path in files:
            logger.info("Removing file: " + file_path)
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Failed to remove file {file_path}: {e}")

    def is_excluded(self, file_path):
        for d in self.exclude_dirs:
            if file_path.startswith(d):
                return True
        return False

    def _iter_files_with_mtime(self, source_folder):
        stack = [source_folder]
        while stack:
            folder = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        file_path = os.path.normpath(entry.path)
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                            mode = entry_stat.st_mode
                            if stat.S_ISDIR(mode):
                                if self.recursive and (self.skip_exclusion_check or not self.is_excluded(file_path)):
                                    stack.append(file_path)
                                continue
                            if not stat.S_ISREG(mode):
                                continue
                            if not self.skip_exclusion_check and self.is_excluded(file_path):
                                continue
                            file_mtime = entry_stat.st_mtime
                            yield file_path, file_mtime
                        except Exception as e:
                            logger.error(f"Error reading file info for \"{file_path}\": {e}")
            except Exception as e:
                logger.error(f"Error scanning directory \"{folder}\": {e}")

    def find_duplicates(self):
        file_dict = defaultdict(list)
        if self.use_hash_cache:
            self.hash_cache.get_hash_cache()
        for source_folder in self.source_folders:
            logger.debug(f"Scanning directory for duplicates: {source_folder}")
            if self.use_hash_cache:
                self.hash_cache.read_hash_cache_entry(source_folder)
            for file_path, file_mtime in self._iter_files_with_mtime(source_folder):
                try:
                    file_hash = self.hash_cache.get_file_hash(source_folder, file_path, file_mtime, self.use_hash_cache)
                    file_dict[file_hash].append(file_path)
                except Exception as e: # FileNotFound error is possible
                    logger.error(f"Error generating hash for \"{file_path}\": {e}")
            if self.use_hash_cache:
                self.hash_cache.write_hash_cache_entry(source_folder)
        if self.use_hash_cache:
            self.hash_cache.finalize_and_persist(self.source_folders)
        self.duplicates = {k: v for k, v in file_dict.items() if len(v) > 1}
        if self.has_duplicates():
            logger.info(f"Found {len(self.duplicates)} sets of duplicate files")
        return self.has_duplicates()

    def has_duplicates(self):
        return len(self.duplicates) > 0

    def determine_duplicates(self, file_list):
        best_duplicate = self.select_best_duplicate(file_list)
        best_duplicate_dir = os.path.dirname(best_duplicate) if self.match_dir else ""
        def is_valid_duplicate(f, best_duplicate):
            if f == best_duplicate:
                return False
            return not self.match_dir or os.path.dirname(f) == best_duplicate_dir
        duplicates_to_remove = [f for f in file_list if is_valid_duplicate(f, best_duplicate)]
        return best_duplicate, duplicates_to_remove

    def handle_duplicates(self, testing, skip_confirm=True):
        for file_list in self.duplicates.values():
            best_duplicate, duplicates_to_remove = self.determine_duplicates(file_list)
            if self.match_dir and len(duplicates_to_remove) == 0:
                continue
            if testing:
                logger.info("Keeping file:               " + best_duplicate)
                logger.info("Removing duplicate files: " + str(duplicates_to_remove))
            else:
                if not skip_confirm:
                    logger.info("Keeping file:               " + best_duplicate)
                    logger.info("Removing duplicate files: " + str(duplicates_to_remove))
                    confirm = input(f"OK to remove? (Y/n): ")
                    if confirm.lower() != "y":
                        logger.info("User skipped removal of duplicates")
                        continue
                self.remove_files(duplicates_to_remove)

    def is_preferred_delete_file(self, file_path):
        for d in self.preferred_delete_dirs:
            if file_path == d or file_path.startswith(d):
                return True
        return False

    def select_best_duplicate(self, file_list):
        filtered_list = list(file_list)
        # only keep files that are not in the preferred delete dirs, unless there are none
        if len(self.preferred_delete_dirs) > 0:
            for f in filtered_list[:]:
                if self.is_preferred_delete_file(f):
                    filtered_list.remove(f)
            if len(filtered_list) == 1:
                return filtered_list[0]
            elif len(filtered_list) == 0:
                filtered_list = list(file_list)
        # sort the file_list by the creation time
        filtered_list.sort(key=lambda x: os.path.getctime(x))
        best_candidates = filtered_list[:]
        # iterate over the sorted file_list to find the best
        if self.select_for_folder_depth:
            highest_dir_separators = 0
            for f in best_candidates:
                separator_count = len(f.split(self.dir_separator_char)) - 1
                if separator_count > highest_dir_separators:
                    highest_dir_separators = separator_count
            best_candidates = list(filter(lambda f: len(f.split(self.dir_separator_char)) - 1 == highest_dir_separators, best_candidates))
            if len(best_candidates) == 1:
                return best_candidates[0]
        candidate_dict = defaultdict(int)
        for f in best_candidates:
            basename = os.path.basename(f)
            index_not_present = DuplicateRemover.INDEX_REGEX.search(basename) is None
            normal_file_chars = DuplicateRemover.NORMAL_FILE_CHARS_REGEX.match(basename) is not None
            starts_with_alpha = DuplicateRemover.STARTS_WITH_ALPHA_REGEX.search(basename) is not None
            if index_not_present and normal_file_chars and starts_with_alpha:
                return f
            count = sum([index_not_present, normal_file_chars, starts_with_alpha])
            candidate_dict[f] = count
        highest_count = max(candidate_dict.values())
        for f, count in candidate_dict.items():
            if count == highest_count:
                return f
        raise Exception("Impossible case")

    def save_report(self):
        logger.info("Generating duplicates report")
        # Create a list of tuples with best duplicate file and its duplicates
        duplicates_list = [(self.select_best_duplicate(files), files) for files in self.duplicates.values()]
        # Sort the list based on the filename of the best duplicate
        sorted_duplicates_list = sorted(duplicates_list, key=lambda x: os.path.basename(x[0]))
        # Create a report
        report_path = os.path.join(self.source_folders[0], 'duplicates_report.txt')
        with open(report_path, 'w') as f:
            f.write(f"DUPLICATES REPORT FOR DIRS: {self.source_folders}\n")
            for best, duplicates in sorted_duplicates_list:
                f.write(f'Best duplicate: {best}\n')
                f.write('Duplicates to be removed:\n')
                for duplicate in duplicates:
                    if duplicate != best:
                        f.write(f'{duplicate}\n')
                f.write('\n')
        logger.info(f'Report saved at {report_path}')

def dups_main(directory_path=".", select_deepest=False, match_dir=False, recursive=True, 
              exclude_dir_string="", preferred_delete_dirs_string="", use_hash_cache=True):
    logger.info(f"Starting duplicate removal process in directory: {directory_path}")
    exclude_dirs = Utils.get_list_from_string(exclude_dir_string)
    preferred_delete_dirs = Utils.get_list_from_string(preferred_delete_dirs_string)
    remover = DuplicateRemover("dups_main", directory_path, select_for_folder_depth=select_deepest,
                               match_dir=match_dir, recursive=recursive, 
                               exclude_dirs=exclude_dirs, preferred_delete_dirs=preferred_delete_dirs,
                               use_hash_cache=use_hash_cache)
    remover.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Remove duplicate files in a directory.')
    parser.add_argument('dir', help='Directory to search for duplicate files')
    args = parser.parse_args()
    dups_main(args.dir)

