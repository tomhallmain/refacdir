"""Checks a built executable runs against itself with ``--smoke-test``.

``build_exe.py`` runs the built app this way with ``REFACDIR_APP_DATA_DIR``
pointing at a scratch directory. Each entry point adds the checks specific to
it; getting far enough to run any of them already proves its imports resolved.
"""

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

    def check_import(self, name: str, module: str) -> None:
        try:
            __import__(module)
            self.check(name, True)
        except ImportError as e:
            self.check(name, False, str(e))

    def check_common(self, expect_oqs: bool = False) -> None:
        """Config, translations, example configs, config discovery, keyring
        backend, and OQS: required with *expect_oqs*, otherwise only reported."""
        import keyring
        import keyring.backends.fail
        from refacdir.batch import BatchArgs
        from refacdir.config import config
        from refacdir.utils.translations import I18N

        self.check("config", os.path.isfile(config.config_path), config.config_path)
        self.check("locale", os.path.isdir(I18N.localedir), I18N.localedir)
        self.check("example configs", os.path.isfile(resource_path("examples", "config_example.yaml")))
        self.check(
            "search functions template",
            os.path.isfile(resource_path("examples", "custom_file_name_search_funcs.py.example")),
        )
        try:
            BatchArgs.discover_configs_from_disk()
            self.check("config discovery", True)
        except Exception as e:
            self.check("config discovery", False, str(e))
        backend = keyring.get_keyring()
        self.check(
            "keyring backend",
            not isinstance(backend, keyring.backends.fail.Keyring),
            f"{type(backend).__module__}.{type(backend).__name__}",
        )

        from refacdir.utils import encryptor

        oqs_available = encryptor.KeyEncapsulation is not None
        if expect_oqs:
            self.check("OQS key encapsulation", oqs_available)
        else:
            logger.info(f"smoke test: OQS key encapsulation {'available' if oqs_available else 'not in this build'}")

    def result(self) -> int:
        """Exit code: 0 if every check passed."""
        if self.failures:
            logger.error(f"smoke test failed: {', '.join(self.failures)}")
            return 1
        logger.info("smoke test passed")
        return 0
