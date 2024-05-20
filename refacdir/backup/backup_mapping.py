from collections import defaultdict
import datetime
from enum import Enum
import hashlib
import json
import os
import pickle

try:
    from send2trash import send2trash
except Exception:
    print("Could not import trashing utility - all deleted files will be deleted instantly")

def remove_file(path):
    try:
        send2trash(os.path.normpath(path))
    except Exception as e:
        print(e)
        print("Failed to send file to the trash, so it will be deleted immediately. Run pip install send2trash to fix.")
#        os.remove(path)


from refacdir.utils import Utils

def exception_as_dict(ex):
    return dict(type=ex.__class__.__name__,
                errno=ex.errno, message=ex.message,
                strerror=exception_as_dict(ex.strerror)
                if isinstance(ex.strerror,Exception) else ex.strerror)

class BackupMode(Enum):
    PUSH_AND_REMOVE = 0
    PUSH = 1
    PUSH_DUPLICATES = 2
    MIRROR = 3
    MIRROR_DUPLICATES = 4

class FailureType(str, Enum):
    MOVE_FILE = 1
    REMOVE_SOURCE_FILE = 2
    REMOVE_SOURCE_FILE_TARGET_NOEXIST = 3
    REMOVE_STALE_FILE = 4
    REMOVE_STALE_DIRECTORY = 5

class BackupSourceData:
    FILEPATH = "backup_mapping_data.pkl"

    def __init__(self, source_dir="."):
        self.source_dir = source_dir
        self.filepath = os.path.normpath(os.path.join(source_dir, BackupSourceData.FILEPATH))
        self.hash_dict = defaultdict(list)
        self.last_updated = datetime.datetime.now().toordinal()

    def save(self):
        with open(self.filepath, "wb") as store:
            pickle.dump(self, store)
        self.last_updated = datetime.datetime.now().toordinal()

    @staticmethod
    def load(source_dir, overwrite=False):
        filepath = os.path.normpath(os.path.join(source_dir, BackupSourceData.FILEPATH))
        if os.path.exists(filepath) and not overwrite:
            with open(filepath, "rb") as f:
                backup_source_data = pickle.load(f)
        else:
            backup_source_data = BackupSourceData(source_dir=source_dir)
        return backup_source_data


class BackupMapping:

    def __init__(self, name="BackupMapping", source_dir=None, target_dir=None, file_types=[],
                 mode=BackupMode.PUSH, exclude_dirs=[], exclude_removal_dirs=[], will_run=True):
        self.name = name
        if source_dir is None or target_dir is None:
            raise ValueError("Source and target directories must be specified")
        self.source_dir = os.path.normpath(source_dir)
        self.target_dir = os.path.normpath(target_dir)
        self.file_types = file_types
        self.allows_all_file_types = len(self.file_types) == 0
        self.exclude_dirs = exclude_dirs
        self.exclude_removal_dirs = exclude_removal_dirs
        self._source_data = BackupSourceData()
        self._target_hash_dict = defaultdict(str)
        self._source_dirs = []
        self._target_dirs = []
        self.modified_target_files = []
        self.mode = mode
        self.failures = []
        self.will_run = will_run

    def _file_type_match(self, filename):
        for ext in self.file_types:
            if filename.endswith(ext):
                return True
        if "." in filename:
            extension = filename[filename.rfind("."):]
            return extension.lower() in self.file_types
        return False

    def _calculate_hash(self, filepath):
        with open(filepath, 'rb') as f:
            sha256 = hashlib.sha256()
            while True:
                data = f.read(65536)
                if not data: break
                sha256.update(f.read())
        return sha256.hexdigest()

    def _build_hash_dict(self, _dir, hash_dict, get_dirs=[], is_target=False):
        if not is_target:
            source_hash_dict = defaultdict(str)
            for hash, files in hash_dict.items():
                for f in files:
                    source_hash_dict[f] = hash

        for root, dirs, files in os.walk(_dir):
            if self._is_file_excluded(os.path.join(root, "_")):
                continue
            for subdir in dirs:
                full_path = os.path.join(root, subdir)
                if full_path not in self.exclude_dirs:
                    relative_path = full_path.replace(os.path.join(_dir, ""), "")
                    get_dirs.append(relative_path)
            for name in files:
                if self.allows_all_file_types or self._file_type_match(name):
                    filepath = os.path.join(root, name)
                    if is_target:
                        hash_dict[filepath] = self._calculate_hash(filepath)
                    else:
                        _hash = source_hash_dict[filepath] if filepath in source_hash_dict else self._calculate_hash(filepath)
                        filepaths = hash_dict[_hash]
                        if not filepath in filepaths:
                            filepaths.append(filepath)

    def setup(self, overwrite=False, warn_duplicates=False):
        self._source_data = BackupSourceData.load(self.source_dir, overwrite=overwrite)
        self._build_hash_dict(self.source_dir, self._source_data.hash_dict, get_dirs=self._source_dirs)
        if warn_duplicates:
            for hash, files in self._source_data.hash_dict.items():
                if len(files) > 1:
                    print(f"Duplicate: {str(files)}")
        self._build_hash_dict(self.target_dir, self._target_hash_dict, get_dirs=self._target_dirs, is_target=True)


    def _build_target_path(self, source_filepath):
        relative_path = source_filepath.replace(os.path.join(self.source_dir, ""), "")
        if relative_path.startswith(self.source_dir):
            print(f"Failed to build target path: source filepath was {source_filepath}, source dir was {self.source_dir}")
            exit()
        target = os.path.join(self.target_dir, relative_path)
        return target

    def _create_dirs(self, target_path, test=True):
        parent = os.path.dirname(target_path)
        if not os.path.isdir(parent):
            print(f"Creating direc: {parent}")
            if not test:
                os.makedirs(parent)

    def is_push_mode(self):
        return self.mode in [BackupMode.PUSH, BackupMode.PUSH_DUPLICATES, BackupMode.PUSH_AND_REMOVE]

    def is_mirror_mode(self):
        return self.mode in [BackupMode.MIRROR, BackupMode.MIRROR_DUPLICATES]

# Uncovered case.. renamed directory in source. Probably need to come up with a way to test that directories are highly similar by their contents to accomodate this

    def _move_file(self, source_path, external_source=None, move_func=Utils.move, test=True):
        target_path = self._build_target_path(source_path)
        self._create_dirs(target_path, test=test)
        try:
            if external_source:
                print(f"Moving file within external dir to: {target_path} - previous location: {external_source}")
                source_path = external_source
            elif os.path.exists(target_path):
                print(f"Replacing file: {target_path}")
            else:
                print(f"Creating file: {target_path}")
            if not test:
                move_func(source_path, target_path)
                self.modified_target_files.append(target_path)
        except Exception as e:
            self.failures.append([FailureType.MOVE_FILE, exception_as_dict(e), target_path, source_path])

    def _is_file_excluded(self, filepath):
        for _dir in self.exclude_dirs:
            if filepath.startswith(_dir):
                return True
        return filepath in self.exclude_dirs # could be a directory

    def _is_file_removal_excluded(self, filepath):
        for _dir in self.exclude_removal_dirs:
            if filepath.startswith(_dir):
                return True
        return False

    def _remove_source_file(self, source_path, target_path, test=True):
        if self._is_file_removal_excluded(source_path):
            return
        if not os.path.exists(target_path):
            print(f"Could not remove source file {source_path} because expected target file {target_path} was not found!!!")
            self.failures.append([FailureType.REMOVE_SOURCE_FILE_TARGET_NOEXIST, "Backup file not found", target_path, source_path])
            return
        print(f"Removing file already backed up: {source_path}")
        if not test:
            try:
                remove_file(source_path)
            except Exception as e:
                self.failures.append([FailureType.REMOVE_SOURCE_FILE, exception_as_dict(e), target_path, source_path])

    def _has_duplicates_in_target(self, _hash):
        all_hashes = list(self._target_hash_dict.values())[:]
        all_hashes.remove(_hash)
        return _hash in all_hashes

    def _ensure_files(self, source_hash, source_files, move_func=Utils.move, test=True):
        if not source_hash in self._target_hash_dict.values():
            for source_path in source_files:
                print("Hash not found")
                self._move_file(source_path, move_func=move_func, test=test)
        else:
            for source_path in source_files:
                target_path = self._build_target_path(source_path)
                # NOTE this logic COULD be an issue if the directory is being modified while this is running
                if not os.path.exists(target_path) or self._target_hash_dict[target_path] != source_hash:
                    if self._has_duplicates_in_target(source_hash):
                        # In case there are duplicates we can't be sure which to select for moving
                        self._move_file(source_path, move_func=move_func, test=test)
                    else:
                        found_hash = False
                        for fp, _hash in self._target_hash_dict.items():
                            if _hash == source_hash and not fp in self.modified_target_files and os.path.exists(fp):
                                self._move_file(source_path, external_source=fp, move_func=move_func, test=test)
                                if move_func == Utils.move:
                                    # Need to remove file in source also here because we did not remove it using shutil due to modified call
                                    self._remove_source_file(source_path, target_path, test=test)
                                found_hash = True
                                break
                        if not found_hash:
                            print("Unable to move file in external because it was previously modified, but it will be moved anyway.")
                            self._move_file(source_path, move_func=move_func, test=test)
                elif move_func == Utils.move:
                    self._remove_source_file(source_path, target_path, test=test)

    def push(self, move_func=Utils.move, test=True):
        # Create any new directories first (even if empty)
        print("PUSHING DIRECTORIES TO EXTERNAL DRIVE")
        new_dirs = list(set(self._source_dirs) - set(self._target_dirs))
        for directory in sorted(new_dirs):
            new_dir = os.path.join(self.target_dir, directory)
            print(f"Making new directory: {new_dir}")
            if not test:
                os.makedirs(new_dir)
        # Move the files to external drive
        print("PUSHING FILES TO EXTERNAL DRIVE")
        for source_hash, source_files in self._source_data.hash_dict.items():
            self._ensure_files(source_hash, source_files, move_func=move_func, test=test)

    def mirror(self, test=True):
        self.push(move_func=copy, test=test)
        confirm = input("Please confirm files removal from external directory - they should be in trash folder if there is a major issue (y/n):")
        if confirm.lower() != "y":
            print("No \"stale\" files or directories to be removed.")
            return
        # Remove stale files to ensure parity
        print("REMOVING OLD EXTERNAL FILES TO ENSURE PARITY")
        for target_file, target_hash in self._target_hash_dict.items():
            if not target_hash in self._source_data.hash_dict:
                if self._is_file_excluded(target_file) or self._is_file_removal_excluded(target_file):
                    continue
                try:
                    print(f"Removing external file: {target_file}")
                    if not test:
                        remove_file(target_file)
                except Exception as e:
                    self.failures.append([FailureType.REMOVE_STALE_FILE, exception_as_dict(e), target_file, "Could not remove stale file"])
        # Remove stale directories to ensure parity
        print("REMOVING OLD EXTERNAL DIRECTORIES TO ENSURE PARITY")
        old_external_dirs = list(set(self._target_dirs) - set(self._source_dirs))
        for directory in old_external_dirs:
            stale_dirpath = os.path.join(self.target_dir, directory)
            if self._is_file_excluded(stale_dirpath) or self._is_file_removal_excluded(stale_dirpath):
                continue
            try:
                print(f"Removing external file: {stale_dirpath}")
                if not test:
                    remove_file(stale_dirpath)
            except Exception as e:
                self.failures.append([FailureType.REMOVE_STALE_DIRECTORY, exception_as_dict(e), stale_dirpath, "Could not remove stale directory"])

    def backup(self, test=True):
        if self.is_push_mode():
            move_func = Utils.move if self.mode == BackupMode.PUSH_AND_REMOVE else Utils.copy
            self.push(move_func=move_func, test=test)
        elif self.is_mirror_mode():
            self._source_data.save() # The source data will only matter if we are not removing source files.
            self.mirror(test=test)

    def report_failures(self):
        if len(self.failures) == 0:
            print(f"No failures encountered for mapping: {self.source_dir} -> {self.target_dir}")
        else:
            print(f"Failures encountered for mapping: {self.source_dir} -> {self.target_dir}")
            for f in self.failures:
                print(f)
                print(f[1])
                failure_type = f[0]
                if failure_type == FailureType.MOVE_FILE:
                    print(f"Failed to move {f[3]} to {f[2]}: {f[1]}")
                elif failure_type == FailureType.REMOVE_SOURCE_FILE:
                    print(f"Failed to remove file {f[3]}: {f[1]}")
                elif failure_type == FailureType.REMOVE_SOURCE_FILE_TARGET_NOEXIST:
                    print(f"Failed to remove file {f[3]} as could not verify target {f[2]}: {f[1]}")
                elif failure_type == FailureType.REMOVE_STALE_FILE:
                    print(f"Failed to remove stale file {f[2]}: {f[1]}")
                elif failure_type == FailureType.REMOVE_STALE_DIRECTORY:
                    print(f"Failed to remove stale directory {f[2]}: {f[1]}")
            json.dump(self.failures, open("backup_failures.json", "w"), indent=2)
            print("Saved failure data to failures.json.")

    def clean(self):
        self.failures = []
        self.modified_target_files = []

    def __str__(self):
        return f"""BackupMapping{{
    Source: {self.source_dir}
    Target: {self.target_dir}
    Mode: {self.mode}
    File types: {self.file_types}
    Exclude dirs: {self.exclude_dirs}
    Exclude removal dirs: {self.exclude_removal_dirs}
}}"""
