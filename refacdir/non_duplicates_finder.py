import argparse
from collections import defaultdict
import hashlib
import os
import sys

from refacdir.utils import Utils

# TODO trim and finish this

class NonDuplicatesFinder:
    def __init__(self, name, source_folders, recursive=True, exclude_dirs=[]):
        self.name = name
        self.source_folders = []
        for source_folder in source_folders:
            self.source_folders.append(os.path.abspath(source_folder))
        self.duplicates = {}
        self.recursive = recursive
        self.dir_separator_char = "\\" if sys.platform.startswith("win") else "/"
        self.exclude_dirs = []
        self.preferred_delete_dirs = []
        self.skip_exclusion_check = len(exclude_dirs) == 0
        if not self.skip_exclusion_check:
            print("Excluding directories from duplicates check:")
            for d in exclude_dirs:
                full_path = self._find_full_path(d)
                if not os.path.isdir(full_path):
                    raise Exception("Invalid exclude directory: " + d)
                print(full_path)
                self.exclude_dirs.append(full_path)

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
        print(f"Running duplicate removal for: {self.source_folders}")
        if self.find_duplicates():
            self.handle_duplicates(testing=True)
            confirm = input("Confirm all duplicates removal (Y/n): ")
            if confirm.lower() == "y":
                self.handle_duplicates(testing=False)
                return
            print("No change made.")
            confirm = input("Remove duplicates with confirmation one by one? (Y/n): ")
            if confirm.lower() == "y":
                self.handle_duplicates(testing=False, skip_confirm=False)
                return
            print("No change made.")
            confirm_report = input("Save duplicates report? (Y/n): ")
            if confirm_report.lower() == "y":
                self.save_report()
        else:
            print("No duplicates found.")

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
            for foldername, subfolders, filenames in os.walk(source_folder):
                if not self.recursive and foldername != source_folder: # TODO better way to handle this
                    continue
                for filename in filenames:
                    file_path = os.path.normpath(os.path.join(foldername, filename))
                    if self.skip_exclusion_check or not self.is_excluded(file_path):
                        try:
                            file_dict[self.get_file_hash(file_path)].append(file_path)
                        except Exception as e: # FileNotFound error is possible
                            print(f"Error generating hash for \"{file_path}\": {e}")
        self.duplicates = {k: v for k, v in file_dict.items() if len(v) > 1}
        return self.has_duplicates()

    def has_duplicates(self):
        return len(self.duplicates) > 0

    def determine_duplicates(self, file_list):
        best_duplicate = self.select_best_duplicate(file_list)
        duplicates_to_remove = [f for f in file_list if not f == best_duplicate]
        return best_duplicate, duplicates_to_remove

    def handle_duplicates(self, testing, skip_confirm=True):
        for file_list in self.duplicates.values():
            best_duplicate, duplicates_to_remove = self.determine_duplicates(file_list)
            if testing:
                print("Keeping file:               " + best_duplicate)
                print("Removing duplicate files: " + str(duplicates_to_remove))
            else:
                if not skip_confirm:
                    print("Keeping file:               " + best_duplicate)
                    print("Removing duplicate files: " + str(duplicates_to_remove))
                    confirm = input(f"OK to remove? (Y/n): ")
                    if confirm.lower() != "y":
                        continue
                for file_path in duplicates_to_remove:
                    print("Removing file: " + file_path)
                    os.remove(file_path)

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
        raise Exception("Impossible case")

    def save_report(self):
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
        print(f'Report saved at {report_path}')

def non_dups_main(directory_path=".", recursive=True, exclude_dir_string=""):
    exclude_dirs = Utils.get_list_from_string(exclude_dir_string)
    remover = NonDuplicatesFinder("dups_main", directory_path, recursive=recursive, 
                               exclude_dirs=exclude_dirs)
    remover.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Remove duplicate files in a directory.')
    parser.add_argument('dir', help='Directory to search for duplicate files')
    args = parser.parse_args()
    non_dups_main(args.dir)

