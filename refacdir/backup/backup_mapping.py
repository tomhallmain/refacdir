import json
import os
import shutil
from typing import Callable, Dict, List, Tuple, Optional

from .backup_modes import BackupMode, FileMode, HashMode, FailureType
from .backup_source_data import BackupSourceData
from .backup_state import BackupState
from .hash_manager import HashManager
from .safe_file_ops import SafeFileOps
from refacdir.utils.logger import setup_logger

# Set up logger for backup mapping
logger = setup_logger('backup_mapping')

# Progress / logging: avoid flooding logs on huge trees; still show liveness.
_HASH_PROGRESS_LOG_EVERY = 5000
_HASH_PROGRESS_UI_EVERY = 400

_FAILURE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup_failures.json")

try:
    from send2trash import send2trash
except Exception:
    logger.error("Could not import trashing utility - all deleted files will be deleted instantly")


def remove_file(path: str) -> bool:
    """Remove a file, preferably by moving to trash"""
    try:
        send2trash(os.path.normpath(path))
        return True
    except Exception as e:
        logger.error(f"Failed to send file to trash: {str(e)}")
        logger.error("Run pip install send2trash to enable trash functionality.")
        try:
            os.remove(path)
            return True
        except Exception as e:
            logger.error(f"Failed to remove file: {str(e)}")
            return False


def exception_as_dict(ex):
    return dict(type=ex.__class__.__name__,
                errno=getattr(ex, 'errno', None),
                message=str(ex),
                strerror=exception_as_dict(ex.strerror)
                if isinstance(ex.strerror, Exception) else ex.strerror)


class BackupTransaction:
    """Tracks backup operations and provides rollback capability"""
    
    def __init__(self):
        self.operations = []  # List of (operation, args, rollback_func) tuples
        self.completed = []  # List of completed operations for rollback
        
    def add_operation(self, operation, args, rollback_func):
        """Add an operation to the transaction"""
        self.operations.append((operation, args, rollback_func))
        
    def execute(self) -> Tuple[bool, Optional[str]]:
        """Execute all operations in the transaction"""
        try:
            for operation, args, _ in self.operations:
                success, error = operation(*args)
                if not success:
                    self.rollback()
                    return False, f"Operation failed: {error}"
                self.completed.append((operation, args))
            return True, None
        except Exception as e:
            self.rollback()
            return False, str(e)
            
    def rollback(self):
        """Roll back all completed operations in reverse order"""
        for operation, args in reversed(self.completed):
            try:
                for op, op_args, rollback_func in self.operations:
                    if op == operation and op_args == args:
                        if rollback_func:
                            rollback_func(*args)
                        break
            except Exception as e:
                logger.warning(f"Warning: Rollback operation failed: {str(e)}")


class BackupMapping:
    """Maps source directory to target directory for backup operations"""

    def __init__(self, name: str = "BackupMapping", 
                 source_dir: Optional[str] = None, 
                 target_dir: Optional[str] = None,
                 file_types: List[str] = [],
                 mode: BackupMode = BackupMode.PUSH,
                 file_mode: FileMode = FileMode.FILES_AND_DIRS,
                 hash_mode: HashMode = HashMode.SHA256,
                 exclude_dirs: List[str] = [],
                 exclude_removal_dirs: List[str] = [],
                 will_run: bool = True):
        """
        Initialize backup mapping.
        
        Args:
            name: Name of the backup mapping
            source_dir: Source directory path
            target_dir: Target directory path
            file_types: List of file extensions to include (empty for all)
            mode: Backup mode (PUSH, MIRROR, etc.)
            file_mode: File operation mode
            hash_mode: Hash mode for file comparison
            exclude_dirs: Directories to exclude from backup
            exclude_removal_dirs: Directories to exclude from removal
            will_run: Whether this mapping will be executed
        """
        if source_dir is None or target_dir is None:
            raise ValueError("Source and target directories must be specified")
            
        self.name = name
        self.source_dir = os.path.normpath(source_dir)
        self.target_dir = os.path.normpath(target_dir)
        self.file_types = file_types
        self.allows_all_file_types = len(self.file_types) == 0
        self.exclude_dirs = exclude_dirs
        self.exclude_removal_dirs = exclude_removal_dirs
        self.mode = mode
        self.file_mode = file_mode
        self.hash_mode = hash_mode
        self.will_run = will_run
        
        self._source_data = BackupSourceData(source_dir)
        self._hash_manager = HashManager(hash_mode)
        self._source_dirs: set = set()
        self._target_dirs: set = set()
        self._target_hash_dict: Dict[str, str] = {}
        self._expected_target_rel_paths: set = set()
        self.modified_target_files = []
        self.failures = []
        self.transaction = None
        self.state = None

    def _is_internal_backup_path(self, filepath: str) -> bool:
        norm = os.path.normpath(filepath)
        parts = norm.split(os.sep)
        if BackupSourceData.BACKUP_DIR in parts or ".backup_data" in parts:
            return True
        if os.path.basename(filepath) == BackupSourceData.FILEPATH:
            return True
        return False

    def _is_dir_excluded(self, dirpath: str) -> bool:
        return any(dirpath.startswith(d) or dirpath == d for d in self.exclude_dirs)

    def _should_include_in_backup_scan(self, filepath: str, name: str, is_target: bool = False) -> bool:
        if self._is_internal_backup_path(filepath):
            return False
        if self._is_file_excluded(filepath):
            return False
        if self.file_mode == FileMode.DIRS_ONLY:
            return False
        if not self._file_type_match(name):
            return False
        return True

    def _file_type_match(self, filename: str) -> bool:
        """Check if a file matches the allowed file types"""
        if self.allows_all_file_types:
            return True
        for ext in self.file_types:
            if filename.endswith(ext):
                return True
        if "." in filename:
            extension = filename[filename.rfind("."):]
            return extension.lower() in self.file_types
        return False

    def setup(
        self,
        overwrite: bool = False,
        warn_duplicates: bool = False,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        """Load persisted hash data and rebuild in-memory hash tables from source/target."""
        logger.info(
            "Backup mapping %r: loading persisted data from %s (overwrite=%s)",
            self.name,
            self.source_dir,
            overwrite,
        )
        self._source_data = BackupSourceData.load(self.source_dir, overwrite=overwrite)
        self._rebuild_hash_tables(progress=progress)
        if warn_duplicates:
            for h, files in self._source_data.hash_dict.items():
                if len(files) > 1:
                    logger.info(f"Duplicate content hash {h[:16]}... : {files}")
        if progress:
            progress(1.0, "scan complete")

    def _count_scan_files(self) -> Tuple[int, int]:
        """Count files that will be hashed; mirrors _rebuild_hash_tables walks (read-only)."""
        src_n = 0
        tgt_n = 0
        if os.path.exists(self.source_dir):
            for root, dirs, files in os.walk(self.source_dir):
                dirs[:] = [d for d in dirs if not self._is_dir_excluded(os.path.join(root, d))]
                if self.file_mode != FileMode.FILES_AND_DIRS:
                    continue
                for name in files:
                    filepath = os.path.join(root, name)
                    if not self._should_include_in_backup_scan(filepath, name):
                        continue
                    src_n += 1
        if os.path.exists(self.target_dir):
            for root, dirs, files in os.walk(self.target_dir):
                dirs[:] = [d for d in dirs if not self._is_dir_excluded(os.path.join(root, d))]
                for name in files:
                    filepath = os.path.join(root, name)
                    if not self._should_include_in_backup_scan(filepath, name, is_target=True):
                        continue
                    tgt_n += 1
        return src_n, tgt_n

    def _rebuild_hash_tables(
        self,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        self._source_data.hash_dict.clear()
        self._target_hash_dict.clear()
        self._hash_manager.clear_cache()
        self._source_dirs.clear()
        self._target_dirs.clear()
        self._expected_target_rel_paths.clear()

        total = 0
        if progress:
            progress(0.0, "counting files to scan…")
            src_n, tgt_n = self._count_scan_files()
            total = src_n + tgt_n
            logger.info(
                "Backup mapping %r: hashing up to %s files (source %s, target %s)",
                self.name,
                total,
                src_n,
                tgt_n,
            )
            progress(0.02, f"counted {total} files; hashing…")

        done = 0

        def _tick():
            nonlocal done
            done += 1
            if not progress or total <= 0:
                if done % _HASH_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "Backup mapping %r: hashed %s files (scan in progress)",
                        self.name,
                        done,
                    )
                return
            frac = min(1.0, done / total)
            if done % _HASH_PROGRESS_UI_EVERY == 0 or done == total:
                progress(0.02 + 0.98 * frac, f"hashed {done}/{total} files")
            if done % _HASH_PROGRESS_LOG_EVERY == 0 or done == total:
                logger.info(
                    "Backup mapping %r: hashed %s/%s files (~%d%%)",
                    self.name,
                    done,
                    total,
                    int(100 * frac),
                )

        if os.path.exists(self.source_dir):
            for root, dirs, files in os.walk(self.source_dir):
                dirs[:] = [d for d in dirs if not self._is_dir_excluded(os.path.join(root, d))]
                rel_root = os.path.relpath(root, self.source_dir)
                if rel_root != ".":
                    self._source_dirs.add(rel_root)
                if self.file_mode != FileMode.FILES_AND_DIRS:
                    continue
                for name in files:
                    filepath = os.path.join(root, name)
                    if not self._should_include_in_backup_scan(filepath, name):
                        continue
                    h = self._hash_manager.get_file_hash(filepath)
                    self._source_data.hash_dict[h].append(filepath)
                    rel = os.path.relpath(filepath, self.source_dir)
                    self._expected_target_rel_paths.add(os.path.normpath(rel))
                    _tick()

        if os.path.exists(self.target_dir):
            for root, dirs, files in os.walk(self.target_dir):
                dirs[:] = [d for d in dirs if not self._is_dir_excluded(os.path.join(root, d))]
                rel_root = os.path.relpath(root, self.target_dir)
                if rel_root != ".":
                    self._target_dirs.add(rel_root)
                for name in files:
                    filepath = os.path.join(root, name)
                    if not self._should_include_in_backup_scan(filepath, name, is_target=True):
                        continue
                    h = self._hash_manager.get_file_hash(filepath)
                    self._target_hash_dict[filepath] = h
                    _tick()

        if progress and total == 0:
            progress(1.0, "nothing to hash")
        elif not progress and done > 0:
            logger.info(
                "Backup mapping %r: finished hashing %s files",
                self.name,
                done,
            )

    def _build_target_path(self, source_filepath: str) -> str:
        relative_path = source_filepath.replace(os.path.join(self.source_dir, ""), "")
        if relative_path.startswith(self.source_dir):
            raise ValueError(f"Failed to build target path: source filepath was {source_filepath}, source dir was {self.source_dir}")
        return os.path.join(self.target_dir, relative_path)

    def _create_dirs(self, target_path: str, test: bool = True) -> None:
        """Create target directory structure"""
        parent = os.path.dirname(target_path)
        if parent and not os.path.exists(parent):
            logger.info(f"Creating directory: {parent}")
            if not test:
                success, error = SafeFileOps.atomic_create_dir(parent)
                if not success:
                    raise Exception(f"Failed to create directory: {error}")

    def _is_file_excluded(self, filepath: str) -> bool:
        """Check if a file should be excluded from backup"""
        if self.file_mode == FileMode.DIRS_ONLY and not os.path.isdir(filepath):
            return True
        return any(filepath.startswith(d) or filepath == d for d in self.exclude_dirs)

    def _is_file_removal_excluded(self, filepath: str) -> bool:
        """Check if a file should be excluded from removal"""
        return any(filepath.startswith(d) for d in self.exclude_removal_dirs)

    def _move_file(self, source_path: str, external_source: Optional[str] = None,
                   move_func = SafeFileOps.move, test: bool = True) -> None:
        """Move or copy a file with proper rollback support"""
        target_path = self._build_target_path(source_path)
        self._create_dirs(target_path, test=test)
        
        def rollback_copy(src: str, dst: str) -> None:
            if os.path.exists(dst):
                os.unlink(dst)
                
        def rollback_move(src: str, dst: str) -> None:
            if os.path.exists(dst):
                SafeFileOps.move(dst, src)
        
        try:
            if external_source:
                logger.info(f"Moving file within external dir to: {target_path} - previous location: {external_source}")
                source_path = external_source
            elif os.path.exists(target_path):
                logger.info(f"Replacing file: {target_path}")
            else:
                logger.info(f"Creating file: {target_path}")
                
            if not test:
                if self.transaction is None:
                    raise RuntimeError("Backup transaction not initialized")
                rollback = rollback_move if move_func == SafeFileOps.move else rollback_copy
                self.transaction.add_operation(move_func, (source_path, target_path), rollback)
                self.modified_target_files.append(target_path)
                
        except Exception as e:
            self.failures.append([FailureType.MOVE_FILE, str(e), target_path, source_path])

    def _remove_source_file(self, source_path: str, target_path: str, test: bool = True) -> None:
        """Remove a source file after successful backup"""
        if self._is_file_removal_excluded(source_path):
            return
        if not os.path.exists(target_path):
            msg = f"Could not remove source file {source_path} - target file {target_path} not found"
            logger.error(msg)
            self.failures.append([FailureType.REMOVE_SOURCE_FILE_TARGET_NOEXIST, msg, target_path, source_path])
            return
        logger.info(f"Removing file already backed up: {source_path}")
        if not test:
            try:
                if not remove_file(source_path):
                    raise Exception("Failed to remove file")
            except Exception as e:
                self.failures.append([FailureType.REMOVE_SOURCE_FILE, str(e), target_path, source_path])

    def _has_duplicates_in_target(self, content_hash: str) -> bool:
        return list(self._target_hash_dict.values()).count(content_hash) > 1

    def _move_func_for_path(self, source_path: str, default_move_func):
        """PUSH_AND_REMOVE uses copy (not move) when removal from this path is excluded — source must remain."""
        if self.mode == BackupMode.PUSH_AND_REMOVE and self._is_file_removal_excluded(source_path):
            return SafeFileOps.copy
        return default_move_func

    def _ensure_files(self, source_hash: str, source_files: List[str],
                      move_func=SafeFileOps.copy, test: bool = True) -> None:
        source_files = list(source_files)
        hashes_on_target = list(self._target_hash_dict.values())
        if source_hash not in hashes_on_target:
            for source_path in source_files:
                self._move_file(source_path, move_func=self._move_func_for_path(source_path, move_func), test=test)
            return
        for source_path in source_files:
            eff = self._move_func_for_path(source_path, move_func)
            target_path = self._build_target_path(source_path)
            current = self._target_hash_dict.get(target_path)
            if not os.path.exists(target_path) or current != source_hash:
                if self._has_duplicates_in_target(source_hash):
                    self._move_file(source_path, move_func=eff, test=test)
                else:
                    found = False
                    for fp, th in self._target_hash_dict.items():
                        if th == source_hash and fp not in self.modified_target_files and os.path.exists(fp):
                            self._move_file(source_path, external_source=fp, move_func=eff, test=test)
                            if eff == SafeFileOps.move:
                                self._remove_source_file(source_path, target_path, test=test)
                            found = True
                            break
                    if not found:
                        logger.warning("Could not reuse an existing target file; copying from source.")
                        self._move_file(source_path, move_func=eff, test=test)
            elif eff == SafeFileOps.move:
                self._remove_source_file(source_path, target_path, test=test)

    def _push(
        self,
        move_func=SafeFileOps.copy,
        test: bool = True,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        if self.file_mode == FileMode.DIRS_ONLY:
            new_dirs = sorted(set(self._source_dirs) - set(self._target_dirs))
            if new_dirs:
                logger.info(f"PUSHING DIRECTORY STRUCTURE TO {self.target_dir}")
            for directory in new_dirs:
                new_dir = os.path.join(self.target_dir, directory)
                logger.info(f"Making new directory: {new_dir}")
                if not test:
                    success, error = SafeFileOps.atomic_create_dir(new_dir)
                    if not success:
                        raise Exception(f"Failed to create directory: {error}")
            if progress:
                progress(1.0, "directory structure only")
            return

        new_dirs = sorted(set(self._source_dirs) - set(self._target_dirs))
        if new_dirs:
            logger.info(f"PUSHING DIRECTORY STRUCTURE TO {self.target_dir}")
        for directory in new_dirs:
            new_dir = os.path.join(self.target_dir, directory)
            logger.info(f"Making new directory: {new_dir}")
            if not test:
                success, error = SafeFileOps.atomic_create_dir(new_dir)
                if not success:
                    raise Exception(f"Failed to create directory: {error}")

        logger.info(f"PUSHING FILES TO {self.target_dir}")
        items = list(self._source_data.hash_dict.items())
        n_groups = len(items)
        if n_groups == 0:
            if progress:
                progress(1.0, "nothing to sync")
            return
        step = max(1, n_groups // 100)
        for j, (source_hash, paths) in enumerate(items):
            self._ensure_files(source_hash, paths, move_func=move_func, test=test)
            if j % step == 0 or j == n_groups - 1:
                if progress:
                    progress((j + 1) / n_groups, f"sync {j + 1}/{n_groups} content groups")
                logger.info(
                    "Backup mapping %r: sync progress %s/%s content groups",
                    self.name,
                    j + 1,
                    n_groups,
                )

    def _mirror_remove_stale(self, test: bool = True) -> None:
        if not os.path.exists(self.target_dir):
            return
        logger.info(f"Removing stale paths under {self.target_dir}")
        for root, _, files in os.walk(self.target_dir, topdown=False):
            for name in files:
                filepath = os.path.join(root, name)
                if self._is_internal_backup_path(filepath):
                    continue
                if self._is_file_excluded(filepath) or self._is_file_removal_excluded(filepath):
                    continue
                rel = os.path.relpath(filepath, self.target_dir)
                rel_n = os.path.normpath(rel)
                if rel_n not in self._expected_target_rel_paths:
                    logger.info(f"Removing stale file: {filepath}")
                    if not test:
                        try:
                            if os.path.isfile(filepath):
                                if not remove_file(filepath):
                                    raise OSError(f"Could not remove {filepath}")
                        except Exception as e:
                            self.failures.append([FailureType.REMOVE_STALE_FILE, str(e), filepath, "stale file"])

        for d in sorted(set(self._target_dirs) - set(self._source_dirs), key=lambda x: -len(x)):
            stale = os.path.join(self.target_dir, d)
            if not os.path.isdir(stale):
                continue
            if self._is_file_excluded(stale) or self._is_file_removal_excluded(stale):
                continue
            try:
                if not os.listdir(stale):
                    logger.info(f"Removing stale empty directory: {stale}")
                    if not test:
                        os.rmdir(stale)
            except OSError as e:
                self.failures.append([FailureType.REMOVE_STALE_DIRECTORY, str(e), stale, "stale directory"])

    def backup(
        self,
        test: bool = True,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        try:
            self.state = BackupState(self)
            success, error = self.state.validate_source()
            if not success:
                raise Exception(error)

            # Initialize transaction
            self.transaction = BackupTransaction()
            if self.is_push_mode():
                move_func = SafeFileOps.move if self.mode == BackupMode.PUSH_AND_REMOVE else SafeFileOps.copy
                self._push(move_func=move_func, test=test, progress=progress)
            elif self.is_mirror_mode():
                logger.info("Backup mapping %r: saving source metadata before mirror sync", self.name)
                self._source_data.save()
                self._push(SafeFileOps.copy, test=test, progress=progress)
            if not test:
                # Execute transaction
                success, error = self.transaction.execute()
                if not success:
                    raise Exception(error)
                if self.is_mirror_mode():
                    self._mirror_remove_stale(test=test)
                if not os.path.exists(self.target_dir):
                    SafeFileOps.atomic_create_dir(self.target_dir)
                success, error = self.state.validate_target()
                if not success:
                    raise Exception(error)
                success, error = self.state.verify_integrity()
                if not success:
                    if self.is_push_mode():
                        self.transaction.rollback()
                    raise Exception(error)
        except Exception as e:
            self.failures.append([FailureType.BACKUP_OPERATION, str(e),
                                  "Backup operation failed", str(e)])
            if not test and self.transaction and self.is_push_mode():
                self.transaction.rollback()
        finally:
            self.transaction = None
            self.state = None

    def is_push_mode(self) -> bool:
        """Check if backup is in push mode"""
        return self.mode in [BackupMode.PUSH, BackupMode.PUSH_DUPLICATES, BackupMode.PUSH_AND_REMOVE]

    def is_mirror_mode(self) -> bool:
        """Check if backup is in mirror mode"""
        return self.mode in [BackupMode.MIRROR, BackupMode.MIRROR_DUPLICATES]

    def preview_changes(self) -> Dict[str, List[str]]:
        """
        Summarize what ``backup()`` would do, using the hash tables ``setup()``
        already built (call ``setup()`` first) — read-only, no file I/O of its
        own beyond what ``setup()`` already performed.

        A best-effort approximation for preview purposes (see
        refacdir/llm/preview.py, Phase 4 of docs/LLM_CONFIG_CHAT_SCOPE.md): unlike
        the real push logic in ``_ensure_files``, this doesn't attempt the
        "reuse an existing identical file elsewhere in target" optimization —
        it may list a source file under ``to_add_or_update`` that ``backup()``
        would actually satisfy by renaming an existing target file into place
        instead of copying. Either way the file ends up present and correct at
        the target path; only the *method* (copy vs. rename-in-place) differs,
        which doesn't matter for reviewing WHAT would change before running for
        real. Note even ``backup(test=True)`` doesn't compute this today: the
        real dry-run path only skips the actual file mutations, it doesn't
        populate any structure describing what those mutations would have been.

        Returns ``{"to_add_or_update": [target_path, ...], "to_remove_stale": [...]}``.
        ``to_remove_stale`` is only ever non-empty for ``is_mirror_mode()``
        mappings (matching ``_mirror_remove_stale``, which only runs in mirror
        mode) and only lists files/dirs already present under ``target_dir``.
        """
        to_add_or_update = []
        for source_hash, source_paths in self._source_data.hash_dict.items():
            for source_path in source_paths:
                target_path = self._build_target_path(source_path)
                if self._target_hash_dict.get(target_path) != source_hash:
                    to_add_or_update.append(target_path)

        to_remove_stale = []
        if self.is_mirror_mode() and os.path.exists(self.target_dir):
            for target_path in self._target_hash_dict:
                if self._is_internal_backup_path(target_path):
                    continue
                if self._is_file_excluded(target_path) or self._is_file_removal_excluded(target_path):
                    continue
                rel = os.path.normpath(os.path.relpath(target_path, self.target_dir))
                if rel not in self._expected_target_rel_paths:
                    to_remove_stale.append(target_path)

        return {"to_add_or_update": to_add_or_update, "to_remove_stale": to_remove_stale}

    def report_failures(self) -> None:
        if len(self.failures) == 0:
            logger.info(f"No failures encountered for mapping: {self.source_dir} -> {self.target_dir}")
            return
        logger.warning(f"Failures encountered for mapping: {self.source_dir} -> {self.target_dir}")
        for f in self.failures:
            logger.warning(f"{f}")
            failure_type = f[0]
            if failure_type == FailureType.MOVE_FILE:
                logger.warning(f"Failed to move {f[3]} to {f[2]}: {f[1]}")
            elif failure_type == FailureType.REMOVE_SOURCE_FILE:
                logger.warning(f"Failed to remove file {f[3]}: {f[1]}")
            elif failure_type == FailureType.REMOVE_SOURCE_FILE_TARGET_NOEXIST:
                logger.warning(f"Failed to remove file {f[3]} (target missing): {f[1]}")
            elif failure_type == FailureType.REMOVE_STALE_FILE:
                logger.warning(f"Failed to remove stale file {f[2]}: {f[1]}")
            elif failure_type == FailureType.REMOVE_STALE_DIRECTORY:
                logger.warning(f"Failed to remove stale directory {f[2]}: {f[1]}")
        try:
            def _serialize(row):
                if isinstance(row, (list, tuple)):
                    return [str(row[0]), row[1], row[2], row[3]] if len(row) >= 4 else [str(x) for x in row]
                return row
            with open(_FAILURE_LOG, "w", encoding="utf-8") as out:
                json.dump([_serialize(x) for x in self.failures], out, indent=2)
            logger.info(f"Saved failure data to {_FAILURE_LOG}")
        except OSError as e:
            logger.warning(f"Could not write failure log: {e}")

    def clean(self) -> None:
        """Clean up backup state"""
        self.failures.clear()
        self.modified_target_files.clear()
        self._target_hash_dict.clear()
        self._expected_target_rel_paths.clear()
        if self.state:
            self.state.clear()
        self._hash_manager.clear_cache()

    def __str__(self) -> str:
        return f"""BackupMapping{{
    Name: {self.name}
    Source: {self.source_dir}
    Target: {self.target_dir}
    Mode: {self.mode}
    File types: {self.file_types}
    Exclude dirs: {self.exclude_dirs}
    Exclude removal dirs: {self.exclude_removal_dirs}
}}"""
