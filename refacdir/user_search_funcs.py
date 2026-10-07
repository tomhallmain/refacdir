"""Filename search functions the user defines in their own Python file.

``custom_file_name_search_funcs.py`` in the user configs dir is loaded with
importlib rather than imported, so it stays editable in a compiled build. It is
reloaded at the start of each batch run and whenever the configs dir changes;
if missing, it is created from the bundled template. A file that fails to load
leaves only the built-in functions (``refacdir.search_funcs``) for that run.
"""

import importlib.util
import os
import shutil
import threading
from typing import Callable, Optional

from refacdir import search_funcs
from refacdir.config import Config
from refacdir.utils.app_paths import resource_path
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import _

logger = setup_logger("user_search_funcs")

USER_FILE_NAME = "custom_file_name_search_funcs.py"
TEMPLATE_PATH = resource_path("examples", "custom_file_name_search_funcs.py.example")
# Distinct from any package module, so loading the file cannot shadow one.
_MODULE_NAME = "refacdir_user_search_funcs"

_lock = threading.Lock()
_functions: dict = {}
_load_error: Optional[str] = None
_loaded_path: Optional[str] = None


def user_file_path() -> str:
    return os.path.join(Config.configs_dir(), USER_FILE_NAME)


def _seed_from_template(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(TEMPLATE_PATH, path)
        logger.info(f"Created {path} from the template")
    except OSError as e:
        logger.warning(f"Could not create {path} from the template: {e}")


def reload(app_actions=None) -> None:
    """(Re)load the user file. Reports a load failure once, through *app_actions* if given."""
    global _functions, _load_error, _loaded_path
    with _lock:
        path = user_file_path()
        _functions, _load_error, _loaded_path = {}, None, path
        if not os.path.exists(path):
            _seed_from_template(path)
        if not os.path.isfile(path):
            return
        try:
            spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            _load_error = f"{path}: {type(e).__name__}: {e}"
            logger.error(f"Could not load user search functions from {_load_error}")
            if app_actions is not None:
                app_actions.alert(
                    _("User search functions not loaded"),
                    _("{0}\n\nThis run uses the built-in search functions only.").format(_load_error),
                    "error",
                )
            return
        # Only what the file defines: names it imports are not its functions.
        _functions = {
            name: obj
            for name, obj in vars(module).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == _MODULE_NAME
        }
        overridden = sorted(name for name in _functions if builtin(name) is not None)
        if overridden:
            logger.info(f"User search functions override built-ins: {', '.join(overridden)}")


def find(name: str) -> Optional[Callable]:
    """The user function *name*, or None. Loads the file on first use."""
    if _loaded_path != user_file_path():
        reload()
    return _functions.get(name)


def builtin(name: str) -> Optional[Callable]:
    """The built-in search function *name*, or None. Private helpers are not functions here."""
    if name.startswith("_"):
        return None
    obj = getattr(search_funcs, name, None)
    if not callable(obj) or getattr(obj, "__module__", None) != search_funcs.__name__:
        return None
    return obj


def load_error() -> Optional[str]:
    return _load_error
