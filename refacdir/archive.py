import os
import patoolib
from subprocess import Popen, PIPE
import sys


class Archive:
    PATH_EQUALS = 'Path = '

    def __init__(self, path):
        self.path = path
        _, self.type = os.path.splitext(path)

    def size(self):
        return os.stat(self.path).st_size

    def list_files(self):
        proc = Popen(["C:\\Program Files\\7-Zip\\7z.exe", "l", "-ba", "-slt", self.path], stdout=PIPE)
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
            print(archive.path)
            print(f"Number of files: {len(files)}")
            print(f"Number of base files: {len(files)}")
            print(f"Size: {size}")
            count = 0
            for f in base_files:
                print(f)
                count += 1
                if count > 9:
                    print("etc...")
                    break
            print("")

    def search_archive_paths(self, search_term, cased=False):
        archive_matches = {}
        for archive in self.archives:
            file_matches = archive.search(search_term, cased)
            if len(file_matches) > 0:
                archive_matches[archive] = file_matches
        for match_archive in archive_matches:
            print("Found archive with matches: " + match_archive.path)
            for f in archive_matches[match_archive]:
                print(f)
            print("")


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
