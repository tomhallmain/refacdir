"""
Collect files from every subdirectory under a root whose name matches one of
configured labels into root/<label>/ (creating those folders as needed).

When ``test`` is True (YAML ``test: true`` or batch dry-run), :meth:`NamedSubdirCollector.run`
performs a dry run: it logs what would be moved and does not create directories, move files,
remove empty source trees, or prompt for confirmation.
"""
import os

from refacdir.file_renamer import FileRenamer
from refacdir.utils.logger import setup_logger
from refacdir.utils.utils import Utils

logger = setup_logger("named_subdir_collector")


def _is_under(path: str, ancestor: str) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    ancestor = os.path.normcase(os.path.abspath(ancestor))
    if path == ancestor:
        return True
    prefix = ancestor + os.sep
    return path.startswith(prefix)


def _unique_basename(dest_dir: str, basename: str) -> str:
    """Pick a non-colliding filename in dest_dir; never overwrites existing files."""
    candidate = os.path.join(dest_dir, basename)
    if not os.path.exists(candidate):
        return basename
    helper = FileRenamer(root=dest_dir, test=True, log_changes=False)
    return helper.get_unique_filename(dest_dir, basename)


def _find_named_directories(root: str, name: str) -> list[str]:
    """
    Return absolute paths of directories named `name` under `root`, excluding
    root/name (the collection bucket at the tree root).
    """
    root = os.path.abspath(root)
    bucket = os.path.normpath(os.path.join(root, name))
    found: list[str] = []
    for dirpath, _dirnames, _filenames in os.walk(root):
        if os.path.basename(dirpath) != name:
            continue
        if os.path.normpath(dirpath) == bucket:
            continue
        found.append(os.path.abspath(dirpath))
    return found


def _iter_files_under(directory: str):
    for dirpath, _dirnames, filenames in os.walk(directory):
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def _remove_empty_tree_leaf_up(start_dir: str, stop_at: str):
    """Remove empty directories from start_dir upward; stop before deleting stop_at or its ancestors."""
    stop_at = os.path.abspath(stop_at)
    current = os.path.abspath(start_dir)
    while _is_under(current, stop_at) and current != stop_at:
        parent = os.path.dirname(current)
        try:
            os.rmdir(current)
        except OSError:
            break
        current = parent


def _allocate_unique_for_test(dest_dir: str, basename: str, occupied: set[str]) -> str:
    """Sequential unique names for dry-run (mirrors FileRenamer.get_unique_filename)."""
    candidate = basename
    if candidate not in occupied:
        occupied.add(candidate)
        return candidate
    stem, ext = os.path.splitext(basename)
    attempts = 1
    while True:
        cand = f"{stem}_{attempts}{ext}"
        if cand not in occupied:
            occupied.add(cand)
            return cand
        attempts += 1
        if attempts > 99999:
            raise Exception("Unable to find a unique filename: " + basename)


class NamedSubdirCollector:
    def __init__(
        self,
        name: str,
        root: str,
        subdir_names: list[str],
        test: bool = False,
        skip_confirm: bool = False,
        clear_sources: bool = True,
    ):
        """
        :param test: If True, dry-run only (no moves, no mkdir beyond reads, no clearing sources).
        """
        self.name = name
        self.root = os.path.abspath(Utils.fix_path(root))
        self.subdir_names = list(subdir_names)
        self.test = test
        self.skip_confirm = skip_confirm
        self.clear_sources = clear_sources

    def _collect_work(self) -> tuple[list[tuple[str, str]], set[str]]:
        """
        Build ordered (label, src_file) pairs and the set of source directories to clear.
        Each source file appears once (deduped) even when nested named dirs overlap.
        """
        sources_to_clear: set[str] = set()
        seen_files: set[str] = set()
        work_items: list[tuple[str, str]] = []

        for label in self.subdir_names:
            for source_dir in _find_named_directories(self.root, label):
                sources_to_clear.add(source_dir)
                for src_file in _iter_files_under(source_dir):
                    src_abs = os.path.abspath(src_file)
                    if not os.path.isfile(src_abs):
                        continue
                    if src_abs in seen_files:
                        continue
                    seen_files.add(src_abs)
                    work_items.append((label, src_abs))

        return work_items, sources_to_clear

    def run(self):
        if not Utils.isdir_with_retry(self.root):
            raise Exception(f"Invalid root directory: {self.root}")
        if len(self.subdir_names) == 0:
            raise Exception("subdir_names must be a non-empty list")

        work_items, sources_to_clear = self._collect_work()

        if len(work_items) == 0:
            logger.warning(f"{self.name}: no files found to collect under {self.root}")
            return

        if self.test:
            logger.info(
                f"|=============== TEST (dry run) {self.name}: no files moved or dirs cleared ===============|"
            )
            occupied_by_label: dict[str, set[str]] = {label: set() for label in self.subdir_names}
            for label in self.subdir_names:
                dest_dir = os.path.join(self.root, label)
                if os.path.isdir(dest_dir):
                    for fn in os.listdir(dest_dir):
                        fp = os.path.join(dest_dir, fn)
                        if os.path.isfile(fp):
                            occupied_by_label[label].add(fn)

            logger.info(
                f"TEST {self.name}: would move {len(work_items)} file(s) under {self.root}"
            )
            for label, src_file in work_items[:50]:
                dest_dir = os.path.join(self.root, label)
                bn = os.path.basename(src_file)
                unique = _allocate_unique_for_test(dest_dir, bn, occupied_by_label[label])
                logger.info(f"TEST move {src_file} -> {os.path.join(dest_dir, unique)}")
            if len(work_items) > 50:
                logger.info(f"TEST ... and {len(work_items) - 50} more")
            return

        logger.info(
            f"{self.name}: collecting {len(work_items)} file(s) into bucket folders at {self.root}"
        )
        if not self.skip_confirm:
            confirm = input("Confirm named subdir collection (y/n): ")
            if confirm.lower() != "y":
                logger.info("Operation cancelled by user")
                return

        for label in self.subdir_names:
            os.makedirs(os.path.join(self.root, label), exist_ok=True)

        for label, src_file in work_items:
            dest_dir = os.path.join(self.root, label)
            os.makedirs(dest_dir, exist_ok=True)
            bn = os.path.basename(src_file)
            unique = _unique_basename(dest_dir, bn)
            dest_path = os.path.join(dest_dir, unique)
            if os.path.normcase(os.path.abspath(src_file)) == os.path.normcase(dest_path):
                continue
            Utils.move(src_file, dest_path)
            logger.info(f"moved {src_file} -> {dest_path}")

        if self.clear_sources:
            for source_dir in sorted(sources_to_clear, key=lambda p: len(p), reverse=True):
                _remove_empty_tree_leaf_up(source_dir, self.root)
