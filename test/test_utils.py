"""
Shared helpers for pytest modules under ``test/``.

**YAML batch configs:** ``BatchJob.run_config_file`` resolves paths with
``os.path.join(BatchJob.BASE_DIR, config)``. Tests must patch ``BatchJob.BASE_DIR``
to a ``tmp_path`` and write config files there — never the repo ``configs/`` tree.

Use :func:`patch_batch_job_base_dir` with :func:`posix_path` for location strings in YAML.

**App cache / crypto / singletons:** root ``test/conftest.py`` sets ``REFACDIR_CONFIGS_DIR`` /
``REFACDIR_CACHE_DIR`` to ``test/fixtures/`` before any ``refacdir`` import, then
``isolated_app_singletons`` repoints each test at ``tmp_path`` (``restore_batch_configs``,
``restore_batch_registries``, ``restore_filename_mapping_registry``).

**UI tests:** ``test/ui/`` — pytest-qt ``qtbot`` (plugin installed globally; only UI tests
use the fixture). Mark modules with ``pytestmark = pytest.mark.ui``.
Do not import ``app_info_cache`` or ``config`` at module level; use lazy imports so
``isolated_app_singletons`` patching applies.
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
