import glob
import os
import re
import sys
from refacdir.utils.logger import setup_logger

# Set up logger for file renamer
logger = setup_logger('file_renamer')

def find_alpha_substring(s): 
    """
    Find a substring with high information value in a filename
    TODO maybe make this better by checking if the prior char was "_" or "-" and if not including any digits prior to the alpha char
    """
    for i, val in enumerate(s):
        if val.isalpha():
            return s[i:]
    return ""

def alpha_basename_part(basename):
    """
    Nested directories will show in the "basename" value after os.path.splittext so need to only grab the alpha substring from the true file basename
    """
    if "\\" in basename:
        last_slash_index = basename.rindex("\\")
    elif "/" in basename:
        last_slash_index = basename.rindex("/")
    else:
        alpha_str = find_alpha_substring(basename)
        return "" if alpha_str == "" else "_" + alpha_str        
    file_basename = basename[last_slash_index+1:]
    alpha_str = find_alpha_substring(file_basename)
    return "" if alpha_str == "" else "_" + alpha_str

class FileRenamer:
    TIMESTAMP_REGEX = r'_(\d{17})(?=_|$)'
    FILE_EXISTS_MESSAGE = "Cannot create a file when that file already exists"
    
    def __init__(self, root=".", test=False, log_changes=True, preserve_alpha=True, exclude_dirs=[], find_unused_filenames=False):
        if not os.path.isdir(root):
            raise Exception(f"Invalid root directory {root}")
        self.root = root
        self.test = test
        self.log_changes = log_changes
        self.preserve_alpha = preserve_alpha
        self.find_unused_filenames = find_unused_filenames
        self.exclude_dirs = []
        self.check_exclusions = len(exclude_dirs) > 0
        for d in exclude_dirs:
            if not os.path.isdir(os.path.join(root, d)):
                raise Exception(f"Invalid exclude directory: {d}")
            self.exclude_dirs.append(os.path.normpath(d))

    def set_target_dir(self, target_dir):
        self.target_dir = target_dir

    def _is_excluded(self, filepath):
        for exclude_dir in self.exclude_dirs:
            if filepath.startswith(exclude_dir):
                return True
        return False

    def _is_ineligible_file(self, filepath):
        return os.path.isdir(filepath) or (self.check_exclusions and self._is_excluded(filepath))

    def rename_file(self, filename, new_filename, count, target_dir, failures):
        rename_dir = target_dir if target_dir else os.path.dirname(filename)
        new_filename_full_path = os.path.join(rename_dir, new_filename)
        made_dirs = False
        if target_dir is not None and ("/" in new_filename or "\\" in new_filename):
            os.makedirs(os.path.dirname(new_filename_full_path), exist_ok=True)
            made_dirs = True
        if filename == new_filename_full_path:
            if False:
                logger.debug("File rename not necessary")
            return count
        try:
            if not self.test:
                os.rename(filename, new_filename_full_path)
            count += 1
            if self.log_changes:
                if self.test:
                    logger.info(f"TEST rename {filename} to {new_filename_full_path}")
                elif target_dir is not None:
                    logger.info(f"moved {filename} to {target_dir}")
                else:
                    logger.info(f"renamed {filename} to {new_filename_full_path}")
        except OSError as e:
            if FileRenamer.FILE_EXISTS_MESSAGE in str(e):
                if not made_dirs:
                    raise e
            logger.error(f"Failed to rename {filename} to {new_filename_full_path}")
            logger.error(str(e))
            failures.append(filename)
        return count

    def get_unique_filename(self, rename_dir, new_filename):
        attempts = 1
        basename, ext = os.path.splitext(os.path.basename(new_filename))
        while True:
            if not os.path.exists(os.path.join(rename_dir, f"{basename}_{attempts}{ext}")):
                return f"{basename}_{attempts}{ext}"
            attempts += 1
            if attempts > 99999:
                raise Exception("Unable to find a unique filename: " + new_filename)

    def rename_by_func_unique_filename(self, rename_func, filename, failures, count):
        attempts = 0
        increment = 0
        positive = False
        while True:
            attempts += 1
            positive = not positive
            if positive:
                increment += 1
            try:
                new_filename = rename_func(filename, increment=increment, positive=positive)
                count = self.rename_file(filename, new_filename, count, None, failures)
                return count
            except Exception as e:
                if not FileRenamer.FILE_EXISTS_MESSAGE in str(e) or attempts > 9999:
                    raise e

    def rename_by_func(self, glob_exp, rename_base, recursive=False, rename_func=lambda x: x):
        count = 0
        cwd = os.getcwd()
        if cwd != self.root:
            os.chdir(self.root)
        failures = []

        test_func = None
        if callable(glob_exp):
            logger.info("reassigning glob expression.")
            test_func = glob_exp
            glob_exp = FileRenamer.get_glob_pattern(recursive=recursive)
        else:
            glob_exp = FileRenamer.get_glob_pattern(glob_exp, recursive=recursive)

        for filename in glob.glob(glob_exp, recursive=recursive):
            if self._is_ineligible_file(filename):
                continue
            if test_func and not test_func(filename):
                continue
            new_filename = rename_func(filename)
            try:
                count = self.rename_file(filename, new_filename, count, None, failures)
            except OSError as e0:
                if not FileRenamer.FILE_EXISTS_MESSAGE in str(e0):
                    raise e0
                logger.info(f"Exact time for new filename \"{new_filename}\" matches another file, will try to find a close value.")
                count = self.rename_by_func_unique_filename(rename_func, filename, failures, count)

    def os_stat_rename_func(self, attr, rename_base):
        def rename_func(filename, increment=0, positive=True):
            basename, extension = os.path.splitext(filename)
            
            # Check if there's already a 17-digit timestamp in the filename
            # Look for pattern: _ followed by exactly 17 digits, then either _ or end of string
            timestamp_match = re.search(FileRenamer.TIMESTAMP_REGEX, basename)
            
            if timestamp_match:
                # Use existing timestamp from filename
                time_str = timestamp_match.group(1)
                # Extract everything after the timestamp (including potential alpha part)
                rest_start = timestamp_match.end()
                rest = basename[rest_start:] if rest_start < len(basename) else ""
            else:
                # Use current behavior with os.stat
                time_str = str(getattr(os.stat(filename), attr)).replace(".", "")
                while len(time_str) < 17:
                    time_str += "0"
                rest = ""
            
            # Apply increment if needed (for collision resolution)
            if increment > 0:
                time = int(time_str)
                if positive:
                    time += increment
                else:
                    time -= increment
                time_str = str(time)
                while len(time_str) < 17:
                    time_str += "0"
            
            if self.preserve_alpha:
                # For files with existing timestamp, preserve everything after it
                if timestamp_match and rest:
                    alpha_part = rest
                else:
                    alpha_part = alpha_basename_part(basename)
                new_filename = rename_base + time_str + alpha_part + extension
            else:
                new_filename = rename_base + time_str + rest + extension

            return new_filename
        return rename_func

    def rename_by_ctime(self, glob_exp, rename_base, recursive=False):
        """
        Rename all files matching given glob expression to rename_base + creation time in ms
        """
        self.rename_by_func(glob_exp, rename_base, recursive=recursive, rename_func=self.os_stat_rename_func("st_ctime", rename_base))

    def rename_by_mtime(self, glob_exp, rename_base, recursive=False):
        """
        Rename all files matching given glob expression to rename_base + modification time in ms
        """
        self.rename_by_func(glob_exp, rename_base, recursive=recursive, rename_func=self.os_stat_rename_func("st_mtime", rename_base))

    def move_files(self, glob_exp, target_dir, recursive=False, make_dirs=False):
        """
        Move all files matching given glob expression to target directory
        """
        count = 0
        cwd = os.getcwd()
        if cwd != self.root:
            os.chdir(self.root)
        failures = []

        test_func = None
        if callable(glob_exp):
            logger.info("reassigning glob expression.")
            test_func = glob_exp
            glob_exp = FileRenamer.get_glob_pattern(recursive=recursive)
        else:
            glob_exp = FileRenamer.get_glob_pattern(glob_exp, recursive=recursive)

        for filename in glob.glob(glob_exp, recursive=recursive):
            if self._is_ineligible_file(filename):
                continue
            if test_func and not test_func(filename):
                continue
            if self.root == target_dir and os.path.dirname(filename) == "":
                continue # Implies we are moving a file to the directory it is already in, so skip
            if not make_dirs and ("/" in filename or "\\" in filename):
                new_filename = os.path.basename(filename)
            else:
                new_filename = filename
            try:
                count = self.rename_file(filename, new_filename, count, target_dir, failures)
            except OSError as e:
                if not FileRenamer.FILE_EXISTS_MESSAGE in str(e) or not self.find_unused_filenames:
                    raise e
                new_filename = self.get_unique_filename(target_dir, new_filename)
                count = self.rename_file(filename, new_filename, count, target_dir, failures)

        os.chdir(cwd)
        if self.log_changes:
            self.print_summary(count, "move", glob_exp, target_dir, recursive)
        self.print_failures(failures)

    def found_files(self, mappings={}, recursive=False):
        for item in mappings:
            if callable(item):
                test_func = item
                pattern = FileRenamer.get_glob_pattern(recursive=recursive)
                for f in glob.glob(pattern, recursive=recursive, root_dir=self.root):
                    if not self._is_ineligible_file(f) and test_func(f):
                        return True
            else:
                pattern = FileRenamer.get_glob_pattern(item, recursive=recursive)
                for f in glob.glob(pattern, recursive=recursive, root_dir=self.root):
                    if not self._is_ineligible_file(f):
                        return True
        return False

    @staticmethod
    def get_glob_pattern(pattern="", recursive=False):
        if recursive:
            pattern = "**/" + pattern
        pattern += "*"
        return pattern

    def log_pre_change(self, mappings):
        if self.log_changes:
            if self.test:
                logger.info(f"\nTEST Batch rename at {self.root} with mappings: {mappings}")
            else:
                logger.info(f"\nBatch rename at {self.root} with mappings: {mappings}")

    def batch_rename_by_mtime(self, mappings={}, recursive=False, make_dirs=False):
        """
        Provide a dictionary of str mappings between glob expressions and rename bases.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.rename_by_mtime(pattern, mappings[pattern], recursive=recursive)

    def batch_rename_by_ctime(self, mappings={}, recursive=False, make_dirs=False):
        """
        Provide a dictionary of str mappings between glob expressions and rename bases.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.rename_by_ctime(pattern, mappings[pattern], recursive=recursive)

    def batch_move_files(self, mappings={}, recursive=False, make_dirs=False):
        """
        Provide a dictionary of str mappings between glob expressions and directory targets.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.move_files(pattern, mappings[pattern], recursive=recursive, make_dirs=make_dirs)


    def print_summary(self, count, strategy, glob_exp, rename_base, recursive):
        if self.test:
            if count > 0:
                logger.info(f"TEST rename {str(count)} files in {self.root} by {strategy}. glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
            else:
                logger.info(f"No files found to rename at {self.root} for glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
        elif count > 0:
            logger.info(f"Renamed {str(count)} files in {self.root} by {strategy}. glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
        else:
            logger.info(f"No files found to rename at {self.root} for glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")

    def print_failures(self, failures):
        if len(failures) > 0:
            logger.warning("Some renaming operations failed. The following files may still be present:")
            for filename in failures:
                logger.warning(filename)


def main():
    logger.info("file_renamer [glob_exp] [dirpath] [rename_base] [recursive=f]")
    glob_exp = sys.argv[1] if len(sys.argv) > 1 else "*.*"
    
    if (glob_exp == "-h" or glob_exp == "--help") and len(sys.argv) == 2:
        exit(0)
    
    glob_exp = "*.*" if glob_exp == "" or glob_exp == "*" or glob_exp == ".*" else glob_exp
    wd = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    rename_base = sys.argv[3] if len(sys.argv) > 3 else ""
    recursive = sys.argv[4] != "f" and sys.argv[4] != "" if len(sys.argv) > 4 else False
    
    if recursive:
        logger.info("Recursive option set")

    if glob_exp == "*.*":
        confirm = input(f"Rename all files in {wd}? Confirm (y/n): ")
    else:
        confirm = input(f"Rename files according to glob pattern {glob_exp} in {wd}? Confirm (y/n): ")

    if confirm.lower() != "y":
        logger.info("No action taken.")
        exit(0)

    renamer = FileRenamer(wd)
    renamer.rename_by_ctime(glob_exp, rename_base, recursive)


if __name__ == "__main__":
    if True:
        exit()



