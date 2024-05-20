from enum import Enum
import yaml

from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMode, BackupMapping

from refacdir.batch_renamer import BatchRenamer, Location
from refacdir.directory_observer import DirectoryObserver, media_file_types
from refacdir.duplicate_remover import DuplicateRemover
from refacdir.utils import Utils
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition


class ActionType(Enum):
    BACKUP = 'BACKUP'
    RENAMER = 'RENAMER'
    DUPLICATE_REMOVER = 'DUPLICATE_REMOVER'
    DIRECTORY_OBSERVER = 'DIRECTORY_OBSERVER'


class BatchJob:
    def __init__(self, configurations=[], test=True, skip_confirm=False):
        self.configurations = configurations
        self.duplicate_remover_count = 0
        self.rename_count = 0
        self.backup_count = 0
        self.directory_observer_count = 0
        self.duplicate_remover_failure_count = 0
        self.renamer_failure_count = 0
        self.backup_failure_count = 0
        self.directory_observer_failure_count = 0
        self.failures = []
        self.test = test
        self.skip_confirm = skip_confirm
        self.cancelled = False
        
        temp_full_path_example = None
        for config in configurations:
            if config.endswith("config_example.yaml"):
                temp_full_path_example = config

        if temp_full_path_example:
            if len(self.configurations) == 1:
                raise Exception("Excluded example config file! Please change name of config_example.yaml to ensure it is included.")
            self.configurations.remove(temp_full_path_example)

    def run(self):
        try:
            for config in self.configurations:
                self.run_config_file(config)
        except KeyboardInterrupt:
            print("Exiting prematurely at user request...")
            self.cancelled = True

    def run_config_file(self, config):
        print(f"Running actions for {config}")
        with open(config, 'r') as f:
            try:
                config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
            except yaml.YAMLError as e:
                print(f"Error loading {config}: {e}")
                self.failures.append(f"Config {config} failed to load: {e}")
                return

            if "actions" not in config_wrapper:
                print(f"Error loading {config}: No actions found in config file!")
                self.failures.append(f"Config {config} failed to load: No actions found in config file!")
                return

            FilenameMappingDefinition.add_named_functions(Utils.get_from_dict(config_wrapper, "filename_mapping_functions", []))
            FiletypesDefinition.add_named_definitions(Utils.get_from_dict(config_wrapper, "filetype_definitions", []))

            for i in range(len(config_wrapper["actions"])):
                action = config_wrapper["actions"][i]
                if not self.run_action(config, action, i):
                    return # If we fail to run an action then we stop running the config file

    def log_results(self):
        print(f"{self.duplicate_remover_count} duplicate remover job(s) completed")
        print(f"{self.rename_count} rename(s) completed")
        print(f"{self.backup_count} backup manager(s) completed")
        print(f"{self.directory_observer_count} directory observer(s) completed")
        if len(self.failures) > 0:
            print(f"{self.duplicate_remover_failure_count} duplicate remover job(s) failed")
            print(f"{self.renamer_failure_count} renames(s) failed")
            print(f"{self.backup_failure_count} backup manager(s) failed")
            print(f"{self.directory_observer_failure_count} directory observer(s) failed")
            for failure in self.failures:
                print(failure)
        elif not self.cancelled:
            print("All operations completed successfully")

    def run_action(self, config, action, idx):
        try:
            action_type_string = action["type"]
            action_type = ActionType[action_type_string]
            if action_type == ActionType.RENAMER:
                return self.run_renamers(config, action["mappings"])
            elif action_type == ActionType.BACKUP:
                return self.run_backups(config, action["mappings"])
            elif action_type == ActionType.DIRECTORY_OBSERVER:
                return self.run_directory_observers(config, action["mappings"])
            elif action_type == ActionType.DUPLICATE_REMOVER:
                return self.run_duplicate_removers(config, action["mappings"])
            else:  # Action type is not a rename or backup, so we don't know what to do with it
                raise ValueError("Invalid action type")
        except KeyError as e:
            self.failures.append(f"Invalid action configuration in {config} index {idx}: {e}")
            return False
        except Exception as e:
            self.failures.append(f"Failed to run action index {idx} in {config}: {e}")
            return False

    def run_duplicate_removers(self, config, duplicate_removers):
        for _duplicate_remover in duplicate_removers:
            self.duplicate_remover_count += 1
            try:
                duplicate_remover = self.construct_duplicate_remover(_duplicate_remover)
            except Exception as e:
                self.duplicate_remover_failure_count += 1
                if "name" in _duplicate_remover:
                    name = _duplicate_remover["name"]
                    error = f"Error in {config} duplicate remover {name}:  {e}"
                else:
                    error = f"Error in {config} duplicate remover {self.duplicate_remover_count-1}:  {e}"
                self.failures.append(error)
                continue
            try:
                duplicate_remover.run()
            except Exception as e:
                self.duplicate_remover_failure_count += 1
                error = f"{config} duplicate remover {duplicate_remover.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.duplicate_remover_failure_count == 0

    def run_renamers(self, config, renamers):
        for _renamer in renamers:
            self.rename_count += 1
            try:
                renamer, renamer_function = self.construct_batch_renamer(_renamer)
            except KeyError as e:
                self.renamer_failure_count += 1
                if "name" in _renamer:
                    name = _renamer["name"]
                    error = f"Error in {config} renamer {name}:  {e}"
                else:
                    error = f"Error in {config} renamer {self.rename_count-1}:  {e}"
                self.failures.append(error)
                print(error)
                continue
            try:
                renamer.execute(renamer_function)
            except Exception as e:
                self.renamer_failure_count += 1
                error = f"{config} renamer {renamer.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.renamer_failure_count == 0

    def run_backups(self, config, backups):
        for _backup in backups:
            self.backup_count += 1
            try:
                backup_manager = self.construct_backup_manager(_backup)
            except Exception as e:
                self.backup_failure_count += 1
                if "name" in _backup:
                    name = _backup["name"]
                    error = f"Error in {config} backup {name}:  {e}"
                else:
                    error = f"Error in {config} backup {self.backup_count-1}:  {e}"
                self.failures.append(error)
                continue
            try:
                backup_manager.run_backup()
            except Exception as e:
                self.backup_failure_count += 1
                error = f"{config} backup {backup_manager.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.backup_failure_count == 0
    
    def run_directory_observers(self, config, directory_observers):
        for _directory_observer in directory_observers:
            self.directory_observer_count += 1
            try:
                directory_observer = self.construct_directory_observer(_directory_observer)
            except Exception as e:
                self.directory_observer_failure_count += 1
                if "name" in _directory_observer:
                    name = _directory_observer["name"]
                    error = f"Error in {config} directory observer {name}:  {e}"
                else:
                    error = f"Error in {config} directory observer {self.directory_observer_count-1}:  {e}"
                self.failures.append(error)
                continue
            try:
                directory_observer.observe()
                directory_observer.log()
            except Exception as e:
                self.directory_observer_failure_count += 1
                error = f"{config} directory observer {directory_observer.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.directory_observer_failure_count == 0

    def construct_duplicate_remover(self, yaml_dict={}):
        name = yaml_dict["name"]
        source_dir = Location.construct(yaml_dict["source_dir"]).root
        recursive = Utils.get_from_dict(yaml_dict, "recursive", True)
        select_for_folder_depth = Utils.get_from_dict(yaml_dict, "select_for_folder_depth", None)
        exclude_dirs = Utils.get_from_dict(yaml_dict, "exclude_dirs", [])
        preferred_delete_dirs = Utils.get_from_dict(yaml_dict, "preferred_delete_dirs", [])
        return DuplicateRemover(name, source_dir, select_for_folder_depth=select_for_folder_depth,
                                recursive=recursive, exclude_dirs=exclude_dirs, preferred_delete_dirs=preferred_delete_dirs)

    def construct_batch_renamer(self, yaml_dict={}):
        name = yaml_dict["name"]
        mappings = FilenameMappingDefinition.construct_mappings(yaml_dict["mappings"])
        locations = [Location.construct(location) for location in yaml_dict["locations"]]
        renamer_function = yaml_dict["function"]
        test = Utils.get_from_dict(yaml_dict, "test", self.test)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        renamer = BatchRenamer(name, mappings, locations, test=test, skip_confirm=skip_confirm)
        return renamer, renamer_function

    def construct_backup_manager(self, yaml_dict={}):
        name = yaml_dict["name"]
        test = Utils.get_from_dict(yaml_dict, "test", False)
        overwrite = Utils.get_from_dict(yaml_dict, "overwrite", False)
        warn_duplicates = Utils.get_from_dict(yaml_dict, "warn_duplicates", False)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        mappings = []

        for mapping in yaml_dict["backup_mappings"]:
            name = mapping["name"]
            source_dir = Location.construct(mapping["source_dir"]).root
            target_dir = Location.construct(mapping["target_dir"]).root
            file_types = FiletypesDefinition.get_definitions(mapping["file_types"])
            if "mode" in mapping:
                mode = BackupMode[mapping["mode"]]
            else:
                mode = BackupMode.PUSH
            exclude_dirs = [Location.construct(location).root for location in Utils.get_from_dict(mapping, "exclude_dirs", [])]
            exclude_removal_dirs = [Location.construct(location).root for location in Utils.get_from_dict(mapping, "exclude_removal_dirs", [])]
            mappings.append(BackupMapping(name=name, source_dir=source_dir, target_dir=target_dir, file_types=file_types, mode=mode,
                                          exclude_dirs=exclude_dirs, exclude_removal_dirs=exclude_removal_dirs))

        return BackupManager(name, mappings=mappings, test=test, overwrite=overwrite, warn_duplicates=warn_duplicates, skip_confirm=skip_confirm)

    def construct_directory_observer(self, yaml_dict={}):
        name = yaml_dict["name"]
        sortable_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "sortable_dirs", [])]
        extra_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "extra_dirs", [])]
        file_types = FiletypesDefinition.get_definitions(Utils.get_from_dict(yaml_dict, "file_types", media_file_types))
        return DirectoryObserver(name, sortable_dirs=sortable_dirs, extra_dirs=extra_dirs, file_types=file_types)



