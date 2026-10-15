"""RefacDir's version, and what a compiled build records about itself.

``build_exe.py`` executes this file on its own, before the build venv exists,
so it imports nothing at load time (functions import what they need).
"""

#: One line holding the version: up to four dot-separated numbers, which is
#: all Windows file version information allows. At the repo root in a
#: checkout; build_exe.py bundles it at the resource root.
VERSION_FILE = "VERSION"

#: Written by build_exe.py and bundled at the resource root.
BUILD_INFO_FILE = "build_info.json"


def app_version() -> str:
    """RefacDir's version, read from VERSION_FILE."""
    from refacdir.utils.app_paths import resource_path

    with open(resource_path(VERSION_FILE), "r", encoding="utf-8") as f:
        return f.read().strip()


def build_info() -> dict:
    """The build's recorded details (build id, interpreter, key package
    versions, source commit), or an empty dict in a source checkout."""
    import json
    import os

    from refacdir.utils.app_paths import resource_path

    path = resource_path(BUILD_INFO_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def describe() -> str:
    """One line naming the version and, in a build, the build id, the source
    commit and the versions it was built with. Never raises for a missing or
    unreadable file, since it runs at startup."""
    try:
        version = app_version()
    except OSError as e:
        version = f"(version unreadable: {e})"
    try:
        info = build_info()
    except (OSError, ValueError) as e:
        return f"RefacDir {version} (build info unreadable: {e})"
    if not info:
        return f"RefacDir {version} (source checkout)"
    source = info.get("source", {})
    commit = source.get("commit")
    commit = commit[:10] if commit else "unknown commit"
    if source.get("changes"):
        commit += " with uncommitted changes"
    packages = ", ".join(f"{name} {v}" for name, v in sorted(info.get("packages", {}).items()))
    oqs = "with OQS" if info.get("with_oqs") else "without OQS"
    return (f"RefacDir {version}, build {info.get('build_id', '?')} from {commit}, {oqs} "
            f"(Python {info.get('python', '?')}, {packages})")


def read_git_commit(checkout: str) -> str:
    """The commit a git checkout has checked out, read from its .git
    directory without running git, or ""."""
    import os

    git_dir = os.path.join(checkout, ".git")
    try:
        with open(os.path.join(git_dir, "HEAD"), "r", encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[len("ref: "):]
        ref_path = os.path.join(git_dir, *ref.split("/"))
        if os.path.isfile(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(git_dir, "packed-refs"), "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        pass
    return ""


def run_git(repo: str, *args: str):
    """git's stdout for a command in *repo*, or None when git is not installed
    or the command fails."""
    import subprocess
    import sys

    # A windowed exe would otherwise flash a console window for git.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        # stdin is explicit: a windowed Windows exe can have no valid standard
        # handles, and inheriting one fails with WinError 6 before git starts.
        result = subprocess.run(
            ["git", "-C", repo, *args], stdin=subprocess.DEVNULL, capture_output=True,
            encoding="utf-8", errors="replace", timeout=15, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def source_state(repo: str) -> dict:
    """The checkout's commit, the tree (files) of that commit ("" when git
    cannot tell), and a fingerprint of its uncommitted changes to tracked
    files ("" when there are none, None when git cannot tell)."""
    import hashlib

    commit = (run_git(repo, "rev-parse", "HEAD") or "").strip() or read_git_commit(repo)
    tree = (run_git(repo, "rev-parse", "HEAD^{tree}") or "").strip()
    diff = run_git(repo, "diff", "HEAD", "--binary")
    if diff is None:
        changes = None
    else:
        changes = hashlib.sha1(diff.encode("utf-8")).hexdigest() if diff else ""
    return {"commit": commit, "tree": tree, "changes": changes}
