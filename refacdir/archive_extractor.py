"""
Extract ZIP archives matching a name pattern and merge their contents into one
target directory.

Only ZIP archives are handled, through the standard library's ``zipfile``;
``refacdir/archive.py`` is a separate read-only 7-Zip-backed lister.

Two layouts, selected by ``preserve_structure``:

- Flat (default): every file lands directly in ``target_dir`` and the folders
  inside each archive are dropped. A name already taken gets the source
  archive's stem appended, plus the member's own folder when it had one
  (``report.txt`` -> ``report__data_2024.txt``, or
  ``report__data_2024__q1.txt``). A counter follows (``report__data_2024_1.txt``)
  only when that tagged name is taken too -- several archives sharing a stem,
  or the tagged name already sitting in ``target_dir``.
- ``preserve_structure: true``: each archive extracts under
  ``target_dir/<archive stem>/`` with its internal folders intact. Archives
  sharing a stem merge into that one folder, and a file collision inside it
  takes a counter suffix.

``target_dir`` is excluded from the search, so a file an earlier run extracted
is never picked up as input by a later one.

Members whose stored path would escape the target directory (absolute paths,
drive letters, ``..`` segments) are skipped -- an archive can otherwise direct
a write anywhere the process can reach.

When ``test`` is True (YAML ``test: true`` or a batch dry run), :meth:`ArchiveExtractor.run`
logs the planned extraction and writes nothing, creates no directory and deletes
no archive. Planning is shared with the real run, so a dry run reports the exact
destination names a real run would produce, collision suffixes included.
"""
import fnmatch
import os
import shutil
import unicodedata
import zipfile

from refacdir.backup.backup_mapping import remove_file
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import _
from refacdir.utils.utils import Utils

logger = setup_logger("archive_extractor")

_MAX_UNIQUE_ATTEMPTS = 99999
_DRY_RUN_LOG_LIMIT = 50


def _is_under(path: str, ancestor: str) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    ancestor = os.path.normcase(os.path.abspath(ancestor))
    if path == ancestor:
        return True
    return path.startswith(ancestor + os.sep)


def _normalise(value: str) -> str:
    """NFKC: folds NBSP to a plain space, drops zero-width marks, unifies compatibility forms."""
    return unicodedata.normalize("NFKC", value)


def _safe_relative_path(member: str):
    """
    Return ``member`` as a path safe to join onto the target directory, or None
    when it would escape: an absolute path, a drive-qualified path, or any
    ``..`` segment. Rejecting outright rather than stripping the offending
    segments keeps a crafted archive from landing a file outside the target.
    """
    normalized = member.replace("\\", "/")
    if normalized.startswith("/"):
        return None
    if len(normalized) > 1 and normalized[1] == ":":
        return None
    parts = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return os.path.join(*parts)


def _is_free(path: str, reserved: set) -> bool:
    return os.path.normcase(path) not in reserved and not os.path.exists(path)


def _allocate(dest_dir: str, filename: str, source_tag, reserved: set):
    """
    Pick a free path for ``filename`` in ``dest_dir``, reserve it, and return
    ``(path, renamed)``. ``source_tag`` (flat layout) is appended before any
    counter so a collision carries the name of the archive it came from; with no
    tag only a counter is added.

    Reserving is what lets planning and execution agree: a dry run writes
    nothing, so an ``os.path.exists`` test alone would hand every colliding
    member the same destination.
    """
    candidate = os.path.join(dest_dir, filename)
    if _is_free(candidate, reserved):
        reserved.add(os.path.normcase(candidate))
        return candidate, False

    stem, suffix = os.path.splitext(filename)
    if source_tag:
        candidate = os.path.join(dest_dir, f"{stem}__{source_tag}{suffix}")
        if _is_free(candidate, reserved):
            reserved.add(os.path.normcase(candidate))
            return candidate, True
        stem = f"{stem}__{source_tag}"

    counter = 1
    while counter <= _MAX_UNIQUE_ATTEMPTS:
        candidate = os.path.join(dest_dir, f"{stem}_{counter}{suffix}")
        if _is_free(candidate, reserved):
            reserved.add(os.path.normcase(candidate))
            return candidate, True
        counter += 1
    raise Exception(f"Unable to find a unique filename for {filename} in {dest_dir}")


def _group_by_archive(planned: list) -> dict:
    grouped = {}
    for item in planned:
        grouped.setdefault(item[0], []).append(item)
    return grouped


class ArchiveExtractor:
    def __init__(
        self,
        name: str,
        search_dir: str,
        target_dir: str,
        pattern: str = "*.zip",
        recursive: bool = True,
        normalise: bool = True,
        preserve_structure: bool = False,
        delete_sources: bool = False,
        test: bool = False,
        skip_confirm: bool = False,
    ):
        """
        :param pattern: fnmatch pattern tested against each archive's filename.
        :param normalise: NFKC-normalise both filename and pattern before matching,
            so a name carrying an NBSP or a decomposed accent still matches a
            pattern typed with the plain form.
        :param test: If True, dry run only (nothing extracted, created or deleted).
        """
        self.name = name
        self.search_dir = os.path.abspath(Utils.fix_path(search_dir))
        self.target_dir = os.path.abspath(Utils.fix_path(target_dir))
        self.pattern = pattern
        self.recursive = recursive
        self.normalise = normalise
        self.preserve_structure = preserve_structure
        self.delete_sources = delete_sources
        self.test = test
        self.skip_confirm = skip_confirm

    def find_archives(self) -> list:
        """ZIP paths under ``search_dir`` matching ``pattern``, with the target tree skipped."""
        pattern = _normalise(self.pattern) if self.normalise else self.pattern
        found = []
        for dirpath, dirnames, filenames in os.walk(self.search_dir):
            if _is_under(dirpath, self.target_dir):
                dirnames[:] = []
                continue
            if not self.recursive:
                dirnames[:] = []
            for filename in filenames:
                if os.path.splitext(filename)[1].lower() != ".zip":
                    continue
                candidate = _normalise(filename) if self.normalise else filename
                if fnmatch.fnmatch(candidate, pattern):
                    found.append(os.path.join(dirpath, filename))
        return sorted(found)

    def _plan(self):
        """
        Build the whole extraction plan without touching the filesystem.

        Returns ``(planned, unreadable)``: ``planned`` holds
        ``(archive, member, dest_path, renamed)`` in extraction order, and
        ``unreadable`` holds ``(archive, reason)`` for archives that could not be
        opened. ``run()``, its dry run and ``preview()`` all go through this, so
        the three never disagree about destinations.
        """
        planned = []
        unreadable = []
        reserved = set()

        for archive in self.find_archives():
            archive_tag = os.path.splitext(os.path.basename(archive))[0].replace(" ", "_")
            try:
                with zipfile.ZipFile(archive, "r") as zip_ref:
                    members = zip_ref.namelist()
            except zipfile.BadZipFile:
                unreadable.append((archive, "not a valid ZIP file"))
                continue
            except Exception as e:
                unreadable.append((archive, str(e)))
                continue

            for member in members:
                if member.endswith("/"):
                    continue
                relative = _safe_relative_path(member)
                if relative is None:
                    logger.warning(
                        f"{self.name}: skipping member with unsafe path {member!r} in {archive}"
                    )
                    continue
                basename = os.path.basename(relative)
                internal_dir = os.path.dirname(relative)
                if self.preserve_structure:
                    dest_dir = os.path.join(self.target_dir, archive_tag, internal_dir)
                    dest_path, renamed = _allocate(dest_dir, basename, None, reserved)
                else:
                    source_tag = archive_tag
                    if internal_dir:
                        internal_tag = internal_dir.replace("/", "_").replace("\\", "_")
                        source_tag = f"{archive_tag}__{internal_tag}"
                    dest_path, renamed = _allocate(self.target_dir, basename, source_tag, reserved)
                planned.append((archive, member, dest_path, renamed))

        return planned, unreadable

    def preview(self) -> dict:
        """
        Read-only view of what ``run()`` would extract: the same plan, with
        nothing written and no archive deleted, regardless of ``self.test``. A
        nonexistent ``search_dir`` yields an empty plan rather than raising,
        matching the os.walk-based scan.
        """
        planned, unreadable = self._plan()
        return {
            "planned": [
                {"archive": archive, "member": member, "destination": dest, "renamed": renamed}
                for archive, member, dest, renamed in planned
            ],
            "unreadable": [{"archive": archive, "reason": reason} for archive, reason in unreadable],
            "archives": sorted({archive for archive, _m, _d, _r in planned}),
        }

    def run(self):
        if not Utils.isdir_with_retry(self.search_dir):
            raise Exception(f"Invalid search directory: {self.search_dir}")
        if self.target_dir == self.search_dir:
            raise Exception(
                f"target_dir must differ from search_dir, both are {self.search_dir} "
                "(the target is excluded from the search, so this would find nothing)"
            )
        if _is_under(self.search_dir, self.target_dir):
            raise Exception(
                f"search_dir {self.search_dir} sits inside target_dir {self.target_dir}; "
                "the target is excluded from the search, so this would find nothing"
            )

        planned, unreadable = self._plan()
        for archive, reason in unreadable:
            logger.error(f"{self.name}: could not read {archive}: {reason}")

        if len(planned) == 0:
            logger.warning(
                f"{self.name}: no extractable files found for pattern {self.pattern} in {self.search_dir}"
            )
            return

        by_archive = _group_by_archive(planned)
        archive_count = len(by_archive)

        if self.test:
            logger.info(
                f"|=============== TEST (dry run) {self.name}: nothing extracted or deleted ===============|"
            )
            logger.info(
                f"TEST {self.name}: would extract {len(planned)} file(s) from "
                f"{archive_count} archive(s) into {self.target_dir}"
            )
            for archive, member, dest_path, renamed in planned[:_DRY_RUN_LOG_LIMIT]:
                suffix = " (renamed)" if renamed else ""
                logger.info(f"TEST extract {member} from {archive} -> {dest_path}{suffix}")
            if len(planned) > _DRY_RUN_LOG_LIMIT:
                logger.info(f"TEST ... and {len(planned) - _DRY_RUN_LOG_LIMIT} more")
            if self.delete_sources:
                logger.info(f"TEST {self.name}: would remove {archive_count} source archive(s)")
            return

        logger.info(
            f"{self.name}: extracting {len(planned)} file(s) from {archive_count} archive(s) "
            f"into {self.target_dir}"
        )
        if not self.skip_confirm:
            confirm = input(
                _("Confirm extraction of {0} file(s) from {1} archive(s) into {2} (y/n): ").format(
                    len(planned), archive_count, self.target_dir
                )
            )
            if confirm.lower() != "y":
                logger.info("Operation cancelled by user")
                return

        os.makedirs(self.target_dir, exist_ok=True)
        extracted = 0
        renamed_count = 0
        failed_archives = set()

        for archive, items in by_archive.items():
            try:
                with zipfile.ZipFile(archive, "r") as zip_ref:
                    for _archive, member, dest_path, renamed in items:
                        try:
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            extracted += 1
                            if renamed:
                                renamed_count += 1
                                logger.info(f"extracted {member} -> {dest_path} (renamed)")
                            else:
                                logger.info(f"extracted {member} -> {dest_path}")
                        except Exception as e:
                            failed_archives.add(archive)
                            logger.error(
                                f"{self.name}: failed to extract {member} from {archive}: {e}"
                            )
            except Exception as e:
                failed_archives.add(archive)
                logger.error(f"{self.name}: failed to open {archive}: {e}")

        logger.info(f"{self.name}: extracted {extracted} file(s) into {self.target_dir}")
        if renamed_count > 0:
            logger.info(f"{self.name}: {renamed_count} file(s) renamed to avoid name collisions")

        if self.delete_sources:
            self._delete_source_archives(by_archive, failed_archives)

    def _delete_source_archives(self, by_archive: dict, failed_archives: set):
        """Trash each archive whose every member extracted; keep any that had a failure."""
        for archive in by_archive:
            if archive in failed_archives:
                logger.warning(
                    f"{self.name}: keeping {archive}, not every member extracted successfully"
                )
                continue
            if remove_file(archive):
                logger.info(f"{self.name}: removed source archive {archive}")
            else:
                logger.error(f"{self.name}: failed to remove source archive {archive}")
