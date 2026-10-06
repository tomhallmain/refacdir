"""Per-user data locations under one app data dir, outside the source tree.

``%LOCALAPPDATA%\\refacdir`` on Windows, ``~/.local/share/refacdir`` elsewhere,
holding ``configs/`` (user YAML configs, config.json, master_config.yaml),
``cache/`` and ``logs/``. ``configs/`` sits directly under it so the
``configs/<name>.yaml`` keys ``BatchJob`` joins onto ``BASE_DIR`` reach the same
files ``Config.configs_dir()`` lists.

User files that earlier versions wrote inside the repo are moved here the first
time each directory is resolved; an existing file here is never overwritten.
``REFACDIR_APP_DATA_DIR`` relocates the whole tree and disables that move.
No ``refacdir`` imports at load time: the logger resolves its directory here.
"""

import glob
import os
import platform
import shutil

APP_DIR_NAME = "refacdir"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tracked templates for config.json and the YAML action configs.
EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")
# Where earlier versions kept user configs.
LEGACY_REPO_CONFIGS_DIR = os.path.join(REPO_ROOT, "configs")

# Locations earlier versions wrote cache files to, relative to REPO_ROOT.
_LEGACY_CACHE_PATTERNS = (
    os.path.join("refacdir", "app_info_cache.enc"),
    os.path.join("refacdir", "app_info_cache.enc.bak*"),
    os.path.join("refacdir", "app_info_cache.json"),
    os.path.join("refacdir", "filename_pattern_cache.enc"),
    os.path.join("refacdir", "llm_prompt_response_history_*.json"),
)

_migrated = set()


def app_data_dir() -> str:
    """Root of the per-user app data directory (not created here).

    ``REFACDIR_APP_DATA_DIR`` replaces it, e.g. for tests or a smoke test.
    """
    override = os.environ.get("REFACDIR_APP_DATA_DIR")
    if override:
        return override
    if platform.system().lower() == "windows":
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_DIR_NAME)


def user_logs_dir() -> str:
    path = os.path.join(app_data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def user_configs_dir() -> str:
    path = os.path.join(app_data_dir(), "configs")
    os.makedirs(path, exist_ok=True)
    _migrate_once("configs", path, _legacy_config_files())
    return path


def user_cache_dir() -> str:
    path = os.path.join(app_data_dir(), "cache")
    os.makedirs(path, exist_ok=True)
    _migrate_once("cache", path, _legacy_cache_files())
    return path


def _legacy_config_files() -> list:
    if not os.path.isdir(LEGACY_REPO_CONFIGS_DIR):
        return []
    return [entry.path for entry in os.scandir(LEGACY_REPO_CONFIGS_DIR)]


def _legacy_cache_files() -> list:
    paths = []
    for pattern in _LEGACY_CACHE_PATTERNS:
        paths.extend(glob.glob(os.path.join(REPO_ROOT, pattern)))
    return paths


def _migrate_once(kind: str, target_dir: str, sources: list) -> None:
    """Move *sources* into *target_dir*, once per process per *kind*.

    Skipped under ``REFACDIR_APP_DATA_DIR``: that dir is not the user's own, so
    repo files must not be moved into it.
    """
    if kind in _migrated or os.environ.get("REFACDIR_APP_DATA_DIR"):
        return
    _migrated.add(kind)
    if not sources:
        return

    # Imported here: the logger resolves its directory through this module.
    from refacdir.utils.logger import setup_logger
    logger = setup_logger("app_paths")

    for src in sorted(sources):
        dest = os.path.join(target_dir, os.path.basename(src))
        if os.path.exists(dest):
            logger.warning(
                f"Not moving {src}: {dest} already exists. Remove whichever copy is stale."
            )
            continue
        try:
            shutil.move(src, dest)
            logger.info(f"Moved {src} -> {dest}")
        except OSError as e:
            logger.error(f"Failed to move {src} -> {dest}: {e}")

    if kind == "configs" and os.path.isdir(LEGACY_REPO_CONFIGS_DIR):
        try:
            os.rmdir(LEGACY_REPO_CONFIGS_DIR)
            logger.info(f"Removed empty {LEGACY_REPO_CONFIGS_DIR}")
        except OSError:
            pass  # not empty: a file was left in place above
