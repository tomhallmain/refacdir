"""
Shared helpers for pytest modules under ``test/``.

**Configs isolation:** ``BatchJob.run_config_file`` resolves YAML paths with
``os.path.join(BatchJob.BASE_DIR, config)``. Tests must patch ``BatchJob.BASE_DIR``
to a ``tmp_path`` (or other temp tree) and write config files there. Never load
from the repo ``configs/`` directory or the user's live config set during tests.

Use :func:`patch_batch_job_base_dir` together with :func:`posix_path` for
location strings embedded in YAML.

**App cache / crypto:** ``test/conftest.py`` sets
``REFACDIR_DISABLE_APP_INFO_CACHE_LOAD`` so ``AppInfoCache`` skips both
``load`` and ``store``, and ``refacdir.utils.encryptor`` skips importing
``oqs`` (same env var). That keeps tests off user-local cache and avoids
pulling liboqs during unrelated imports.
"""


def posix_path(path: str) -> str:
    """Normalize filesystem paths for YAML strings (forward slashes)."""
    return path.replace("\\", "/")


def patch_batch_job_base_dir(monkeypatch, base_dir: str, batch_job_cls):
    """
    Point ``BatchJob.BASE_DIR`` (or another batch class) at a temp directory so
    ``run_config_file("my.yaml")`` reads ``base_dir/my.yaml``, not ``configs/``.
    """
    monkeypatch.setattr(batch_job_cls, "BASE_DIR", base_dir)
