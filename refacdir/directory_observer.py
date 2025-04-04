import glob
import json
import os

from refacdir.utils.utils import Utils

media_file_types = [".bmp", ".gif", ".jpeg", ".jpg", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".png", ".tiff", ".webm", ".webp"]

def print_table(table, divider="  "):
    max_field_lengths = []
    for row in table:
        for col_index in range(len(row)):
            cell_len = len(str(row[col_index]))
            if len(max_field_lengths) <= col_index:
                max_field_lengths.append(cell_len)
            elif cell_len > max_field_lengths[col_index]:
                max_field_lengths[col_index] = cell_len
    
    for row in table:
        row_string = ""
        for col_index in range(len(row)):
            cell = row[col_index]
            cell_str = str(cell)
            spaces_to_add = max_field_lengths[col_index] - len(cell_str)
            if isinstance(cell, int):
                if cell == 0:
                    cell_str = "-"
                row_string += (spaces_to_add * " ") + cell_str + divider
            else:
                row_string += cell_str + (spaces_to_add * " ") + divider
        print(row_string)

class DirData:
    file_types = []

    @staticmethod
    def set_file_types(file_types):
        DirData.file_types = file_types
        if ((".jpg" in DirData.file_types and ".jpeg" not in DirData.file_types)
                or (".jpg" not in DirData.file_types and ".jpeg" in DirData.file_types)):
            raise Exception("JPG can have two types, .jpg, and .jpeg. It is recommended to use both if using one.")

    @staticmethod
    def remove_file_types(file_types):
        print(f"Removing file types with no files: {file_types}")
        for t in file_types:
            try:
                DirData.file_types.remove(t)
            except ValueError as e:
                pass

    @staticmethod
    def combine_file_types_list(file_types, preserving_name):
        first_index = None
        for t in file_types:
            if t in DirData.file_types:
                if first_index is None:
                    first_index = DirData.file_types.index(t)
                DirData.file_types.remove(t)
        if first_index is None:
            raise Exception("No file type was found in the list of file types.")
        DirData.file_types.insert(first_index, preserving_name)

    def __init__(self, directory):
        self.directory = directory
        self.exclude_dirs = []
        self.all_files = []
        self.dict = {}
        self.total_file_count_types = 0
        self.total_file_count = 0
        for t in DirData.file_types:
            self.dict[t] = 0

    def observe(self):
        self.all_files = glob.glob("**/*", root_dir=self.directory, recursive=True)
        if len(self.exclude_dirs) > 0:
            for d in self.exclude_dirs:
                to_remove = []
                for f in self.all_files:
                    if f.startswith(d):
                        to_remove.append(f)
                self.all_files = Utils.subtract_list(self.all_files, to_remove)
        self.total_file_count = len(self.all_files)
        for file_type in DirData.file_types:
            file_count = len(list(filter(lambda f: f.lower().endswith(file_type), self.all_files)))
            self.total_file_count_types += file_count
            self.dict[file_type] = file_count
        return self.total_file_count, self.total_file_count_types

    def other_file_count(self):
        return self.total_file_count - self.total_file_count_types

    def combine_file_types(self, file_types_to_combine, preserving_type_name):
        total_count = 0
        for t in file_types_to_combine:
            total_count += self.dict[t]
            del self.dict[t]
        self.dict[preserving_type_name] = total_count

    def has_files(self):
        return len(self.all_files) > 0

    def has_file_type(self, ext):
        return ext in self.dict and self.dict[ext] > 0

    def apply_exclude_dir(self, exclude_dir):
        if exclude_dir.startswith(self.directory):
            exclude_dir = exclude_dir[len(self.directory)+1:]
        self.exclude_dirs.append(exclude_dir)


class DirectoryObserver:
    UNSORTED = "_unsorted"
    def __init__(self, name, sortable_dirs=[], extra_dirs=[], parent_dirs=[], exclude_dirs=[], file_types=[]):
        self.name = name
        self.dir_data = {}
        self.total_file_count = 0
        self.total_file_count_types = 0

        for d in sortable_dirs:
            sort_dir = os.path.join(d, DirectoryObserver.UNSORTED)
            if not os.path.isdir(sort_dir):
                raise Exception("Invalid directory provided: " + d)
            self.dir_data[sort_dir] = DirData(sort_dir)

        for d in extra_dirs:
            if not os.path.isdir(d):
                raise Exception("Invalid directory provided: " + d)
            self.dir_data[d] = DirData(d)
        
        for d in parent_dirs:
            if not os.path.isdir(d):
                raise Exception("Invalid directory provided: " + d)
            print(f"Adding directories from parent: {d}")
            for subdir in [ f.path for f in os.scandir(d) if f.is_dir() ]:
                self.dir_data[subdir] = DirData(subdir)

        for d in exclude_dirs:
            if not os.path.isdir(d):
                raise Exception("Invalid exclude directory provided: " + d)
            self.apply_exclude_dir_to_matching_dir_data(d)

        if len(file_types) == 0 or len(self.dir_data) == 0:
            raise Exception("No sort dirs or file types provided")

        DirData.set_file_types(file_types)

    def run(self):
        self.observe()
        self.log()

    def observe(self):
        # Gather data
        for dir_data in self.dir_data.values():
            total_file_count, total_file_count_types = dir_data.observe()
            self.total_file_count += total_file_count
            self.total_file_count_types += total_file_count_types

        # Combine file types that are similar
        if ".jpg" in DirData.file_types and ".jpeg" in DirData.file_types:
            for dir_data in self.dir_data.values():
                dir_data.combine_file_types([".jpg", ".jpeg"], ".jpg/.jpeg")
            DirData.combine_file_types_list([".jpg", ".jpeg"], ".jpg/.jpeg")

        # Remove file types with no files
        to_remove_file_types = []
        for ext in DirData.file_types:
            remove_this_ext = True
            for dir_data in self.dir_data.values():
                if dir_data.has_file_type(ext):
                    remove_this_ext = False
                    break
            if remove_this_ext:
                to_remove_file_types.append(ext)
        if len(to_remove_file_types):
            DirData.remove_file_types(to_remove_file_types)

    def log(self):
        print("Current state of directories:")
        print(f"Total: {self.total_file_count} files")
        rows = []
        header = ["Directory"]
        for ext in DirData.file_types:
            header.append(ext)
        header.append("Other")
        header.append("Total")

        for d, dir_data in self.dir_data.items():
            if not dir_data.has_files():
                continue
            line = [d]
            for ext in DirData.file_types:
                line.append(dir_data.dict[ext])
            line.append(dir_data.other_file_count())
            line.append(dir_data.total_file_count)
            rows.append(line)

        rows.sort(key=lambda row: row[len(row)-1], reverse=True)
        rows.insert(0, header)
        print_table(rows)

    def apply_exclude_dir_to_matching_dir_data(self, exclude_dir):
        for d, dir_data in self.dir_data.items():
            if exclude_dir.startswith(d):
                dir_data.apply_exclude_dir(exclude_dir)
                return

        print(f"No matching directory found for exclude directory {exclude_dir}")



if __name__ == "__main__":
    observed_dirs_json = json.load(open("observed_directories.json"))
    sortable_dirs = observed_dirs_json["sortable_dirs"]
    extra_dirs = observed_dirs_json["extra_dirs"]
    file_types = observed_dirs_json["file_types"] if "file_types" in observed_dirs_json else media_file_types
    state_observer = DirectoryObserver(
        name="StateObserver",
        sortable_dirs=sortable_dirs,
        extra_dirs=extra_dirs,
        file_types=file_types
    )
    state_observer.observe()
    state_observer.log()

