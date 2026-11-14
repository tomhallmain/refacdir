"""
Build RefacDir with Nuitka: ``python build_exe.py``.

Nuitka compiles the code to C, then to a single native executable that embeds
the Python runtime. Needs a C compiler: Xcode Command Line Tools on macOS; on
Windows, Visual Studio Build Tools, or Nuitka downloads MinGW itself. Nuitka
does not cross-compile, so run this on each target OS.

Builds inside a dedicated ``.venv-build`` at the repo root, populated from
requirements-build.txt, so packages from the active conda env or venv aren't
bundled. The venv is based on the interpreter running this script, and the exe
embeds that interpreter's runtime. ``--current-env`` builds with the running
interpreter instead; it must already have requirements-build.txt installed.
Either way, the build stops before compiling if the build interpreter lacks
anything requirements.txt lists, since the executable would otherwise fail
only once that import is reached.

Builds dist/RefacDir (``.exe`` on Windows) from app_qt.py. ``--with-headless``
also builds RefacDirHeadless from app_headless.py, the MCP server with no
window and no Qt; it is a second full Nuitka compile. Both serve MCP. At its
first start each unpacks its runtime to ``unpacked/<prefix>-<build id>`` in
the app data dir; later starts of the same build reuse that folder. Each is
smoke-tested with ``--smoke-test``. Other args are forwarded to Nuitka, e.g.
``--show-scons`` or ``--jobs=4``.

The GUI build ships pytest, pytest-qt and the test/ tree: the app's Run tests
window runs the suite so users can see the backup cases it covers.

Before compressing the onefile payload, the last step of each compile, the
build waits for enough free memory (the memory-wait plugin, from app-release
when installed), since a failed allocation there loses the whole compile.
``--min-free-memory=<GiB>`` sets the amount instead of the estimate; 0 turns
the wait off. Each step is timed, and the log goes to
``build/logs/build_exe-<build id>.log`` as well (Nuitka's own output only to
the console).

``--with-oqs`` adds quantum-safe (OQS) key encapsulation: it installs
liboqs-python, finds the liboqs shared library the build interpreter loads, and
bundles it. liboqs-python builds liboqs on first import if none is installed,
which needs git, CMake and a C compiler; or point OQS_INSTALL_PATH at an
existing install. Without the option the build has no OQS, and a cache
encrypted with OQS keys cannot be read by it. Applies to both executables.

The executables' version information comes from the VERSION file at the repo
root, which is also bundled, with the build id (build time) in its
description. Each build writes ``build/nuitka/build_info.json`` (version, build
id, whether it has OQS, Python and key package versions, and this checkout's
path, commit, the commit's tree and a fingerprint of its uncommitted changes),
bundled so the app logs it at startup, and ``build/nuitka/build-requirements.lock.txt``,
the build venv's ``pip freeze``. ``--lock=<file>`` installs the build venv from
such a file instead of requirements-build.txt, to repeat a known good build;
packages already in the venv but absent from the file stay installed, so
delete .venv-build first for an exact copy. app-release publishes the
executables in dist/ as a GitHub release.
"""
import contextlib
import json
import logging
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import venv

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(REPO_ROOT, ".venv-build")
BUILD_DIR = os.path.join(REPO_ROOT, "build", "nuitka")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
# refacdir.utils.app_paths.app_data_dir() spelled for Nuitka. On Windows,
# Nuitka's {CACHE_DIR} is %LOCALAPPDATA%, the base app_data_dir() uses there.
APP_DATA_SPEC = "{CACHE_DIR}/refacdir" if sys.platform == "win32" else "{HOME}/.local/share/refacdir"
VERSION_FILE = "VERSION"
VERSION_MODULE = os.path.join("refacdir", "utils", "version.py")
BUILD_INFO_PATH = os.path.join(BUILD_DIR, "build_info.json")
LOCK_PATH = os.path.join(BUILD_DIR, "build-requirements.lock.txt")
LOG_DIR = os.path.join(REPO_ROOT, "build", "logs")
# Set by app-release, which ships the memory-wait plugin, when it runs this script.
MEMORY_WAIT_PLUGIN_ENV = "NUITKA_MEMORY_WAIT_PLUGIN"
# Read by the memory-wait plugin.
MIN_FREE_MEMORY_ENV = "BUILD_MIN_FREE_MEMORY_GB"
# Versions the build output and build_info.json record.
RECORDED_DISTRIBUTIONS = (
    "Nuitka", "PySide6", "keyring", "cryptography", "pytest", "pytest-qt", "mcp", "liboqs-python",
    "ruamel.yaml",
)
# What the built app imports at runtime; every entry must be installed in the build interpreter.
RUNTIME_REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")
ICON_SVG = os.path.join("ui", "assets", "refacdir_icon.svg")
ICON_ICO = os.path.join(BUILD_DIR, "refacdir_icon.ico")

# Shipped files, at the same relative paths refacdir.utils.app_paths.resource_path()
# resolves them under.
DATA_DIRS = ("locale", "examples")
DATA_FILES = (VERSION_FILE,)
GUI_DATA_FILES = (ICON_SVG, "pytest.ini")
TEST_DIR = "test"
# math is also promised, but built into the interpreter.
USER_FILE_STDLIB_MODULES = (
    "re", "os", "datetime", "fnmatch", "string", "random",
    "collections", "hashlib", "pathlib",
)
# Same source as requirements-optional.txt; not on PyPI.
LIBOQS_PYTHON = "git+https://github.com/open-quantum-safe/liboqs-python.git"
# Prints the path of the liboqs shared library liboqs-python loaded.
_LIBOQS_PROBE = (
    "import oqs.oqs as m\n"
    "lib = m.native() if hasattr(m, 'native') else m._liboqs\n"
    "print(lib._name)\n"
)
# Prints {"python": ..., "packages": {name: version}} for the names in argv.
_VERSIONS_PROBE = (
    "import json, sys\n"
    "from importlib.metadata import PackageNotFoundError, version\n"
    "def get(name):\n"
    "    try:\n"
    "        return version(name)\n"
    "    except PackageNotFoundError:\n"
    "        return None\n"
    "print(json.dumps({'python': sys.version.split()[0],\n"
    "                  'packages': {n: get(n) for n in sys.argv[1:]}}))\n"
)
# Prints a JSON list of the requirement lines in argv that are not installed
# (or installed at a version they exclude), skipping lines whose environment
# marker does not apply. pip vendors packaging, so it is always importable there.
_REQUIREMENTS_PROBE = (
    "import json, sys\n"
    "from importlib.metadata import PackageNotFoundError, version\n"
    "try:\n"
    "    from packaging.requirements import Requirement\n"
    "except ImportError:\n"
    "    from pip._vendor.packaging.requirements import Requirement\n"
    "missing = []\n"
    "for line in sys.argv[1:]:\n"
    "    req = Requirement(line)\n"
    "    if req.marker is not None and not req.marker.evaluate():\n"
    "        continue\n"
    "    try:\n"
    "        installed = version(req.name)\n"
    "    except PackageNotFoundError:\n"
    "        missing.append(line)\n"
    "        continue\n"
    "    if req.specifier and not req.specifier.contains(installed, prereleases=True):\n"
    "        missing.append(line + ' (installed: ' + installed + ')')\n"
    "print(json.dumps(missing))\n"
)
# Generated by test runs, not part of the suite.
TEST_DIR_EXCLUDES = (
    "__pycache__",
    ".pytest_cache",
    os.path.join("backup", "source"),
    os.path.join("backup", "test_files"),
)

logger = logging.getLogger("build_exe")


class _LevelPrefix(logging.Filter):
    def filter(self, record):
        record.level_prefix = "" if record.levelno == logging.INFO else f"{record.levelname}: "
        return True


def _setup_logging(build_id: str) -> str:
    """Log to the console and to a file for this build; returns the file's path."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"build_exe-{build_id}.log")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(asctime)s] %(level_prefix)s%(message)s", "%H:%M:%S"))
    log_file = logging.FileHandler(path, encoding="utf-8")
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for handler in (console, log_file):
        handler.addFilter(_LevelPrefix())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@contextlib.contextmanager
def _timed(step: str):
    """Log how long *step* took, or after how long it failed."""
    started = time.monotonic()
    logger.info(f"{step}...")
    try:
        yield
    except BaseException:
        logger.error(f"{step} failed after {_duration(time.monotonic() - started)}")
        raise
    logger.info(f"{step} done in {_duration(time.monotonic() - started)}")


def _venv_python(venv_dir: str) -> str:
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _exe_name(base: str) -> str:
    return f"{base}.exe" if sys.platform == "win32" else base


def _ensure_build_venv(extra_packages=(), requirements=None) -> str:
    """The build venv's interpreter, after installing *requirements*
    (requirements-build.txt by default, or a lock file) and *extra_packages*."""
    python = _venv_python(VENV_DIR)
    if not os.path.exists(python):
        logger.info(f"Creating build venv at {VENV_DIR}")
        venv.create(VENV_DIR, with_pip=True)
    requirements = requirements or os.path.join(REPO_ROOT, "requirements-build.txt")
    subprocess.run(
        [python, "-m", "pip", "install", "-q", "-r", requirements, *extra_packages],
        check=True,
    )
    return python


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_has(lock_path: str, distribution: str) -> bool:
    """Whether the lock file pins *distribution* (``name==...`` or ``name @ url``)."""
    with open(lock_path, "r", encoding="utf-8") as f:
        for line in f:
            name = re.split(r"[=@<>~!\s;\[]", line.strip(), maxsplit=1)[0]
            if name and _canonical_name(name) == _canonical_name(distribution):
                return True
    return False


def _runtime_requirements(path: str = RUNTIME_REQUIREMENTS) -> list:
    """The requirement lines of *path*: no comments, pip options or URL requirements."""
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split(" #", 1)[0].strip()
            if not line or line.startswith(("#", "-")) or "://" in line:
                continue
            lines.append(line)
    return lines


def _missing_requirements(python: str, requirements: list) -> list:
    probe = subprocess.run(
        [python, "-c", _REQUIREMENTS_PROBE, *requirements], capture_output=True, text=True, check=True,
    )
    return json.loads(probe.stdout.strip().splitlines()[-1])


def _check_runtime_requirements(python: str, lock=None, current_env: bool = False) -> None:
    """Stop the build when the build interpreter lacks something the app imports.

    pip installing requirements-build.txt covers this, but a --lock file can
    predate a requirement, and --current-env installs nothing; Nuitka would
    then build an executable that fails only when the missing import is reached.
    """
    missing = _missing_requirements(python, _runtime_requirements())
    if not missing:
        return
    if lock:
        hint = (f"The lock file {lock} predates these requirements. Build once without --lock "
                "to record a new one, or add them to the lock file.")
    elif current_env:
        hint = "Install them with: pip install -r requirements-build.txt"
    else:
        hint = "pip did not install them into the build venv; its output is above."
    sys.exit(
        "The build interpreter is missing runtime requirements from requirements.txt:\n  "
        + "\n  ".join(missing) + "\n" + hint
    )


def _write_lock_file(python: str) -> None:
    freeze = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(freeze.stdout)
    logger.info(f"Build environment recorded in {LOCK_PATH}")


def _version_module() -> dict:
    """refacdir/utils/version.py's globals, loaded without importing the app."""
    return runpy.run_path(os.path.join(REPO_ROOT, VERSION_MODULE))


def _app_version() -> str:
    with open(os.path.join(REPO_ROOT, VERSION_FILE), "r", encoding="utf-8") as f:
        version = f.read().strip()
    if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
        sys.exit(f"{VERSION_FILE} holds {version!r}; it must be up to four dot-separated numbers.")
    return version


def _environment_versions(python: str) -> dict:
    probe = subprocess.run(
        [python, "-c", _VERSIONS_PROBE, *RECORDED_DISTRIBUTIONS], capture_output=True, text=True, check=True,
    )
    return json.loads(probe.stdout.strip().splitlines()[-1])


def _write_build_info(version: str, build_id: str, environment: dict, with_oqs: bool) -> None:
    """build_info.json, bundled at the resource root (refacdir/utils/version.py reads it)."""
    info = {
        "version": version,
        "build_id": build_id,
        # app-release rebuilds with --with-oqs when this is true.
        "with_oqs": with_oqs,
        "python": environment["python"],
        "packages": {name: v for name, v in environment["packages"].items() if v},
        # The startup drift check finds the checkout by this path, which anyone
        # with the executable can read; app-release warns of it.
        "source": {"repo": REPO_ROOT, **_version_module()["source_state"](REPO_ROOT)},
    }
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    logger.info("Building " + ", ".join(
        [f"RefacDir {version}", f"build {build_id}",
         f"from {info['source']['commit'][:10] or 'unknown commit'}"
         + (" with uncommitted changes" if info["source"]["changes"] else ""),
         f"Python {info['python']}"]
        + [f"{name} {v}" for name, v in sorted(info["packages"].items())]
    ))


def _test_tree_files() -> list:
    """Every file under test/ except generated ones, as repo-relative paths.

    Listed one by one because --include-data-dir skips code files, and the
    suite is mostly .py files.
    """
    files = []
    root = os.path.join(REPO_ROOT, TEST_DIR)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [
            d for d in dirnames
            if os.path.normpath(os.path.join(rel_dir, d)) not in TEST_DIR_EXCLUDES
            and d not in TEST_DIR_EXCLUDES
        ]
        for name in filenames:
            files.append(os.path.relpath(os.path.join(dirpath, name), REPO_ROOT))
    return sorted(files)


def _write_windows_icon(python: str) -> None:
    """Render the SVG app icon to the .ico Nuitka needs, with the build venv's Qt."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    script = (
        "import sys\n"
        "from PySide6.QtCore import Qt\n"
        "from PySide6.QtGui import QGuiApplication, QImage, QPainter\n"
        "from PySide6.QtSvg import QSvgRenderer\n"
        "app = QGuiApplication(sys.argv[:1])\n"
        "image = QImage(256, 256, QImage.Format_ARGB32)\n"
        "image.fill(Qt.transparent)\n"
        "painter = QPainter(image)\n"
        "QSvgRenderer(sys.argv[1]).render(painter)\n"
        "painter.end()\n"
        "sys.exit(0 if image.save(sys.argv[2], 'ICO') else 1)\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([python, "-c", script, os.path.join(REPO_ROOT, ICON_SVG), ICON_ICO], env=env, check=True)


def _memory_wait_plugin():
    """The memory-wait plugin's path: from app-release's variable, else from an
    installed app-release, else None (the build does not wait)."""
    path = os.environ.get(MEMORY_WAIT_PLUGIN_ENV)
    tool = None if path else shutil.which("app-release")
    if tool:
        try:
            result = subprocess.run([tool, "--memory-wait-plugin"], capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"Cannot ask {tool} for the memory-wait plugin: {e}")
        else:
            if result.returncode == 0:
                path = result.stdout.strip()
    if path and os.path.isfile(path):
        logger.info(f"Memory-wait plugin: {path}")
        return path
    logger.warning("No memory-wait plugin: the onefile step will not wait for free memory. "
                   "Install app-release, or build through it.")
    return None


def _common_args(exe_name: str, unpack_prefix: str, version: str, build_id: str,
                 memory_wait_plugin=None) -> list:
    args = [
        "--onefile",
        # The exe unpacks its runtime to this folder. A fixed path (no
        # {PID}/{TIME}) makes Nuitka keep it between runs, so only the first
        # run pays the unpacking cost; the build id gives each build its own
        # folder, so a rebuilt exe never reuses a previous build's files.
        # Nothing the app writes goes under unpacked/.
        f"--onefile-tempdir-spec={APP_DATA_SPEC}/unpacked/{unpack_prefix}-{build_id}",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={exe_name}",
        # Lets Nuitka fetch build helpers (e.g. MinGW on Windows) without prompting.
        "--assume-yes-for-downloads",
        # Version information; Windows shows it in the executable's properties
        # and crash reports. The file version takes numbers only, so the build
        # id goes in the description.
        "--product-name=RefacDir",
        f"--product-version={version}",
        f"--file-version={version}",
        f"--file-description=RefacDir file management, build {build_id}",
        f"--include-data-files={BUILD_INFO_PATH}=build_info.json",
        # keyring finds its backends, including the OS one, through package
        # metadata entry points; without it every encrypted save fails over to
        # plaintext JSON.
        "--include-distribution-metadata=keyring",
        # The MCP SDK reads its own version from package metadata, and uvicorn
        # loads its protocol and event-loop modules by name.
        "--include-distribution-metadata=mcp",
        "--include-package=uvicorn",
        *([f"--user-plugin={memory_wait_plugin}"] if memory_wait_plugin else []),
    ]
    # The user's search functions file is loaded at runtime and can only import
    # what the build contains; its template promises these.
    args += [f"--include-module={m}" for m in USER_FILE_STDLIB_MODULES]
    args += [f"--include-data-dir={d}={d}" for d in DATA_DIRS]
    args += [f"--include-data-files={f}={f}" for f in DATA_FILES]
    if sys.platform == "win32":
        args.append(f"--windows-icon-from-ico={ICON_ICO}")
    return args


def _gui_args() -> list:
    args = [
        "--enable-plugin=pyside6",
        # The window icon is an SVG, which needs Qt's SVG image format and icon engine.
        "--include-qt-plugins=sensible,imageformats,iconengines",
        # pytest finds the pytest-qt plugin through package metadata, loads its
        # built-in plugins by module name, and pytest-qt imports QtTest by name.
        "--include-distribution-metadata=pytest",
        "--include-distribution-metadata=pytest-qt",
        "--include-package=_pytest",
        "--include-package=pytest",
        "--include-package=pytestqt",
        "--include-module=PySide6.QtTest",
        # Test modules import it; the app itself never does.
        "--include-module=app_headless",
    ]
    args += [f"--include-data-files={f}={f}" for f in GUI_DATA_FILES]
    args += [f"--include-data-files={f}={f}" for f in _test_tree_files()]
    if sys.platform == "win32":
        # No console window when started from Explorer; when started from a
        # terminal, output (e.g. the smoke test's) goes to that terminal.
        args.append("--windows-console-mode=attach")
    return args


def _headless_args() -> list:
    return [
        # Only window-bound code (refacdir/lib/position_data.py) imports Qt,
        # inside functions a headless process never calls.
        "--nofollow-import-to=PySide6",
    ]


def _oqs_args(python: str, with_oqs: bool) -> list:
    if not with_oqs:
        # Keep liboqs-python out even if the build environment has it: without
        # its shared library it would try to build liboqs at the app's startup.
        return ["--nofollow-import-to=oqs"]
    probe = subprocess.run([python, "-c", _LIBOQS_PROBE], capture_output=True, text=True)
    library = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    if probe.returncode != 0 or not os.path.isabs(library) or not os.path.isfile(library):
        sys.exit(
            "--with-oqs: could not locate the liboqs shared library through liboqs-python.\n"
            f"{probe.stdout}{probe.stderr}\n"
            "Install liboqs (or let liboqs-python build it: needs git, CMake and a C "
            "compiler) or set OQS_INSTALL_PATH to an existing install, then rebuild."
        )
    # The layout liboqs-python searches under OQS_INSTALL_PATH, which
    # refacdir/utils/encryptor.py points at this folder in the build.
    lib_dir = "bin" if sys.platform == "win32" else "lib"
    logger.info(f"Bundling liboqs: {library}")
    return [
        "--include-package=oqs",
        "--include-distribution-metadata=liboqs-python",
        f"--include-data-files={library}=liboqs/{lib_dir}/{os.path.basename(library)}",
    ]


def _nuitka_env(min_free_memory=None) -> dict:
    env = dict(os.environ)
    if min_free_memory is not None:
        env[MIN_FREE_MEMORY_ENV] = min_free_memory
    return env


def _min_free_memory(value):
    """``--min-free-memory``'s value, checked, or None when not given."""
    if value is None:
        return None
    try:
        if float(value) >= 0:
            return value
    except ValueError:
        pass
    sys.exit(f"--min-free-memory={value}: give a number of GiB, or 0 to not wait for memory.")


def _copy_to_dist(exe_name: str) -> str:
    exe_path = os.path.join(DIST_DIR, exe_name)
    if os.path.isdir(exe_path):
        # Left by a folder build; on macOS/Linux it has the executable's name.
        logger.info(f"Removing the folder build at {exe_path}")
        shutil.rmtree(exe_path)
    os.makedirs(DIST_DIR, exist_ok=True)
    shutil.copy2(os.path.join(BUILD_DIR, exe_name), exe_path)
    return exe_path


def _pop_option(args: list, name: str):
    """Remove ``name=value`` from *args* and return the value, or None."""
    for arg in list(args):
        if arg.startswith(name + "="):
            args.remove(arg)
            return arg.split("=", 1)[1]
    return None


def _smoke_test_env(scratch: str) -> dict:
    """The environment for a smoke test with all app data in *scratch*. Each
    directory override is set, not inherited, so a value exported in the
    developer's shell cannot point the test at real data."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["REFACDIR_APP_DATA_DIR"] = scratch
    env["REFACDIR_CONFIGS_DIR"] = os.path.join(scratch, "configs")
    env["REFACDIR_CACHE_DIR"] = os.path.join(scratch, "cache")
    # The smoke test checks the real cache code path.
    env.pop("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", None)
    return env


def _smoke_test(exe_path: str, with_oqs: bool) -> None:
    # Run from outside the repo so a passing test can't depend on the checkout,
    # with all app data in a scratch directory so the user's is untouched. The
    # exe still unpacks to the real unpacked/ folder, which a later start of
    # this build reuses.
    command = [exe_path, "--smoke-test", *(["--expect-oqs"] if with_oqs else [])]
    with tempfile.TemporaryDirectory(prefix="refacdir-smoke-") as scratch:
        env = _smoke_test_env(scratch)
        for name in ("REFACDIR_CONFIGS_DIR", "REFACDIR_CACHE_DIR"):
            os.makedirs(env[name], exist_ok=True)
        result = subprocess.run(command, cwd=os.path.expanduser("~"), env=env)
    if result.returncode != 0:
        sys.exit(f"Smoke test failed: `{' '.join(command)}` exited {result.returncode}.")


# exe base name, entry script, unpack folder prefix, target-specific args
TARGETS = (
    ("RefacDir", "app_qt.py", "refacdir", _gui_args),
    ("RefacDirHeadless", "app_headless.py", "refacdir-headless", _headless_args),
)
HEADLESS_TARGET = "RefacDirHeadless"


def _targets(with_headless: bool) -> tuple:
    return tuple(t for t in TARGETS if with_headless or t[0] != HEADLESS_TARGET)


def main() -> None:
    args = sys.argv[1:]
    with_oqs = "--with-oqs" in args
    if with_oqs:
        args.remove("--with-oqs")
    with_headless = "--with-headless" in args
    if with_headless:
        args.remove("--with-headless")
    lock = _pop_option(args, "--lock")
    min_free_memory = _min_free_memory(_pop_option(args, "--min-free-memory"))
    version = _app_version()
    build_id = time.strftime("%Y%m%d-%H%M%S")
    logger.info(f"Log: {_setup_logging(build_id)}")

    current_env = "--current-env" in args
    if current_env:
        args.remove("--current-env")
        if lock:
            sys.exit("--lock installs into the build venv; it cannot be combined with --current-env.")
        python = sys.executable
    else:
        if lock:
            lock = os.path.abspath(lock)
            if not os.path.isfile(lock):
                sys.exit(f"--lock: {lock} not found.")
        # A lock file from an OQS build already pins liboqs-python.
        needs_liboqs = with_oqs and not (lock and _lock_has(lock, "liboqs-python"))
        with _timed("Installing the build venv"):
            python = _ensure_build_venv((LIBOQS_PYTHON,) if needs_liboqs else (), requirements=lock)

    _check_runtime_requirements(python, lock=lock, current_env=current_env)
    _write_lock_file(python)
    _write_build_info(version, build_id, _environment_versions(python), with_oqs)
    if sys.platform == "win32":
        _write_windows_icon(python)
    oqs_args = _oqs_args(python, with_oqs)
    memory_wait_plugin = _memory_wait_plugin()

    for base_name, entry, unpack_prefix, target_args in _targets(with_headless):
        exe_name = _exe_name(base_name)
        nuitka_args = [
            *_common_args(exe_name, unpack_prefix, version, build_id, memory_wait_plugin),
            *target_args(), *oqs_args,
            *args, os.path.join(REPO_ROOT, entry),
        ]
        with _timed(f"Compiling {base_name} with Nuitka"):
            result = subprocess.run([python, "-m", "nuitka", *nuitka_args], cwd=REPO_ROOT,
                                    env=_nuitka_env(min_free_memory))
            if result.returncode != 0:
                sys.exit(f"Nuitka exited {result.returncode} compiling {base_name}; its output is above.")
        exe_path = _copy_to_dist(exe_name)
        with _timed(f"Smoke-testing {exe_name}"):
            _smoke_test(exe_path, with_oqs)
        logger.info(f"Built {exe_path}")


if __name__ == "__main__":
    started = time.monotonic()
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                logger.error(e.code)
            logger.error(f"Build failed after {_duration(time.monotonic() - started)}")
            sys.exit(1)
        raise
    except KeyboardInterrupt:
        logger.error(f"Build stopped after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    except BaseException:
        logger.exception(f"Build failed after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    logger.info(f"Build finished in {_duration(time.monotonic() - started)}")
