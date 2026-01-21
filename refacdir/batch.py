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
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition
from refacdir.image_categorizer import ImageCategorizer
from refacdir.utils.translations import I18N
from refacdir.utils.utils import Utils
from refacdir.utils.logger import setup_logger

# Set up logger for batch operations
logger = setup_logger('batch')
_ = I18N._

class BatchArgs:
    configs = {}

    def __init__(self, recache_configs=False):
        self.verbose = False
        self.test = False
        self.skip_confirm = False
        self.only_observers = False
        self.app_actions = None
        if len(self.configs) == 0 or recache_configs:
            BatchArgs.setup_configs()

    def validate(self):
        if len(BatchArgs.configs) == 0:
            logger.error("No config files found!")
            raise Exception("No config files found!")
        return True

    @staticmethod
    def override_configs(filtered_configs):
        logger.info(f"Overriding configs with filtered set: {list(filtered_configs.keys())}")
        BatchArgs.configs = filtered_configs

    @staticmethod
    def update_config_state(config_path, will_run):
        """Update a single config's will_run state without reloading from files"""
        if config_path in BatchArgs.configs:
            logger.info(f"Updating config state: {config_path} -> {will_run}")
            BatchArgs.configs[config_path] = will_run

    @staticmethod
    def setup_configs(recache=True):
        if not recache and len(BatchArgs.configs) > 0:
            return

        master_config_file = os.path.join(Config.CONFIGS_DIR_LOC, "master_config.yaml")
        if not os.path.exists(master_config_file):
            master_config_file = os.path.join(Config.CONFIGS_DIR_LOC, "master_config_example.yaml")
            if not os.path.exists(master_config_file):
                logger.warning("No master config file found, parsing config list.")
                configs = sorted(glob("configs/*.yaml", recursive=False))
                for config in configs:
                    BatchArgs.configs[config] = None
                return
            else:
                logger.info("master_config.yaml not found, using master_config_example.yaml instead.")

        try:
            master_config_yaml = yaml.load(open(master_config_file), Loader=yaml.FullLoader)
            logger.info(f"Successfully loaded master config from {master_config_file}")
        except yaml.YAMLError as e:
            logger.error(f"Error loading {master_config_file}: {e}")
            configs = sorted(glob("configs/*.yaml", recursive=False))
            for config in configs:
                BatchArgs.configs[config] = None
            return

        for config in master_config_yaml["configs"]:
            logger.info(f"Loading config: {config['config_file']} (will_run: {config['will_run']})")
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
        logger.info("Initializing new batch job")
        self.cwd = os.getcwd()
        self.args = args
        self.configurations = BatchArgs.configs
        self.counts_map = {}
        self.failure_counts_map = {}
        self.app_actions = args.app_actions
        for action_type in ActionType.__members__.values():
            self.counts_map[action_type] = 0
            self.failure_counts_map[action_type] = 0
        self.failures = []
        self.test = args.test
        self.skip_confirm = args.skip_confirm
        self.cancelled = False
        
        # Progress tracking
        self.total_configs = sum(1 for will_run in self.configurations.values() if will_run)
        self.current_config_index = 0
        self.total_actions = 0
        self.current_action_index = 0
        self.skipped_actions = 0
        
        temp_full_path_example = None
        for config in self.configurations:
            if config.endswith("config_example.yaml"):
                temp_full_path_example = config

        if temp_full_path_example:
            if len(self.configurations) == 1:
                logger.error("Only example config file found - this is not allowed")
                raise Exception("Excluded example config file! Please change name of config_example.yaml to ensure it is included.")
            del self.configurations[temp_full_path_example]


    def run(self):
        try:
            logger.info("Starting batch job execution")
            # Count total actions across all configs
            self.total_actions = 0
            for config, will_run in self.configurations.items():
                if not will_run:
                    continue
                with open(os.path.join(BatchJob.BASE_DIR, config), 'r') as f:
                    try:
                        config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
                        if "actions" in config_wrapper:
                            self.total_actions += len(config_wrapper["actions"])
                    except yaml.YAMLError as e:
                        logger.error(f"Error loading config {config}: {e}")
                        continue

            logger.info(f"Total actions to process: {self.total_actions}")
            self.current_config_index = 0
            self.current_action_index = 0
            self.skipped_actions = 0
            
            if self.app_actions:
                self.app_actions.progress_text(_("Starting batch operations..."))
                self.app_actions.progress_bar_update(None, 0.0)

            for config, will_run in self.configurations.items():
                if will_run == False:
                    continue
                os.chdir(self.cwd)
                self.current_config_index += 1
                logger.info(f"Processing config {self.current_config_index}/{self.total_configs}: {config}")
                if self.app_actions:
                    self.app_actions.progress_text(f"Processing config {self.current_config_index}/{self.total_configs}: {config}")
                self.run_config_file(config)
                
            if self.app_actions:
                if self.skipped_actions > 0:
                    logger.info(f"Batch operations completed with {self.skipped_actions} skipped actions")
                    self.app_actions.progress_text(_("Batch operations completed (skipped {0} actions)").format(self.skipped_actions))
                else:
                    logger.info("Batch operations completed successfully")
                    self.app_actions.progress_text(_("Batch operations completed"))
                self.app_actions.progress_bar_reset()
                
        except KeyboardInterrupt:
            logger.warning("Batch job interrupted by user")
            print("Exiting prematurely at user request...")
            self.cancelled = True
            if self.app_actions:
                self.app_actions.progress_text(_("Operations cancelled by user"))
                self.app_actions.progress_bar_reset()

    def run_config_file(self, config):
        logger.info(f"Running config file: {config}")
        with open(os.path.join(BatchJob.BASE_DIR, config), 'r') as f:
            try:
                config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
            except yaml.YAMLError as e:
                logger.error(f"Error loading {config}: {e}")
                self.failures.append(f"Config {config} failed to load: {e}")
                return

            if "will_run" in config_wrapper and config_wrapper["will_run"] == False:
                logger.info(f"{config} is set to will run = False, skipping...")
                return

            if "actions" not in config_wrapper:
                logger.error(f"Error loading {config}: No actions found in config file!")
                self.failures.append(f"Config {config} failed to load: No actions found in config file!")
                return

            logger.info(f"Running {len(config_wrapper['actions'])} actions for {config}")

            FilenameMappingDefinition.add_named_functions(Utils.get_from_dict(config_wrapper, "filename_mapping_functions", []))
            FiletypesDefinition.add_named_definitions(Utils.get_from_dict(config_wrapper, "filetype_definitions", []))

            total_actions_in_config = len(config_wrapper["actions"])
            for i in range(len(config_wrapper["actions"])):
                action = config_wrapper["actions"][i]
                if not self.run_action(config, action, i):
                    # If action fails, count remaining actions as skipped
                    remaining_actions = total_actions_in_config - (i + 1)
                    self.skipped_actions += remaining_actions
                    logger.warning(f"Config {config} stopped after {i + 1} actions (skipped {remaining_actions} actions)")
                    if self.app_actions:
                        self.app_actions.progress_text(_("Config {0}/{1}: {2} stopped after {3} actions (skipped {4} actions)").format(self.current_config_index, self.total_configs, config, i + 1, remaining_actions))
                    return # If we fail to run an action then we stop running the config file
                
                # Update progress after action completes successfully
                self.current_action_index += 1
                if self.app_actions:
                    progress = self.current_action_index / self.total_actions
                    self.app_actions.progress_bar_update(None, progress)

    def log_results(self):
        logger.info("Logging batch job results")
        # Calculate totals
        total_completed = sum(self.counts_map.values())
        total_skipped = self.skipped_actions
        
        for action_type in ActionType.__members__.values():
            count_action_type = self.counts_map[action_type]
            if count_action_type > 0:
                logger.info(f"{count_action_type} {action_type} job(s) completed")
        if len(self.failures) > 0:
            for action_type in ActionType.__members__.values():
                count_action_type = self.failure_counts_map[action_type]
                if count_action_type > 0:
                    logger.warning(f"{count_action_type} {action_type} job(s) failed")
            for failure in self.failures:
                logger.error(failure)
            
            # Call alert if app_actions is available and there are failures
            if self.app_actions:
                message_parts = []
                if total_completed > 0:
                    message_parts.append(f"{total_completed} completed")
                if total_skipped > 0:
                    message_parts.append(f"{total_skipped} skipped")
                
                # List specific failures
                failure_list = "\n".join(self.failures)
                
                if message_parts:
                    message = f"{', '.join(message_parts)}.\n\nFailures:\n{failure_list}"
                else:
                    message = f"Failures:\n{failure_list}"
                
                self.app_actions.alert("Batch Operations Failed", message, "error")
        elif not self.cancelled:
            logger.info("All operations completed successfully")

    def run_action(self, config, action, idx):
        try:
            action_type_string = action["type"]
            action_type = ActionType[action_type_string]
            if self.args.only_observers and ActionType.DIRECTORY_OBSERVER != action_type:
                logger.info(f"{config} - Skipping {action_type} action")
                return True
            if self.app_actions:
                self.app_actions.progress_text(_("Config {0}/{1}: Running {2} action in {3}").format(self.current_config_index, self.total_configs, action_type, config))
            logger.info(f"Running action type: {action_type}")
            if action_type == ActionType.RENAMER:
                return self.run_renamers(config, action["mappings"])
            else:
                return self.run_multi_action(config, action_type, action["mappings"])
        except KeyError as e:
            error_msg = f"Invalid action configuration in {config} index {idx}: {e}"
            logger.error(error_msg)
            self.failures.append(error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to run action index {idx} in {config}: {e}"
            logger.error(error_msg)
            self.failures.append(error_msg)
            return False

    def run_multi_action(self, config, action_type, actions):
        constructor_func_name = f"construct_{action_type.get_varname()}"
        total_actions = len(actions)
        for action_index, _action in enumerate(actions):
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
                logger.error(error)
                self.failures.append(error)
                continue

            # Calculate sub-progress for this action
            if self.app_actions:
                # Calculate progress between current action and next action
                current_action_progress = (self.current_action_index - 1) / self.total_actions
                next_action_progress = self.current_action_index / self.total_actions
                # Interpolate based on which sub-action we're on
                sub_progress = current_action_progress + (next_action_progress - current_action_progress) * (action_index / total_actions)
                self.app_actions.progress_bar_update(None, sub_progress)
                self.app_actions.progress_text(_("Config {0}/{1}: Running {2} {3}/{4} in {5}").format(self.current_config_index, self.total_configs, action_type, action_index + 1, total_actions, config))

            try:
                action.run()
            except Exception as e:
                self.failure_counts_map[action_type] += 1
                error = f"{config} {action_type} {action.name} failed:  {e}"
                logger.error(error)
                self.failures.append(error)
        return self.failure_counts_map[action_type] == 0

    def run_renamers(self, config, renamers):
        total_renamers = len(renamers)
        for renamer_index, _renamer in enumerate(renamers):
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
                logger.error(error)
                self.failures.append(error)
                continue

            # Calculate sub-progress for this renamer
            if self.app_actions:
                # Calculate progress between current action and next action
                current_action_progress = (self.current_action_index - 1) / self.total_actions
                next_action_progress = self.current_action_index / self.total_actions
                # Interpolate based on which renamer we're on
                sub_progress = current_action_progress + (next_action_progress - current_action_progress) * (renamer_index / total_renamers)
                self.app_actions.progress_bar_update(None, sub_progress)
                self.app_actions.progress_text(_("Config {0}/{1}: Running renamer mapping {2}/{3} in {4}").format(self.current_config_index, self.total_configs, renamer_index + 1, total_renamers, config))

            try:
                renamer.execute(renamer_function)
            except Exception as e:
                self.failure_counts_map[ActionType.RENAMER] += 1
                error = f"{config} renamer {renamer.name} failed:  {e}"
                logger.error(error)
                self.failures.append(error)
        return self.failure_counts_map[ActionType.RENAMER] == 0

    def construct_duplicate_remover(self, yaml_dict={}):
        name = yaml_dict["name"]
        source_dirs = [Location.construct(location).root for location in yaml_dict["source_dirs"]]
        recursive = Utils.get_from_dict(yaml_dict, "recursive", True)
        select_for_folder_depth = Utils.get_from_dict(yaml_dict, "select_for_folder_depth", None)
        exclude_dirs = Utils.get_from_dict(yaml_dict, "exclude_dirs", [])
        preferred_delete_dirs = Utils.get_from_dict(yaml_dict, "preferred_delete_dirs", [])
        logger.info(f"Constructing duplicate remover: {name} with {len(source_dirs)} source directories")
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
        logger.info(f"Constructing batch renamer: {name} with {len(mappings)} mappings and {len(locations)} locations")
        renamer = BatchRenamer(name, mappings, locations, test=test, skip_confirm=skip_confirm,
                               recursive=recursive, make_dirs=make_dirs, find_unused_filenames=find_unused_filenames)
        return renamer, renamer_function

    def construct_directory_flattener(self, yaml_dict={}):
        name = yaml_dict["name"]
        location = Utils.get_from_dict(yaml_dict, "location", None)
        if not location:
            logger.error("No location found for directory flattener config!")
            raise Exception("No location found for directory flattener config!")
        search_patterns = Utils.get_from_dict(yaml_dict, "search_patterns", [])
        test = Utils.get_from_dict(yaml_dict, "test", self.test)
        skip_confirm = Utils.get_from_dict(yaml_dict, "skip_confirm", self.skip_confirm)
        logger.info(f"Constructing directory flattener: {name} with {len(search_patterns)} search patterns")
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

        logger.info(f"Constructing backup manager: {name} with {len(mappings)} backup mappings")
        return BackupManager(name, mappings=mappings, test=test, overwrite=overwrite, warn_duplicates=warn_duplicates, skip_confirm=skip_confirm)

    def construct_directory_observer(self, yaml_dict={}):
        name = yaml_dict["name"]
        sortable_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "sortable_dirs", [])]
        extra_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "extra_dirs", [])]
        parent_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "parent_dirs", [])]
        exclude_dirs = [Location.construct(location).root for location in Utils.get_from_dict(yaml_dict, "exclude_dirs", [])]
        file_types = FiletypesDefinition.get_definitions(Utils.get_from_dict(yaml_dict, "file_types", media_file_types))
        logger.info(f"Constructing directory observer: {name} with {len(sortable_dirs)} sortable dirs, {len(extra_dirs)} extra dirs, {len(parent_dirs)} parent dirs")
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
        logger.info(f"Constructing image categorizer: {name} with {len(categories)} categories and {len(file_types)} file types")
        return ImageCategorizer(name, test=test, source_dir=source_dir, exclude_dirs=exclude_dirs,
                                file_types=file_types, categories=categories, skip_confirm=skip_confirm,
                                recursive=recursive)




