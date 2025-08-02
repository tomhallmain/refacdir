import argparse
from collections import defaultdict
import hashlib
import os
import re
import sys

from refacdir.utils.utils import Utils
from refacdir.utils.logger import setup_logger

# Set up logger for duplicate remover
logger = setup_logger('duplicate_remover')

# TODO maybe option to not preserve/ignore duplicates if they exist in different subdirectories within the root

class DuplicateRemover:
    INDEX_REGEX = re.compile(r'\s\(\d+\)(.[a-z0-9]{1,5})?$') # regex to match files with indices like " (1)" or " (2)"
    NORMAL_FILE_CHARS_REGEX = re.compile(r'^[\w_\-. ]+$')
    STARTS_WITH_ALPHA_REGEX = re.compile(r'^[A-Za-z]')

    def __init__(self, name, source_folders, select_for_folder_depth=False, match_dir=False,
                 recursive=True, exclude_dirs=[], preferred_delete_dirs=[]):
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
        self.skip_exclusion_check = len(exclude_dirs) == 0
        if not self.skip_exclusion_check:
            logger.info("Excluding directories from duplicates check:")
            for d in exclude_dirs:
                full_path = self._find_full_path(d)
                if not os.path.isdir(full_path):
                    raise Exception("Invalid exclude directory: " + d)
                logger.info(full_path)
                self.exclude_dirs.append(full_path)
        if len(preferred_delete_dirs) > 0:
            logger.info("Preferring directories for deletion:")
            for d in preferred_delete_dirs:
                full_path = self._find_full_path(d)
                if not os.path.isdir(full_path):
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

    def get_file_hash(self, file_path):
        hash_obj = hashlib.md5()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def is_excluded(self, file_path):
        for d in self.exclude_dirs:
            if file_path.startswith(d):
                return True
        return False

    def find_duplicates(self):
        file_dict = defaultdict(list)
        for source_folder in self.source_folders:
            logger.debug(f"Scanning directory for duplicates: {source_folder}")
            for foldername, subfolders, filenames in os.walk(source_folder):
                if not self.recursive and foldername != source_folder: # TODO better way to handle this
                    continue
                for filename in filenames:
                    file_path = os.path.normpath(os.path.join(foldername, filename))
                    if self.skip_exclusion_check or not self.is_excluded(file_path):
                        try:
                            file_dict[self.get_file_hash(file_path)].append(file_path)
                        except Exception as e: # FileNotFound error is possible
                            logger.error(f"Error generating hash for \"{file_path}\": {e}")
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
                for file_path in duplicates_to_remove:
                    logger.info("Removing file: " + file_path)
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(f"Failed to remove file {file_path}: {e}")

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
              exclude_dir_string="", preferred_delete_dirs_string=""):
    logger.info(f"Starting duplicate removal process in directory: {directory_path}")
    exclude_dirs = Utils.get_list_from_string(exclude_dir_string)
    preferred_delete_dirs = Utils.get_list_from_string(preferred_delete_dirs_string)
    remover = DuplicateRemover("dups_main", directory_path, select_for_folder_depth=select_deepest,
                               match_dir=match_dir, recursive=recursive, 
                               exclude_dirs=exclude_dirs, preferred_delete_dirs=preferred_delete_dirs)
    remover.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Remove duplicate files in a directory.')
    parser.add_argument('dir', help='Directory to search for duplicate files')
    args = parser.parse_args()
    dups_main(args.dir)

