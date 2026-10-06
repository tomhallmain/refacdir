"""
Shared helpers for pytest modules under ``test/``.

**YAML batch configs:** ``BatchJob.run_config_file`` resolves paths with
``os.path.join(BatchJob.BASE_DIR, config)``. The autouse ``isolated_app_singletons``
already points ``BASE_DIR`` at ``tmp_path`` (parent of the per-test configs dir); a
test that writes configs elsewhere patches it to that directory instead.

Use :func:`patch_batch_job_base_dir` with :func:`posix_path` for location strings in YAML.

**App cache / crypto / singletons:** root ``test/conftest.py`` sets ``REFACDIR_CONFIGS_DIR`` /
``REFACDIR_CACHE_DIR`` to ``test/fixtures/`` and ``REFACDIR_APP_DATA_DIR`` to a
session temp dir before any ``refacdir`` import, then
``isolated_app_singletons`` repoints each test at ``tmp_path`` (``restore_batch_configs``,
``restore_batch_registries``, ``restore_filename_mapping_registry``).

**Layout:** runnable tests live in subdirectories (``test/unit/``, ``test/ui/``,
``test/backup/``, etc.). Shared non-test modules such as this file and ``test/fixtures/``
stay at the ``test/`` root.
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
