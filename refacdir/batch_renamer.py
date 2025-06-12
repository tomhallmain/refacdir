import os

from refacdir.file_renamer import FileRenamer
from refacdir.filename_ops import FilenameMappingDefinition
from refacdir.utils.utils import Utils
from refacdir.utils.logger import setup_logger

# Set up logger for batch renamer
logger = setup_logger('batch_renamer')

class Location:
    def __init__(self, root, exclude_dirs=[]):
        if not isinstance(root, str):
            raise TypeError(f"directory root must be a string, got {type(root)} ({root})")
        self.root = Utils.fix_path(root)
        self.exclude_dirs = list(map(lambda p: Utils.fix_path(p), exclude_dirs))

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


class DirectoryFlattener:
    """
    Take all files in recursive directories and flatten them into the base directory.
    """
    def __init__(self, name, location, search_patterns=[], test=True, skip_confirm=False):
        logger.info(f"Initializing directory flattener: {name}")
        self.name = name
        self.location = Location.construct(location)
        if search_patterns is None or len(search_patterns) == 0:
            mappings_list = [{"search_patterns": [lambda f: True], "rename_tag": self.location.root}]
        else:
            mappings_list = [{"search_patterns": search_patterns, "rename_tag": self.location.root}]
        mappings = FilenameMappingDefinition.construct_mappings(mappings_list)
        self.batch_renamer = BatchRenamer("DirectoryFlattener", mappings, [self.location], test=test,
                                          skip_confirm=skip_confirm, recursive=True, make_dirs=False, find_unused_filenames=True)

    def run(self):
        logger.info(f"Running directory flattener: {self.name}")
        self.flatten()

    def flatten(self):
        logger.info(f"Flattening directory: {self.location.root}")
        self.batch_renamer.move_files()


class BatchRenamer:
    DESCRIPTIONS = {
        "batch_move_files": "move files to target specified in mappings from",
        "batch_rename_by_ctime": "rename files by ctime at",
        "batch_rename_by_mtime": "rename files by mtime at",
    }

    def __init__(self, name, mappings, locations, test=True, skip_confirm=False, recursive=True,
                 preserve_alpha=False, make_dirs=False, find_unused_filenames=False):
        logger.info(f"Initializing batch renamer: {name} with {len(mappings)} mappings and {len(locations)} locations")
        self.name = name
        self.mappings = mappings
        self.locations = locations
        self.test = test
        self.skip_confirm = skip_confirm
        self.recursive = recursive
        self.preserve_alpha = preserve_alpha
        self.make_dirs = make_dirs
        self.find_unused_filenames = find_unused_filenames

    def _get_renamer(self, location):
        if isinstance(location, Location):
            file_renamer = FileRenamer(root=location.root, test=self.test, preserve_alpha=self.preserve_alpha,
                                       exclude_dirs=location.exclude_dirs, find_unused_filenames=self.find_unused_filenames)
        elif isinstance(location, str):
            file_renamer = FileRenamer(root=location, test=self.test, preserve_alpha=self.preserve_alpha,
                                       find_unused_filenames=self.find_unused_filenames)
        elif isinstance(location, dict):
            root = location["root"]
            exclude_dirs = location["exclude_dirs"]
            file_renamer = FileRenamer(root=root, test=self.test, preserve_alpha=self.preserve_alpha, exclude_dirs=exclude_dirs,
                                       find_unused_filenames=self.find_unused_filenames)
        else:
            error_msg = f"Invalid location provided: {location}"
            logger.error(error_msg)
            raise Exception(error_msg)
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
                error_msg = f"Invalid function provided: {_func}. Must be one of: {BatchRenamer.DESCRIPTIONS.keys()}"
                logger.error(error_msg)
                raise Exception(error_msg)
        _desc = BatchRenamer.DESCRIPTIONS[_func]
        
        if self.test:
            logger.info(f"|=============== TESTING BATCH RENAME PROCESS: {self.name} (no change to be made) ===============|")
        elif not self.found_files():
            logger.warning(f"{self.name} - No files found for {_desc} {Utils.stringify_list(self.locations, do_print=False)}")
            return
        else:
            logger.info(f"|=============== BATCH RENAME PROCESS STARTED: {self.name} ===============|")
            
        logger.info(f"About to {_desc} locations: {Utils.stringify_list(self.locations, do_print=False)}")
        logger.info(f"With mapping patterns: {Utils.stringify_dict(self.mappings, do_print=False)}")

        if not self.test:
            if not self.skip_confirm:
                confirm = input("Confirm (y/n) ")
                if confirm.lower() != "y":
                    logger.info("Operation cancelled by user")
                    return

        for location in self.locations:
            logger.info(f"Processing location: {location}")
            file_renamer = self._get_renamer(location)
            operation = getattr(file_renamer, _func)
            operation(self.mappings, recursive=self.recursive, make_dirs=self.make_dirs)

        logger.info(f"|=============== BATCH RENAME PROCESS COMPLETE: {self.name} ===============|\n\n")
