from enum import Enum
from glob import glob
import os
import yaml

from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMode, FileMode, HashMode, BackupMapping

from refacdir.batch_renamer import BatchRenamer, Location, DirectoryFlattener
from refacdir.config import Config
from refacdir.directory_observer import DirectoryObserver, media_file_types
from refacdir.duplicate_remover import DuplicateRemover
from refacdir.image_categorizer import ImageCategorizer
from refacdir.utils import Utils
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition


class BatchArgs:
    configs = {}

    def __init__(self, recache_configs=False):
        self.verbose = False
        self.test = False
        self.skip_confirm = False
        self.only_observers = False
        if len(self.configs) == 0 or recache_configs:
            BatchArgs.setup_configs()

    def validate(self):
        if len(BatchArgs.configs) == 0:
            raise Exception("No config files found!")
        return True

    @staticmethod
    def override_configs(filtered_configs):
        BatchArgs.configs = filtered_configs

    @staticmethod
    def update_config_state(config_path, will_run):
        """Update a single config's will_run state without reloading from files"""
        if config_path in BatchArgs.configs:
            BatchArgs.configs[config_path] = will_run

    @staticmethod
    def setup_configs(recache=True):
        if not recache and len(BatchArgs.configs) > 0:
            return

        master_config_file = os.path.join(Config.CONFIGS_DIR_LOC, "master_config.yaml")
        if not os.path.exists(master_config_file):
            master_config_file = os.path.join(Config.CONFIGS_DIR_LOC, "master_config_example.yaml")
            if not os.path.exists(master_config_file):
                print("No master config file found, parsing config list.")
                configs = sorted(glob("configs/*.yaml", recursive=False))
                for config in configs:
                    BatchArgs.configs[config] = None
                return
            else:
                print("master_config.yaml not found, using master_config_example.yaml instead.")

        try:
            master_config_yaml = yaml.load(open(master_config_file), Loader=yaml.FullLoader)
        except yaml.YAMLError as e:
            print(f"Error loading {master_config_file}: {e}")
            configs = sorted(glob("configs/*.yaml", recursive=False))
            for config in configs:
                BatchArgs.configs[config] = None
            return

        for config in master_config_yaml["configs"]:
            print(f"Config: {config}")
            BatchArgs.configs["configs/" + config["config_file"]] = config["will_run"]

class ActionType(Enum):
    # NOTE action type values must not be changed without also updating the func names of BatchJob
    BACKUP = 'BACKUP'
    RENAMER = 'RENAMER'
    DUPLICATE_REMOVER = 'DUPLICATE_REMOVER'
    DIRECTORY_OBSERVER = 'DIRECTORY_OBSERVER'
    DIRECTORY_FLATTENER = 'DIRECTORY_FLATTENER'
    IMAGE_CATEGORIZER = 'IMAGE_CATEGORIZER'

    def get_varname(self):
        return self.value.lower()

    def __str__(self) -> str:
        return self.value.lower().replace('_', ' ')


class BatchJob:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, args=BatchArgs()):
        self.cwd = os.getcwd()
        self.args = args
        self.configurations = BatchArgs.configs
        self.counts_map = {}
        self.failure_counts_map = {}
        for action_type in ActionType.__members__.values():
            self.counts_map[action_type] = 0
            self.failure_counts_map[action_type] = 0
        self.failures = []
        self.test = args.test
        self.skip_confirm = args.skip_confirm
        self.cancelled = False
        
        temp_full_path_example = None
        for config in self.configurations:
            if config.endswith("config_example.yaml"):
                temp_full_path_example = config

        if temp_full_path_example:
            if len(self.configurations) == 1:
                raise Exception("Excluded example config file! Please change name of config_example.yaml to ensure it is included.")
            del self.configurations[temp_full_path_example]


    def run(self):
        try:
            for config, will_run in self.configurations.items():
                if will_run == False:
                    continue
                os.chdir(self.cwd)
                self.run_config_file(config)
        except KeyboardInterrupt:
            print("Exiting prematurely at user request...")
            self.cancelled = True

    def run_config_file(self, config):
        with open(os.path.join(BatchJob.BASE_DIR, config), 'r') as f:
            try:
                config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
            except yaml.YAMLError as e:
                print(f"Error loading {config}: {e}")
                self.failures.append(f"Config {config} failed to load: {e}")
                return

            if "will_run" in config_wrapper and config_wrapper["will_run"] == False:
                print(f"{config} is set to will run = False, skipping...")
                return

            if "actions" not in config_wrapper:
                print(f"Error loading {config}: No actions found in config file!")
                self.failures.append(f"Config {config} failed to load: No actions found in config file!")
                return

            print(f"Running actions for {config}")

            FilenameMappingDefinition.add_named_functions(Utils.get_from_dict(config_wrapper, "filename_mapping_functions", []))
            FiletypesDefinition.add_named_definitions(Utils.get_from_dict(config_wrapper, "filetype_definitions", []))

            for i in range(len(config_wrapper["actions"])):
                action = config_wrapper["actions"][i]
                if not self.run_action(config, action, i):
                    return # If we fail to run an action then we stop running the config file

    def log_results(self):
        for action_type in ActionType.__members__.values():
            count_action_type = self.counts_map[action_type]
            if count_action_type > 0:
                print(f"{count_action_type} {action_type} job(s) completed")
        if len(self.failures) > 0:
            for action_type in ActionType.__members__.values():
                count_action_type = self.failure_counts_map[action_type]
                if count_action_type > 0:
                    print(f"{count_action_type} {action_type} job(s) failed")
            for failure in self.failures:
                print(failure)
        elif not self.cancelled:
            print("All operations completed successfully")

    def run_action(self, config, action, idx):
        try:
            action_type_string = action["type"]
            action_type = ActionType[action_type_string]
            if self.args.only_observers and ActionType.DIRECTORY_OBSERVER != action_type:
                print(f"{config} - Skipping {action_type} action")
                return True
            print(f"Running action type: {action_type}")
            if action_type == ActionType.RENAMER:
                return self.run_renamers(config, action["mappings"])
            else:
                return self.run_multi_action(config, action_type, action["mappings"])
        except KeyError as e:
            self.failures.append(f"Invalid action configuration in {config} index {idx}: {e}")
            return False
        except Exception as e:
            self.failures.append(f"Failed to run action index {idx} in {config}: {e}")
            return False

    def run_multi_action(self, config, action_type, actions):
        constructor_func_name = f"construct_{action_type.get_varname()}"
        for _action in actions:
            self.counts_map[action_type] += 1
            try:
                constructor_func = getattr(self, constructor_func_name)
                action = constructor_func(_action)
            except Exception as e:
                self.failure_counts_map[action_type] += 1
                if "name" in _action:
                    name = _action["name"]
                    error = f"Error in {config} {action_type} {name}:  {e}"
                else:
                    _action_index = self.counts_map[action_type] - 1
                    error = f"Error in {config} {action_type} {_action_index}:  {e}"
                self.failures.append(error)
                continue
            try:
                action.run()
            except Exception as e:
                self.failure_counts_map[action_type] += 1
                error = f"{config} {action_type} {action.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.failure_counts_map[action_type] == 0

    def run_renamers(self, config, renamers):
        for _renamer in renamers:
            self.counts_map[ActionType.RENAMER] += 1
            try:
                renamer, renamer_function = self.construct_batch_renamer(_renamer)
            except KeyError as e:
                self.failure_counts_map[ActionType.RENAMER] += 1
                if "name" in _renamer:
                    name = _renamer["name"]
                    error = f"Error in {config} renamer {name}:  {e}"
                else:
                    rename_index = self.counts_map[ActionType.RENAMER] - 1
                    error = f"Error in {config} renamer {rename_index}:  {e}"
                self.failures.append(error)
                print(error)
                continue
            try:
                renamer.execute(renamer_function)
            except Exception as e:
                self.failure_counts_map[ActionType.RENAMER] += 1
                error = f"{config} renamer {renamer.name} failed:  {e}"
                self.failures.append(error)
                print(error)
        return self.failure_counts_map[ActionType.RENAMER] == 0

    def construct_duplicate_remover(self, yaml_dict={}):
        name = yaml_dict["name"]
        source_dirs = [Location.construct(location).root for location in yaml_dict["source_dirs"]]
        recursive = Utils.get_from_dict(yaml_dict, "recursive", True)
        select_for_folder_depth = Utils.get_from_dict(yaml_dict, "select_for_folder_depth", None)
        exclude_dirs = Utils.get_from_dict(yaml_dict, "exclude_dirs", [])
        preferred_delete_dirs = Utils.get_from_dict(yaml_dict, "preferred_delete_dirs", [])
        return DuplicateRemover(name, source_dirs, select_for_folder_depth=select_for_folder_depth,
                                recursive=recursive, exclude_dirs=exclude_dirs, preferred_delete_dirs=preferred_delete_dirs)

    def construct_batch_renamer(self, yaml_dict={}):
        name = yaml_dict["name"]
        mappings = FilenameMappingDefinition.construct_mappings(yaml_dict["mappings"])
        locations = [Location.construct(location) for location in yaml_dict["locations"]]
        renamer_function = yaml_dict["function"]
        test = Utils.get_from_dict(yaml_dict, "test", self.test)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        recursive = Utils.get_from_dict(yaml_dict, "recursive", True)
        make_dirs = Utils.get_from_dict(yaml_dict, "make_dirs", True)
        find_unused_filenames = Utils.get_from_dict(yaml_dict, "find_unused_filenames", False)
        renamer = BatchRenamer(name, mappings, locations, test=test, skip_confirm=skip_confirm,
                               recursive=recursive, make_dirs=make_dirs, find_unused_filenames=find_unused_filenames)
        return renamer, renamer_function

    def construct_directory_flattener(self, yaml_dict={}):
        name = yaml_dict["name"]
        location = Utils.get_from_dict(yaml_dict, "location", None)
        if not location:
            raise Exception("No location found for directory flattener config!")
        search_patterns = Utils.get_from_dict(yaml_dict, "search_patterns", [])
        test = Utils.get_from_dict(yaml_dict, "test", self.test)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        return DirectoryFlattener(name, location, search_patterns, test=test, skip_confirm=skip_confirm)

    def construct_backup(self, yaml_dict={}):
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
            will_run = Utils.get_from_dict(mapping, "will_run", True)
            file_types = FiletypesDefinition.get_definitions(mapping["file_types"])
            if "mode" in mapping:
                mode = BackupMode[mapping["mode"]]
            else:
                mode = BackupMode.PUSH
            if "file_mode" in mapping:
                file_mode = FileMode[mapping["file_mode"]]
            else:
                file_mode = FileMode.FILES_AND_DIRS
            if "hash_mode" in mapping:
                hash_mode = HashMode[mapping["hash_mode"]]
            else:
                hash_mode = HashMode.SHA256
            exclude_dirs = [Location.construct(location).root for location in Utils.get_from_dict(mapping, "exclude_dirs", [])]
            exclude_removal_dirs = [Location.construct(location).root for location in Utils.get_from_dict(mapping, "exclude_removal_dirs", [])]
            mappings.append(BackupMapping(name=name, source_dir=source_dir, target_dir=target_dir, file_types=file_types,
                                          mode=mode, file_mode=file_mode, hash_mode=hash_mode,
                                          exclude_dirs=exclude_dirs, exclude_removal_dirs=exclude_removal_dirs, will_run=will_run))

        return BackupManager(name, mappings=mappings, test=test, overwrite=overwrite, warn_duplicates=warn_duplicates, skip_confirm=skip_confirm)

    def construct_directory_observer(self, yaml_dict={}):
        name = yaml_dict["name"]
        sortable_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "sortable_dirs", [])]
        extra_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "extra_dirs", [])]
        parent_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "parent_dirs", [])]
        exclude_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "exclude_dirs", [])]
        file_types = FiletypesDefinition.get_definitions(Utils.get_from_dict(yaml_dict, "file_types", media_file_types))
        return DirectoryObserver(name, sortable_dirs=sortable_dirs, extra_dirs=extra_dirs, parent_dirs=parent_dirs, exclude_dirs=exclude_dirs, file_types=file_types)

    def construct_image_categorizer(self, yaml_dict={}):
        name = yaml_dict["name"]
        test = Utils.get_from_dict(yaml_dict, "test", self.test)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        source_dir = Location.construct(yaml_dict["source_dir"]).root
        file_types = FiletypesDefinition.get_definitions(Utils.get_from_dict(yaml_dict, "file_types", [".png", ".jpg", ".jpeg"]))
        exclude_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "exclude_dirs", [])]
        categories = Utils.get_from_dict(yaml_dict, "categories", [])
        recursive = Utils.get_from_dict(yaml_dict, "recursive", True)
        return ImageCategorizer(name, test=test, source_dir=source_dir, exclude_dirs=exclude_dirs,
                                file_types=file_types, categories=categories, skip_confirm=skip_confirm,
                                recursive=recursive)




