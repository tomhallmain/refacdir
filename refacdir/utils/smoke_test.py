"""Checks a built executable runs against itself with ``--smoke-test``.

``build_exe.py`` runs the built app this way with ``REFACDIR_APP_DATA_DIR``
pointing at a scratch directory. Each entry point adds the checks specific to
it; getting far enough to run any of them already proves its imports resolved.
A check that raises fails by name with its full traceback logged; that
includes ``SystemExit``, which Nuitka's metadata lookup for a package bundled
without its distribution metadata raises.
"""

import contextlib
import io
import os

from refacdir.utils.app_paths import resource_path
from refacdir.utils.logger import setup_logger

logger = setup_logger("smoke_test")


class SmokeTest:
    def __init__(self):
        self.failures = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        logger.info(f"smoke test: {name}: {'ok' if ok else 'FAILED'} {detail}".rstrip())
        if not ok:
            self.failures.append(name)

    @contextlib.contextmanager
    def guarded(self, name: str):
        """Fail check *name*, with the traceback logged, if the block raises."""
        try:
            yield
        except (Exception, SystemExit):
            logger.exception(f"smoke test: {name}: FAILED with an exception")
            self.failures.append(name)

    def check_import(self, name: str, module: str) -> None:
        with self.guarded(name):
            try:
                __import__(module)
            except ImportError as e:
                self.check(name, False, str(e))
                return
            self.check(name, True)

    def check_version(self) -> None:
        """VERSION is bundled and, in a build, build_info.json names the same version."""
        from refacdir.utils.app_paths import IS_BUILD
        from refacdir.utils.version import BUILD_INFO_FILE, VERSION_FILE, app_version, build_info, describe

        logger.info(f"smoke test: {describe()}")
        try:
            version = app_version()
            self.check("version", bool(version), version)
        except OSError as e:
            self.check("version", False, str(e))
            return
        if IS_BUILD:
            try:
                built = build_info().get("version")
            except (OSError, ValueError) as e:
                built = f"unreadable: {e}"
            self.check(
                "build info", built == version,
                f"{BUILD_INFO_FILE} names {built!r}, {VERSION_FILE} holds {version!r}",
            )

    def check_fault_log(self) -> None:
        """The fault log opens; it then stays enabled for the process."""
        from refacdir.utils.crash_log import enable_fault_log

        with self.guarded("fault log"):
            path = enable_fault_log()
            self.check("fault log", os.path.isfile(path), path)

    def check_mcp(self) -> None:
        """The MCP SDK and the HTTP transport the server runs on."""
        with self.guarded("MCP SDK"):
            try:
                # What extensions/mcp_server.py's _serve and _register_tools import.
                from extensions.mcp_server import sdk_context_class
                from mcp.server import MCPServer  # noqa: F401

                sdk_context_class()
                self.check("MCP SDK", True)
            except ImportError as e:
                self.check("MCP SDK", False, str(e))
        self.check_import("uvicorn (MCP HTTP transport)", "uvicorn")

    def check_yaml_round_trip(self) -> None:
        """ruamel.yaml, which Replace Paths (window and MCP) needs, keeps a comment
        through load and dump; a package bundled incompletely fails here."""
        with self.guarded("ruamel.yaml round trip"):
            try:
                from ruamel.yaml import YAML
                from ruamel.yaml.util import load_yaml_guess_indent  # noqa: F401
            except ImportError as e:
                self.check("ruamel.yaml round trip", False, str(e))
                return
            yaml = YAML()
            stream = io.StringIO()
            yaml.dump(yaml.load("key: value  # kept\n"), stream)
            self.check("ruamel.yaml round trip", "# kept" in stream.getvalue())

    def check_common(self, expect_oqs: bool = False) -> None:
        """Version, config, translations, example configs, config discovery,
        the YAML round trip, keyring backend, and OQS: required with
        *expect_oqs*, otherwise only reported."""
        with self.guarded("version"):
            self.check_version()
        with self.guarded("config"):
            from refacdir.config import config

            self.check("config", os.path.isfile(config.config_path), config.config_path)
        with self.guarded("locale"):
            from refacdir.utils.translations import I18N

            self.check("locale", os.path.isdir(I18N.localedir), I18N.localedir)
        self.check("example configs", os.path.isfile(resource_path("examples", "config_example.yaml")))
        self.check(
            "search functions template",
            os.path.isfile(resource_path("examples", "custom_file_name_search_funcs.py.example")),
        )
        with self.guarded("config discovery"):
            from refacdir.batch import BatchArgs

            BatchArgs.discover_configs_from_disk()
            self.check("config discovery", True)
        self.check_yaml_round_trip()
        with self.guarded("keyring backend"):
            import keyring
            import keyring.backends.fail

            backend = keyring.get_keyring()
            self.check(
                "keyring backend",
                not isinstance(backend, keyring.backends.fail.Keyring),
                f"{type(backend).__module__}.{type(backend).__name__}",
            )
        with self.guarded("OQS key encapsulation"):
            from refacdir.utils import encryptor

            oqs_available = encryptor.KeyEncapsulation is not None
            if expect_oqs:
                self.check("OQS key encapsulation", oqs_available)
            else:
                logger.info(
                    f"smoke test: OQS key encapsulation {'available' if oqs_available else 'not in this build'}"
                )

    def result(self) -> int:
        """Exit code: 0 if every check passed."""
        if self.failures:
            logger.error(f"smoke test failed: {', '.join(self.failures)}")
            return 1
        logger.info("smoke test passed")
        return 0
