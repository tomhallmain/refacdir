"""
Collect files from every subdirectory under a root whose name matches one of
configured labels into root/<label>/ (creating those folders as needed).

``subdir_depth`` limits how far below ``root`` a label directory may sit: the relative path
from ``root`` to that directory must have exactly ``subdir_depth + 1`` path components.
The default ``subdir_depth=1`` matches ``root/<top-level-child>/<label>/``. Each increment
adds one allowed intermediate segment before ``<label>``. ``subdir_depth=-1`` means no
depth limit (every matching folder name under ``root`` except the bucket ``root/<label>/``).

When ``test`` is True (YAML ``test: true`` or batch dry-run), :meth:`NamedSubdirCollector.run`
performs a dry run: it logs what would be moved and does not create directories, move files,
remove empty source trees, or prompt for confirmation.
"""
import os
from pathlib import Path

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


def _find_named_directories(
    root: str, name: str, *, subdir_depth: int = 1
) -> list[str]:
    """
    Return absolute paths of directories named `name` under `root`, excluding
    root/name (the collection bucket at the tree root).

    If ``subdir_depth`` is not ``-1``, only directories whose relative path from
    ``root`` has exactly ``subdir_depth + 1`` components are included (so ``1`` →
    ``<top-level-child>/<name>``).
    """
    root = os.path.abspath(root)
    bucket = os.path.normpath(os.path.join(root, name))
    root_resolved = Path(root).resolve()
    found: list[str] = []
    for dirpath, _dirnames, _filenames in os.walk(root):
        if os.path.basename(dirpath) != name:
            continue
        dir_abs = os.path.abspath(dirpath)
        if os.path.normpath(dir_abs) == bucket:
            continue
        if subdir_depth != -1:
            try:
                rel_parts = Path(dir_abs).resolve().relative_to(root_resolved).parts
            except ValueError:
                continue
            if len(rel_parts) != subdir_depth + 1:
                continue
        found.append(dir_abs)
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
        subdir_depth: int = 1,
    ):
        """
        :param test: If True, dry-run only (no moves, no mkdir beyond reads, no clearing sources).
        :param subdir_depth: Number of path segments under ``root`` down to and including the
            label folder, minus one (default ``1`` → ``root/<child>/<label>/``). Use ``-1`` for
            any depth.
        """
        if not isinstance(subdir_depth, int) or subdir_depth < -1:
            raise Exception(
                f"subdir_depth must be an integer >= -1 (use -1 for unlimited depth), got {subdir_depth!r}"
            )
        self.name = name
        self.root = os.path.abspath(Utils.fix_path(root))
        self.subdir_names = list(subdir_names)
        self.test = test
        self.skip_confirm = skip_confirm
        self.clear_sources = clear_sources
        self.subdir_depth = subdir_depth

    def _collect_work(self) -> tuple[list[tuple[str, str]], set[str]]:
        """
        Build ordered (label, src_file) pairs and the set of source directories to clear.
        Each source file appears once (deduped) even when nested named dirs overlap.
        """
        sources_to_clear: set[str] = set()
        seen_files: set[str] = set()
        work_items: list[tuple[str, str]] = []

        for label in self.subdir_names:
            for source_dir in _find_named_directories(
                self.root,
                label,
                subdir_depth=self.subdir_depth,
            ):
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

    def preview(self) -> dict:
        """
        Read-only preview of what ``run()`` would collect/move — the same
        ``_collect_work`` scan ``run()`` itself uses, without moving anything
        or clearing any source directory, regardless of ``self.test``. Used
        by refacdir/llm/preview.py's match/affected-file preview (Phase 4,
        docs/LLM_CONFIG_CHAT_SCOPE.md).

        Returns ``{"work_items": [(label, src_file), ...], "sources_to_clear": [...]}``.
        A nonexistent ``root`` (a valid state for a not-yet-existing draft —
        see docs/LLM_CONFIG_CHAT_SCOPE.md's Phase 2 entry) simply yields no
        work items rather than raising, matching ``_collect_work``'s own
        os.walk-based behavior.
        """
        work_items, sources_to_clear = self._collect_work()
        return {"work_items": work_items, "sources_to_clear": sorted(sources_to_clear)}

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
