"""
List and search the contents of archives under a directory without extracting
them, through 7-Zip. Run as ``python -m refacdir.archive <dir> [search_term]``.

It covers what ARCHIVE_EXTRACTOR (``refacdir/archive_extractor.py``) does not,
and could later be folded into it or into an action of its own:

- Any format 7-Zip reads (7z, RAR, TAR and others; recognized via
  ``patoolib.is_archive``), where the extractor handles ZIP only.
- Searching member paths across many archives for a term, case-insensitive by
  default, reporting which archives contain a match.
- A per-archive summary: member count, top-level entries and size.

No action type uses it. It needs ``patoolib``, which no requirements file
lists, and 7-Zip installed at ``C:\\Program Files\\7-Zip\\7z.exe``.
"""
import os
import patoolib
import subprocess
from subprocess import DEVNULL, Popen, PIPE
import sys
from refacdir.utils.logger import setup_logger

# Set up logger for archive operations
logger = setup_logger('archive')

# Keeps a console child of the windowed Windows build from opening a console window.
_NO_CONSOLE_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class Archive:
    PATH_EQUALS = 'Path = '

    def __init__(self, path):
        self.path = path
        _, self.type = os.path.splitext(path)

    def size(self):
        return os.stat(self.path).st_size

    def list_files(self):
        # stdin is explicit: a windowed Windows build can have no valid standard
        # handles, and inheriting one fails with WinError 6 before 7-Zip starts.
        proc = Popen(["C:\\Program Files\\7-Zip\\7z.exe", "l", "-ba", "-slt", self.path],
                     stdin=DEVNULL, stdout=PIPE, creationflags=_NO_CONSOLE_WINDOW)
        files = [l[len(Archive.PATH_EQUALS):] for l in proc.stdout.read().decode().splitlines() if l.startswith(Archive.PATH_EQUALS)]
        return files

    def search(self, search_term, cased=False):
        matches = []
        if not cased:
            search_term = search_term.lower()
        for f in self.list_files():
            if cased:
                if search_term in f:
                    matches.append(f)
            elif search_term in f.lower():
                matches.append(f)
        return matches

    def contains(self, search_term, cased=False):
        if not cased:
            search_term = search_term.lower()
        for f in self.list_files():
            if cased:
                if search_term in f:
                    return True
            elif search_term in f.lower():
                return True
        return False


class ArchiveDirectory:
    def __init__(self, root="."):
        self.root = root
        if not os.path.isdir(self.root):
            raise Exception("ArchiveDirectory root must be a directory.")
        self.archives = self.gather_archives()

    def gather_archives(self):
        archives = []
        for root, dirs, files in os.walk(self.root):
            for f in files:
                if patoolib.is_archive(f):
                    archives.append(Archive(os.path.join(root, f)))
        return archives

    def list_archive_contents(self):
        for archive in self.archives:
            files = archive.list_files()
            size = archive.size()
            base_files = []
            for f in files:
                if "/" not in f and "\\" not in f:
                    base_files.append(f)
            logger.info(f"Archive: {archive.path}")
            logger.info(f"Number of files: {len(files)}")
            logger.info(f"Number of base files: {len(files)}")
            logger.info(f"Size: {size}")
            count = 0
            for f in base_files:
                logger.info(f)
                count += 1
                if count > 9:
                    logger.info("etc...")
                    break
            logger.info("")

    def search_archive_paths(self, search_term, cased=False):
        archive_matches = {}
        for archive in self.archives:
            file_matches = archive.search(search_term, cased)
            if len(file_matches) > 0:
                archive_matches[archive] = file_matches
        for match_archive in archive_matches:
            logger.info(f"Found archive with matches: {match_archive.path}")
            for f in archive_matches[match_archive]:
                logger.info(f)
            logger.info("")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise Exception("Missing archive directory path argument: python archive.py path/to/archive/dir [search_term]")
    archive_directory = ArchiveDirectory(sys.argv[1])
    search_term = None
    if len(sys.argv) > 2:
        search_term = sys.argv[2]

    if search_term is not None:
        archive_directory.search_archive_paths(search_term)
    else:
        archive_directory.list_archive_contents()
