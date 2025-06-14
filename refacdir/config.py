import json
import os
from refacdir.utils.logger import setup_logger

# Set up logger for config
logger = setup_logger('config')

class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "configs")

    def __init__(self):
        self.dict = {}
        self.foreground_color = None
        self.background_color = None
        self.simple_image_compare_loc = None
        self.print_settings = False
        self.debug = False
        self.server_port = 6001
        self.server_password = "<PASSWORD>"

        dict_set = False
        configs =  [ f.path for f in os.scandir(Config.CONFIGS_DIR_LOC) if f.is_file() and f.path.endswith(".json") ]
        self.config_path = None

        for c in configs:
            if os.path.basename(c) == "config.json":
                self.config_path = c
                break
            elif os.path.basename(c) != "config_example.json":
                self.config_path = c

        if self.config_path is None:
            self.config_path = os.path.join(Config.CONFIGS_DIR_LOC, "config_example.json")

        try:
            self.dict = json.load(open(self.config_path, "r"))
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

        if dict_set:
            self.simple_image_compare_loc = self.validate_and_set_directory(key="simple_image_compare_loc")

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
        if self.simple_image_compare_loc is not None:
            logger.info(f" - Using simple image compare path at {self.simple_image_compare_loc}")
        else:
            pass
#            logger.info(f" - Simple image compare location is not set or invalid.")

config = Config()
