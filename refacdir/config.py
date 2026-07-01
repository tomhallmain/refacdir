import json
import os
from refacdir.utils.logger import setup_logger

# Set up logger for config
logger = setup_logger('config')

class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "configs")

    @staticmethod
    def configs_dir():
        """Active configs directory (overridable via REFACDIR_CONFIGS_DIR for tests)."""
        return os.environ.get("REFACDIR_CONFIGS_DIR") or Config.CONFIGS_DIR_LOC

    @staticmethod
    def resolve_config_path():
        """Resolve the active server config JSON path, preferring config.json."""
        configs_dir = Config.configs_dir()
        if not os.path.isdir(configs_dir):
            return os.path.join(Config.CONFIGS_DIR_LOC, "config_example.json")

        configs = [
            f.path for f in os.scandir(configs_dir)
            if f.is_file() and f.path.endswith(".json")
        ]
        config_path = None
        for candidate in configs:
            basename = os.path.basename(candidate)
            if basename == "config.json":
                config_path = candidate
                break
            if basename != "config_example.json":
                config_path = candidate

        if config_path is None:
            config_path = os.path.join(configs_dir, "config_example.json")
        return config_path

    def __init__(self, config_path=None):
        self.dict = {}
        self.foreground_color = None
        self.background_color = None
        self.weidr_loc = None
        self.print_settings = False
        self.debug = False
        self.server_port = 6001
        self.server_password = "<PASSWORD>"

        self.config_path = config_path if config_path is not None else Config.resolve_config_path()

        dict_set = False
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.dict = json.load(f)
            dict_set = True
        except Exception as e:
            logger.error(str(e))
            logger.error("Unable to load config. Ensure config.json file is located in the configs directory of simple-image-comare.")

        self.set_values(str,
                        "foreground_color",
                        "background_color",
                        "server_password")
        self.set_values(int, "server_port")
        self.set_values(bool, "debug")

        if dict_set and "weidr_loc" in self.dict:
            try:
                self.weidr_loc = self.validate_and_set_directory(key="weidr_loc")
            except Exception as e:
                logger.warning(f"weidr_loc not applied from config: {e}")

        if self.print_settings:
            self.print_config_settings()

    def validate_and_set_directory(self, key):
        loc = self.dict[key]
        if loc and loc.strip() != "":
            if "{HOME}" in loc:
                loc = loc.strip().replace("{HOME}", os.path.expanduser("~"))
            if "{{USER_HOME}}" in loc:
                loc = loc.strip().replace("{{USER_HOME}}", os.path.expanduser("~"))
            if not os.path.isdir(loc):
                raise Exception(f"Invalid location provided for {key}: {loc}")
            return loc
        return None

    def set_values(self, type, *names):
        for name in names:
            if type:
                try:
                    setattr(self, name, type(self.dict[name]))
                except Exception as e:
                    logger.error(str(e))
                    logger.error(f"Failed to set {name} from config.json file. Ensure the value is set and of the correct type.")
            else:
                try:
                    setattr(self, name, self.dict[name])
                except Exception as e:
                    logger.error(str(e))
                    logger.error(f"Failed to set {name} from config.json file. Ensure the key is set.")

    def print_config_settings(self):
        logger.info("Settings active:")
        if self.weidr_loc is not None:
            logger.info(f" - Using simple image compare path at {self.weidr_loc}")
        else:
            pass
#            logger.info(f" - Simple image compare location is not set or invalid.")

config = Config()
