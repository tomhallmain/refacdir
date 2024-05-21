import os

from refacdir.file_renamer import FileRenamer
from refacdir.utils import Utils


class Location:
    def __init__(self, root, exclude_dirs=[]):
        if not isinstance(root, str):
            raise TypeError(f"directory root must be a string, got {type(root)} ({root})")
        self.root = root.replace("{{USER_HOME}}", os.path.expanduser("~"))
        self.exclude_dirs = exclude_dirs

    @staticmethod
    def construct(location_obj):
        if isinstance(location_obj, dict):
            return Location(**location_obj)
        else:
            return Location(location_obj)

    def __str__(self):
        if len(self.exclude_dirs) == 0:
            return f"{self.root}"
        else:
            return f"{self.root} (excluding dirs: {self.exclude_dirs})"

class BatchRenamer:
    DESCRIPTIONS = {
        "batch_move_files": "move files to target specified in mappings from",
        "batch_rename_by_ctime": "rename files by ctime at",
        "batch_rename_by_mtime": "rename files by mtime at",
    }

    def __init__(self, name, mappings, locations, test=True, skip_confirm=False, recursive=True, preserve_alpha=False, make_dirs=False):
        self.name = name
        self.mappings = mappings
        self.locations = locations
        self.test = test
        self.skip_confirm = skip_confirm
        self.recursive = recursive
        self.preserve_alpha = preserve_alpha
        self.make_dirs = make_dirs

    def _get_renamer(self, location):
        if isinstance(location, Location):
            file_renamer = FileRenamer(root=location.root, test=self.test, preserve_alpha=self.preserve_alpha, exclude_dirs=location.exclude_dirs)
        elif isinstance(location, str):
            file_renamer = FileRenamer(root=location, test=self.test, preserve_alpha=self.preserve_alpha)
        elif isinstance(location, dict):
            root = location["root"]
            exclude_dirs = location["exclude_dirs"]
            file_renamer = FileRenamer(root=root, test=self.test, preserve_alpha=self.preserve_alpha, exclude_dirs=exclude_dirs)
        else:
            raise Exception(f"Invalid location provided: {location}")
        return file_renamer

    def found_files(self):
        for location in self.locations:
            file_renamer = self._get_renamer(location)
            if file_renamer.found_files(self.mappings, self.recursive):
                return True
        return False

    def move_files(self):
        self.execute(_func="batch_move_files")

    def rename_by_ctime(self):
        self.execute(_func="batch_rename_by_ctime")

    def rename_by_mtime(self):
        self.execute(_func="batch_rename_by_mtime")

    def execute(self, _func, _desc="rename files at"):
        if _func not in BatchRenamer.DESCRIPTIONS:
            temp = "batch_" + _func
            if temp in BatchRenamer.DESCRIPTIONS:
                _func = temp
            else:
                raise Exception(f"Invalid function provided: {_func}. Must be one of: {BatchRenamer.DESCRIPTIONS.keys()}")
        _desc = BatchRenamer.DESCRIPTIONS[_func]
        if self.test:
            print(f"\n|=============== TESTING BATCH RENAME PROCESS: {self.name} (no change to be made) ===============|")
        elif not self.found_files():
            print(f"{self.name} - No files found for {_desc} {Utils.stringify_list(self.locations, do_print=False)}")
            return
        else:
            print(f"\n|=============== BATCH RENAME PROCESS STARTED: {self.name} ===============|")
        print(f"About to {_desc} locations:")
        Utils.stringify_list(self.locations)
        print("with mapping patterns:")
        Utils.stringify_dict(self.mappings)

        if not self.test:
            if not self.skip_confirm:
                confirm = input("Confirm (y/n) ")

                if confirm.lower() != "y":
                    print("No action taken.")
                    return

        for location in self.locations:
            file_renamer = self._get_renamer(location)
            operation = getattr(file_renamer, _func)
            operation(self.mappings, recursive=self.recursive, make_dirs=self.make_dirs)

        print(f"|=============== BATCH RENAME PROCESS COMPLETE: {self.name} ===============|\n\n")
