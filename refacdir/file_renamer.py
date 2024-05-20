import glob
import os
import sys

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
    FILE_EXISTS_MESSAGE = "Cannot create a file when that file already exists"
    
    def __init__(self, root=".", test=False, log_changes=True, preserve_alpha=True, exclude_dirs=[]):
        if not os.path.isdir(root):
            raise Exception(f"Invalid root directory {root}")
        self.root = root
        self.test = test
        self.log_changes = log_changes
        self.preserve_alpha = preserve_alpha
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
        new_filename = os.path.join(rename_dir, new_filename)
        try:
            if not self.test:
                os.rename(filename, new_filename)
            count += 1
            if self.log_changes:
                if self.test:
                    print(f"TEST rename {filename} to {new_filename}")
                elif filename == new_filename:
                    print(f"moved {filename} to {target_dir}")
                else:
                    print(f"renamed {filename} to {new_filename}")
        except OSError as e:
            if FileRenamer.FILE_EXISTS_MESSAGE in str(e):
                raise e
            print(f"Failed to rename {filename} to {new_filename}")
            print(e)
            failures.append(filename)
        return count

    def rename_by_func(self, glob_exp, rename_base, recursive=False, rename_func=lambda x: x):
        count = 0
        cwd = os.getcwd()
        if cwd != self.root:
            os.chdir(self.root)
        failures = []

        test_func = None
        if callable(glob_exp):
            print("reassigning glob expression.")
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
                print(f"Exact time for new filename \"{new_filename}\" matches another file, will try to find a close value.")
                resolved = False
                increment = 0
                positive = False
                while count < 50 and not resolved:
                    positive = not positive
                    if positive:
                        increment += 1
                    try:
                        new_filename = rename_func(filename, increment=increment, positive=positive)
                        count = self.rename_file(filename, new_filename, count, None, failures)
                        resolved = True
                    except Exception as e1:
                        if not FileRenamer.FILE_EXISTS_MESSAGE in str(e1):
                            raise e0            

    def os_stat_rename_func(self, attr, rename_base):
        def rename_func(filename, increment=0, positive=True):
            time_str = str(getattr(os.stat(filename), attr)).replace(".", "")
            while len(time_str) < 17:
                time_str += "0"
            if increment > 0:
                time = int(time_str)
                if positive:
                    time += increment
                else:
                    time -= increment
                time_str = str(time)
                while len(time_str) < 17:
                    time_str += "0"
            basename, extension = os.path.splitext(filename)
            if self.preserve_alpha:
                alpha_part = alpha_basename_part(basename)
                new_filename = rename_base + time_str + alpha_part + extension
            else:
                new_filename = rename_base + time_str + extension
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

    def move_files(self, glob_exp, target_dir, recursive=False):
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
            print("reassigning glob expression.")
            test_func = glob_exp
            glob_exp = FileRenamer.get_glob_pattern(recursive=recursive)
        else:
            glob_exp = FileRenamer.get_glob_pattern(glob_exp, recursive=recursive)

        for filename in glob.glob(glob_exp, recursive=recursive):
            if self._is_ineligible_file(filename):
                continue
            if test_func and not test_func(filename):
                continue
            count = self.rename_file(filename, filename, count, target_dir, failures)

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
                print(f"\nTEST Batch rename at {self.root} with mappings: {mappings}")
            else:
                print(f"\nBatch rename at {self.root} with mappings: {mappings}")

    def batch_rename_by_mtime(self, mappings={}, recursive=False):
        """
        Provide a dictionary of str mappings between glob expressions and rename bases.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.rename_by_mtime(pattern, mappings[pattern], recursive=recursive)

    def batch_rename_by_ctime(self, mappings={}, recursive=False):
        """
        Provide a dictionary of str mappings between glob expressions and rename bases.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.rename_by_ctime(pattern, mappings[pattern], recursive=recursive)

    def batch_move_files(self, mappings={}, recursive=False):
        """
        Provide a dictionary of str mappings between glob expressions and directory targets.
        """
        self.log_pre_change(mappings)
        for pattern in mappings:
            self.move_files(pattern, mappings[pattern], recursive=recursive)


    def print_summary(self, count, strategy, glob_exp, rename_base, recursive):
        if self.test:
            if count > 0:
                print(f"TEST rename {str(count)} files in {self.root} by {strategy}. glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
            else:
                print(f"No files found to rename at {self.root} for glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
        elif count > 0:
            print(f"Renamed {str(count)} files in {self.root} by {strategy}. glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")
        else:
            print(f"No files found to rename at {self.root} for glob_exp={glob_exp}, rename_base={rename_base}, recursive={recursive}")

    def print_failures(self, failures):
        if len(failures) > 0:
            print("Some renaming operations failed. The following files may still be present:")
            for filename in failures:
                print(filename)


def main():
    print("file_renamer [glob_exp] [dirpath] [rename_base] [recursive=f]")
    glob_exp = sys.argv[1] if len(sys.argv) > 1 else "*.*"
    
    if (glob_exp == "-h" or glob_exp == "--help") and len(sys.argv) == 2:
        exit(0)
    
    glob_exp = "*.*" if glob_exp == "" or glob_exp == "*" or glob_exp == ".*" else glob_exp
    wd = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    rename_base = sys.argv[3] if len(sys.argv) > 3 else ""
    recursive = sys.argv[4] != "f" and sys.argv[4] != "" if len(sys.argv) > 4 else False
    
    if recursive:
        print("Recursive option set")

    if glob_exp == "*.*":
        confirm = input(f"Rename all files in {wd}? Confirm (y/n): ")
    else:
        confirm = input(f"Rename files according to glob pattern {glob_exp} in {wd}? Confirm (y/n): ")

    if confirm.lower() != "y":
        print("No action taken.")
        exit(0)

    renamer = FileRenamer(wd)
    renamer.rename_by_ctime(glob_exp, rename_base, recursive)


if __name__ == "__main__":
    if True:
        exit()



