# Non-backup batch action types — test coverage

This document summarizes automated test coverage for `ActionType` values **other than** `BACKUP`. For backup coverage, see [BACKUP_TEST_COVERAGE.md](./BACKUP_TEST_COVERAGE.md).

## Verification (repo scan)

Pytest modules under `test/` that target non-backup actions:

| Action (`ActionType`) | Test directory | Notes |
|----------------------|----------------|--------|
| `RENAMER` | `test/renamer/` | Glob, stat rename, dry-run vs real rename, `BatchRenamer`, YAML + `BatchJob` |
| `DUPLICATE_REMOVER` | `test/duplicate_remover/` | Identical files + `skip_confirm`, `construct_duplicate_remover`, YAML + `BatchJob` |
| `DIRECTORY_OBSERVER` | `test/directory_observer/` | `DirData.observe`, `DirectoryObserver.run` with `extra_dirs`, `construct_directory_observer`, YAML + `BatchJob` |
| `DIRECTORY_FLATTENER` | `test/directory_flattener/` | Nested files + user dry-run (`test=True`), `construct_directory_flattener`, YAML + `BatchJob` |
| `IMAGE_CATEGORIZER` | — | No dedicated tests yet |

Shared helpers: `test/test_utils.py` (e.g. `patch_batch_job_base_dir`, `posix_path`), `test/conftest.py` (`REFACDIR_DISABLE_APP_INFO_CACHE_LOAD` so imports do not touch persisted app cache). Tests use `tmp_path` and never rely on the repo `configs/` tree for YAML integration.

## What is *not* covered (yet)

- **`IMAGE_CATEGORIZER`** — `construct_image_categorizer` / `ImageCategorizer` (likely needs fixtures or mocks).
- **Cross-cutting** — Optional smoke `BatchJob.run_action` for every action type in one module.

## Related code references

- `refacdir/batch.py` — `ActionType`, `run_action`, `construct_*` methods.
- `configs/` / `master_config.yaml` — real configs are not a substitute for automated tests.
