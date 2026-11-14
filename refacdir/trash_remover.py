"""
Empty user-chosen "trash" directories, and optionally the system trash.

Each target directory keeps existing; only its contents are removed. Entries
are planned first (read-only), and the same plan drives the dry run,
``preview()`` and the real removal, so the three agree.

Rules the plan follows:

- Symlinks, and on Windows every reparse point (junctions included), are
  removed as links and never descended into, so nothing outside a target
  directory is touched through one.
- ``exclude_dirs`` (relative to the target root) are kept with their contents.
- ``older_than_days`` and ``patterns`` filter files; a subdirectory is removed
  only when everything in it was removed, it passes the same age check, and
  ``remove_subdirectories`` is on.
- A target that is itself a symlink is emptied at the location it resolves
  to, and the safety check below is made against that resolved location.
- A target that resolves to a drive root, the home directory or an ancestor of
  it, the app's own data/config/install directories, or a system location is
  refused at construction, before any file is looked at.

The system trash is emptied whole: ``older_than_days`` and ``patterns`` do not
apply to it, and on freedesktop systems its ``files/`` and ``info/`` halves
are always removed together, so the two cannot get out of step.
"""
import fnmatch
import os
import stat
import sys
import time
from dataclasses import dataclass

from refacdir.utils.app_paths import RESOURCE_ROOT, app_data_dir
from refacdir.utils.confirm import confirm_action
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import LocalizedText, _
from refacdir.utils.utils import Utils

logger = setup_logger("trash_remover")

DELETE_MODES = ("permanent", "system_trash")
_DRY_RUN_LOG_LIMIT = 50
_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}

# A target equal to or inside one of these is refused.
_POSIX_SYSTEM_TREES = (
    "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc",
    "/sbin", "/sys", "/usr", "/System", "/Library",
)
# A target equal to one of these is refused; directories inside them are allowed.
_POSIX_SYSTEM_EXACT = (
    "/var", "/opt", "/tmp", "/mnt", "/media", "/srv", "/root", "/home",
    "/Users", "/Applications", "/Volumes", "/private",
)
_WINDOWS_SYSTEM_TREE_ENV = ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
_WINDOWS_SYSTEM_EXACT_ENV = ("ProgramData", "PUBLIC", "ALLUSERSPROFILE")

# SHEmptyRecycleBin flags: no confirmation dialog, no progress UI, no sound.
_SHERB_NOCONFIRMATION = 0x1
_SHERB_NOPROGRESSUI = 0x2
_SHERB_NOSOUND = 0x4
# SHEmptyRecycleBin fails with E_UNEXPECTED when the recycle bin is already empty.
_E_UNEXPECTED = -2147418113


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_same_or_under(path: str, ancestor: str) -> bool:
    if path == ancestor:
        return True
    return path.startswith(ancestor.rstrip(os.sep) + os.sep)


def _protected_trees() -> list:
    """Directories a target may be neither inside of nor an ancestor of."""
    paths = [app_data_dir(), RESOURCE_ROOT]
    for env_name in ("REFACDIR_CONFIGS_DIR", "REFACDIR_CACHE_DIR"):
        value = os.environ.get(env_name)
        if value:
            paths.append(value)
    return [_norm(p) for p in paths if p]


def _system_locations() -> tuple:
    """``(trees, exact)``: system dirs refused with their contents, and refused only themselves."""
    if os.name == "nt":
        trees = [os.environ.get(name) for name in _WINDOWS_SYSTEM_TREE_ENV]
        exact = [os.environ.get(name) for name in _WINDOWS_SYSTEM_EXACT_ENV]
    else:
        trees, exact = list(_POSIX_SYSTEM_TREES), list(_POSIX_SYSTEM_EXACT)
    return [_norm(p) for p in trees if p], [_norm(p) for p in exact if p]


def protected_directory_reason(path: str):
    """
    Return a ``LocalizedText`` saying why ``path`` may not be emptied, or None
    if it may. The path need not exist; symlinks are resolved first, so a link
    pointing at a protected location is refused as well.
    """
    if not isinstance(path, str) or path.strip() == "":
        return LocalizedText("A trash directory path must be a non-empty string")
    real = _norm(Utils.fix_path(path))
    if os.path.dirname(real) == real:
        return LocalizedText("{0} is a filesystem or drive root", path)
    home = _norm(os.path.expanduser("~"))
    if _is_same_or_under(home, real):
        return LocalizedText("{0} is the home directory or contains it", path)
    for protected in _protected_trees():
        if _is_same_or_under(real, protected) or _is_same_or_under(protected, real):
            return LocalizedText("{0} overlaps this application's own files ({1})", path, protected)
    trees, exact = _system_locations()
    for system_dir in trees:
        if _is_same_or_under(real, system_dir):
            return LocalizedText("{0} is a system directory", path)
    if real in exact:
        return LocalizedText("{0} is a system directory", path)
    return None


def parse_size(value):
    """Bytes from an int or a string such as ``"500MB"`` / ``"2 GB"`` (1024-based); None stays None."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(LocalizedText("Invalid size: {0}", value))
    if isinstance(value, (int, float)):
        amount, unit = value, "B"
    else:
        text = str(value).strip().upper().replace(" ", "")
        unit = next((u for u in sorted(_SIZE_UNITS, key=len, reverse=True) if text.endswith(u)), "B")
        number = text[: -len(unit)] if text.endswith(unit) else text
        try:
            amount = float(number)
        except ValueError:
            raise ValueError(LocalizedText("Invalid size: {0}", value)) from None
    if amount < 0:
        raise ValueError(LocalizedText("Invalid size: {0}", value))
    return int(amount * _SIZE_UNITS[unit])


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _is_link_like(path: str, st: os.stat_result) -> bool:
    """A symlink, or on Windows any reparse point (a junction is not reported as a symlink)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    attributes = getattr(st, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


@dataclass
class TrashEntry:
    path: str
    kind: str  # "file", "link" or "dir"
    size: int


@dataclass
class DirectoryPlan:
    root: str
    entries: list  # TrashEntry, children before their parent directory
    errors: list  # (path, reason) for entries that could not be read

    @property
    def size(self) -> int:
        return sum(entry.size for entry in self.entries)


class TrashRemover:
    def __init__(
        self,
        name: str,
        directories: list,
        delete_mode: str = "permanent",
        remove_subdirectories: bool = True,
        older_than_days=None,
        patterns=None,
        empty_system_trash: bool = False,
        max_entries=None,
        max_total_size=None,
        will_run: bool = True,
        test: bool = False,
        skip_confirm: bool = False,
        skip_missing_locations: bool = False,
        cancel_event=None,
        app_actions=None,
    ):
        """
        :param directories: ``Location`` objects whose contents are removed.
        :param skip_missing_locations: Skip a missing target directory with a
            warning instead of failing; fails anyway when every one is missing.
        :param cancel_event: ``threading.Event`` checked between directories.
        """
        self.name = name
        self.directories = list(directories or [])
        if delete_mode not in DELETE_MODES:
            raise ValueError(
                LocalizedText("Invalid delete_mode {0}, must be one of: {1}", delete_mode, ", ".join(DELETE_MODES))
            )
        self.delete_mode = delete_mode
        self.remove_subdirectories = bool(remove_subdirectories)
        if older_than_days is not None and (
            isinstance(older_than_days, bool) or not isinstance(older_than_days, (int, float)) or older_than_days < 0
        ):
            raise ValueError(LocalizedText("older_than_days must be a non-negative number, got {0}", older_than_days))
        self.older_than_days = older_than_days
        if isinstance(patterns, str):
            patterns = [patterns]
        self.patterns = list(patterns) if patterns else []
        self.empty_system_trash = bool(empty_system_trash)
        if max_entries is not None and (isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 0):
            raise ValueError(LocalizedText("max_entries must be a non-negative integer, got {0}", max_entries))
        self.max_entries = max_entries
        self.max_total_size = parse_size(max_total_size)
        self.will_run = will_run
        self.test = test
        self.skip_confirm = skip_confirm
        self.skip_missing_locations = skip_missing_locations
        self.cancel_event = cancel_event
        self.app_actions = app_actions
        self._validate_directories()

    def _validate_directories(self):
        if not self.directories and not self.empty_system_trash:
            raise ValueError(
                LocalizedText("{0}: directories is required unless empty_system_trash is true", self.name)
            )
        for location in self.directories:
            reason = protected_directory_reason(location.root)
            if reason is not None:
                raise ValueError(LocalizedText("{0}: refusing to empty this directory: {1}", self.name, reason))
        resolved = [(location.root, _norm(location.root)) for location in self.directories]
        for i, (root_a, real_a) in enumerate(resolved):
            for root_b, real_b in resolved[i + 1:]:
                if _is_same_or_under(real_a, real_b) or _is_same_or_under(real_b, real_a):
                    raise ValueError(
                        LocalizedText("{0}: trash directories {1} and {2} overlap", self.name, root_a, root_b)
                    )

    # ----- planning (read-only) -----

    def _age_ok(self, st: os.stat_result, now: float) -> bool:
        if self.older_than_days is None:
            return True
        return (now - st.st_mtime) >= self.older_than_days * 86400

    def _name_ok(self, name: str) -> bool:
        if not self.patterns:
            return True
        lowered = name.lower()
        return any(fnmatch.fnmatch(lowered, str(p).lower()) for p in self.patterns)

    def _plan_location(self, location, apply_filters: bool = True, remove_subdirectories=None) -> DirectoryPlan:
        root = location.root
        excluded = {os.path.normcase(os.path.normpath(os.path.join(root, d))) for d in location.exclude_dirs}
        remove_dirs = self.remove_subdirectories if remove_subdirectories is None else remove_subdirectories
        entries, errors = [], []
        now = time.time()

        def walk(directory: str) -> bool:
            """Plan ``directory``'s children; True when every child is planned for removal."""
            all_removed = True
            try:
                names = sorted(os.listdir(directory))
            except OSError as e:
                errors.append((directory, str(e)))
                return False
            for name in names:
                path = os.path.join(directory, name)
                if os.path.normcase(os.path.normpath(path)) in excluded:
                    all_removed = False
                    continue
                try:
                    st = os.lstat(path)
                except OSError as e:
                    errors.append((path, str(e)))
                    all_removed = False
                    continue
                if _is_link_like(path, st) or not stat.S_ISDIR(st.st_mode):
                    if not apply_filters or (self._age_ok(st, now) and self._name_ok(name)):
                        kind = "link" if _is_link_like(path, st) else "file"
                        entries.append(TrashEntry(path, kind, 0 if kind == "link" else st.st_size))
                    else:
                        all_removed = False
                    continue
                children_removed = walk(path)
                if children_removed and remove_dirs and (not apply_filters or self._age_ok(st, now)):
                    entries.append(TrashEntry(path, "dir", 0))
                else:
                    all_removed = False
            return all_removed

        walk(root)
        return DirectoryPlan(root=root, entries=entries, errors=errors)

    def _existing_directories(self) -> tuple:
        """``(present, missing)`` target locations."""
        present, missing = [], []
        for location in self.directories:
            (present if Utils.isdir_with_retry(location.root) else missing).append(location)
        return present, missing

    def preview(self) -> dict:
        """
        Read-only view of what ``run()`` would remove, regardless of
        ``self.test``. Missing directories are listed rather than raised, so a
        draft naming a directory that does not exist yet still previews.
        """
        present, missing = self._existing_directories()
        plans = [self._plan_location(location) for location in present]
        result = {
            "directories": {
                plan.root: {
                    "entries": [{"path": e.path, "kind": e.kind, "size": e.size} for e in plan.entries],
                    "entry_count": len(plan.entries),
                    "total_size": plan.size,
                    "unreadable": [{"path": p, "reason": r} for p, r in plan.errors],
                }
                for plan in plans
            },
            "missing": [location.root for location in missing],
            "entry_count": sum(len(plan.entries) for plan in plans),
            "total_size": sum(plan.size for plan in plans),
        }
        if self.empty_system_trash:
            result["system_trash"] = system_trash_summary()
        return result

    # ----- execution -----

    def run(self):
        if not self.will_run:
            logger.info(_("{0} - Skipping trash remover mapping (will_run=false)").format(self.name))
            return

        present, missing = self._existing_directories()
        if missing:
            missing_roots = ", ".join(location.root for location in missing)
            if not self.skip_missing_locations:
                raise Exception(LocalizedText("{0}: trash directory not found: {1}", self.name, missing_roots))
            if not present and self.directories:
                raise Exception(
                    LocalizedText("None of the locations for {0} were found: {1}", self.name, missing_roots)
                )
            for location in missing:
                logger.warning(_("{0} - Directory not found, skipping location: {1}").format(self.name, location.root))

        plans = [self._plan_location(location) for location in present]
        for plan in plans:
            for path, reason in plan.errors:
                logger.error(_("{0}: could not read {1}: {2}").format(self.name, path, reason))
        entry_count = sum(len(plan.entries) for plan in plans)
        total_size = sum(plan.size for plan in plans)

        if self.max_entries is not None and entry_count > self.max_entries:
            raise Exception(
                LocalizedText("{0}: {1} entries exceed max_entries {2}; nothing removed", self.name, entry_count, self.max_entries)
            )
        if self.max_total_size is not None and total_size > self.max_total_size:
            raise Exception(
                LocalizedText(
                    "{0}: {1} exceeds max_total_size {2}; nothing removed",
                    self.name, format_size(total_size), format_size(self.max_total_size),
                )
            )

        system_summary = system_trash_summary() if self.empty_system_trash else None

        if self.test:
            self._log_dry_run(plans, system_summary)
            return

        if entry_count == 0 and not self.empty_system_trash:
            logger.info(_("{0}: nothing to remove").format(self.name))
            return

        if not self.skip_confirm and not self._confirm(plans, entry_count, total_size, system_summary):
            logger.info(_("Operation cancelled by user"))
            return

        failures = sum(len(plan.errors) for plan in plans)
        for plan in plans:
            if self.cancel_event is not None and self.cancel_event.is_set():
                logger.warning(_("{0}: cancelled, remaining directories left as they are").format(self.name))
                break
            failures += self._remove_plan(plan)

        if self.empty_system_trash and not (self.cancel_event is not None and self.cancel_event.is_set()):
            failures += self._empty_system_trash()

        if failures:
            raise Exception(LocalizedText("{0}: {1} entries could not be removed", self.name, failures))

    def _log_dry_run(self, plans, system_summary):
        logger.info(
            "|=============== " + _("TEST (dry run) {0}: nothing removed").format(self.name) + " ===============|"
        )
        for plan in plans:
            logger.info(
                _("TEST {0}: would remove {1} entries ({2}) from {3}").format(
                    self.name, len(plan.entries), format_size(plan.size), plan.root
                )
            )
            for entry in plan.entries[:_DRY_RUN_LOG_LIMIT]:
                logger.info(_("TEST remove {0}").format(entry.path))
            if len(plan.entries) > _DRY_RUN_LOG_LIMIT:
                logger.info(_("TEST ... and {0} more").format(len(plan.entries) - _DRY_RUN_LOG_LIMIT))
        if system_summary is not None:
            logger.info(_("TEST {0}: would empty the system trash: {1}").format(self.name, system_summary["description"]))

    def _confirm(self, plans, entry_count, total_size, system_summary) -> bool:
        lines = [_("{0}: {1} entries ({2})").format(p.root, len(p.entries), format_size(p.size)) for p in plans]
        if system_summary is not None:
            lines.append(_("System trash: {0}").format(system_summary["description"]))
        if self.delete_mode == "permanent":
            message = _('"{0}": permanently delete {1} entries ({2})?').format(
                self.name, entry_count, format_size(total_size)
            )
        else:
            message = _('"{0}": move {1} entries ({2}) to the system trash?').format(
                self.name, entry_count, format_size(total_size)
            )
        if system_summary is not None:
            message += "\n" + _("The system trash will be emptied as well.")
        acknowledgement = None
        if self.delete_mode == "permanent" or system_summary is not None:
            acknowledgement = _("I understand that permanently deleted files cannot be restored.")
        return confirm_action(
            self.app_actions,
            _("Confirm emptying trash"),
            message,
            details=_("Directories:") + "\n" + "\n".join(lines),
            acknowledgement=acknowledgement,
        )

    def _remove_plan(self, plan: DirectoryPlan, delete_mode=None) -> int:
        """Remove a plan's entries; returns the number of failures."""
        mode = delete_mode or self.delete_mode
        entries = _collapse_for_trash(plan.entries) if mode == "system_trash" else plan.entries
        removed, freed, failed = 0, 0, 0
        for entry in entries:
            try:
                if mode == "system_trash":
                    _send_to_trash(entry.path)
                elif entry.kind == "dir":
                    os.rmdir(entry.path)
                elif entry.kind == "link":
                    _remove_link(entry.path)
                else:
                    os.remove(entry.path)
            except Exception as e:
                failed += 1
                logger.error(_("{0}: failed to remove {1}: {2}").format(self.name, entry.path, e))
                continue
            removed += 1
            freed += entry.size
            _record_removal(entry.path, "trash" if mode == "system_trash" else "delete", entry.kind)
        logger.info(
            _("{0}: removed {1} entries ({2}) from {3}, {4} failed").format(
                self.name, removed, format_size(freed), plan.root, failed
            )
        )
        return failed

    def _empty_system_trash(self) -> int:
        """Empty the system trash; returns the number of failures."""
        platform_name = _system_trash_platform()
        if platform_name == "windows":
            try:
                _empty_windows_recycle_bin()
            except Exception as e:
                logger.error(_("{0}: failed to empty the recycle bin: {1}").format(self.name, e))
                return 1
            _record_removal(_("<system trash>"), "empty_system_trash", "trash")
            logger.info(_("{0}: emptied the recycle bin").format(self.name))
            return 0
        if platform_name in ("freedesktop", "macos"):
            failures = 0
            for trash_dir in _posix_trash_dirs(platform_name):
                if not os.path.isdir(trash_dir):
                    continue
                plan = self._plan_location(_PlainLocation(trash_dir), apply_filters=False, remove_subdirectories=True)
                for path, reason in plan.errors:
                    logger.error(_("{0}: could not read {1}: {2}").format(self.name, path, reason))
                failures += len(plan.errors) + self._remove_plan(plan, delete_mode="permanent")
            return failures
        logger.error(_("{0}: emptying the system trash is not supported on this platform").format(self.name))
        return 1


@dataclass
class _PlainLocation:
    root: str
    exclude_dirs: tuple = ()


def _collapse_for_trash(entries: list) -> list:
    """Keep only the topmost entries: a directory planned whole is trashed as one item."""
    dirs = {os.path.normcase(e.path) for e in entries if e.kind == "dir"}
    kept = []
    for entry in entries:
        parent = os.path.dirname(os.path.normcase(entry.path))
        covered = False
        while parent and parent != os.path.dirname(parent):
            if parent in dirs:
                covered = True
                break
            parent = os.path.dirname(parent)
        if not covered:
            kept.append(entry)
    # A collapsed directory's size is that of everything it held.
    for entry in kept:
        if entry.kind == "dir":
            prefix = os.path.normcase(entry.path) + os.sep
            entry.size = sum(e.size for e in entries if os.path.normcase(e.path).startswith(prefix))
    return kept


def _remove_link(path: str):
    try:
        os.unlink(path)
    except OSError:
        if os.name == "nt":
            os.rmdir(path)  # a directory symlink or junction
        else:
            raise


def _send_to_trash(path: str):
    from send2trash import send2trash

    send2trash(os.path.normpath(path))


def _record_removal(path: str, op_type: str, kind: str):
    from refacdir.batch_job_history import record_file_operation

    record_file_operation(op_type, path, "", reversible=False, meta={"kind": kind})


def _system_trash_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "posix":
        return "freedesktop"
    return "unsupported"


def _posix_trash_dirs(platform_name: str) -> list:
    if platform_name == "macos":
        return [os.path.join(os.path.expanduser("~"), ".Trash")]
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    trash = os.path.join(data_home, "Trash")
    return [os.path.join(trash, "files"), os.path.join(trash, "info")]


def _query_windows_recycle_bin():
    """``(size, count)`` for all drives, or None if it cannot be queried."""
    try:
        from win32com.shell import shell

        size, count = shell.SHQueryRecycleBin(None)
        return int(size), int(count)
    except Exception as e:
        logger.debug(f"SHQueryRecycleBin failed: {e}")
        return None


def _empty_windows_recycle_bin():
    from win32com.shell import shell

    query = _query_windows_recycle_bin()
    if query is not None and query[1] == 0:
        return
    try:
        shell.SHEmptyRecycleBin(None, None, _SHERB_NOCONFIRMATION | _SHERB_NOPROGRESSUI | _SHERB_NOSOUND)
    except Exception as e:
        if getattr(e, "hresult", None) == _E_UNEXPECTED or (e.args and e.args[0] == _E_UNEXPECTED):
            return  # already empty
        raise


def system_trash_summary() -> dict:
    """Read-only description of the system trash: ``{platform, entry_count, total_size, description}``."""
    platform_name = _system_trash_platform()
    if platform_name == "windows":
        query = _query_windows_recycle_bin()
        if query is None:
            return {
                "platform": platform_name, "entry_count": None, "total_size": None,
                "description": _("contents could not be determined in advance"),
            }
        size, count = query
        return {
            "platform": platform_name, "entry_count": count, "total_size": size,
            "description": _("{0} entries ({1})").format(count, format_size(size)),
        }
    if platform_name in ("freedesktop", "macos"):
        count, size = 0, 0
        for trash_dir in _posix_trash_dirs(platform_name):
            if not os.path.isdir(trash_dir) or os.path.basename(trash_dir) == "info":
                continue
            try:
                names = os.listdir(trash_dir)
            except OSError:
                return {
                    "platform": platform_name, "entry_count": None, "total_size": None,
                    "description": _("contents could not be determined in advance"),
                }
            count += len(names)
            for dirpath, _dirnames, filenames in os.walk(trash_dir):
                for filename in filenames:
                    try:
                        size += os.lstat(os.path.join(dirpath, filename)).st_size
                    except OSError:
                        pass
        return {
            "platform": platform_name, "entry_count": count, "total_size": size,
            "description": _("{0} entries ({1})").format(count, format_size(size)),
        }
    return {
        "platform": platform_name, "entry_count": None, "total_size": None,
        "description": _("not supported on this platform"),
    }
