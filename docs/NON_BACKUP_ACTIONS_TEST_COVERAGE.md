# Non-backup batch action types — test coverage

This document summarizes automated test coverage for `ActionType` values **other than** `BACKUP`. For backup coverage, see [BACKUP_TEST_COVERAGE.md](./BACKUP_TEST_COVERAGE.md).

## Verification (repo scan)

A search of the repository for `pytest` test modules shows **only** `test/backup/**/*.py` as dedicated automated tests (plus `ui/test_results_window.py`, which is UI code that *invokes* pytest on backup tests only).

There are **no** test files under `test/` that import or exercise:

| Action (`ActionType`) | `BatchJob` constructor | Typical modules |
|----------------------|-------------------------|-----------------|
| `RENAMER` | `construct_batch_renamer` | `batch_renamer.py`, `file_renamer.py`, `filename_ops.py` |
| `DUPLICATE_REMOVER` | `construct_duplicate_remover` | `duplicate_remover.py` |
| `DIRECTORY_OBSERVER` | `construct_directory_observer` | `directory_observer.py` |
| `DIRECTORY_FLATTENER` | `construct_directory_flattener` | `batch_renamer.py` (`DirectoryFlattener`) |
| `IMAGE_CATEGORIZER` | `construct_image_categorizer` | `image_categorizer.py` |

**Conclusion:** Your recollection is **correct**: aside from shared infrastructure touched by backup/batch tests (e.g. `FiletypesDefinition`, `BatchJob` for YAML isolation), **none of the other action types have automated tests** in this repository today.

## What *is* covered (indirectly)

- **Backup path only** — `test/backup/*` and `BatchJob` usage in `test_batch_backup_yaml.py` (BACKUP actions).
- **UI test runner** — `ui/test_results_window.py` runs a fixed list of files under `test/backup/` only; it does not run suites for other actions (because those suites do not exist yet).

## Suggested coverage gaps to close (incremental)

Use the same patterns as backup where possible: `tmp_path`, isolated configs, registry snapshots for global `FiletypesDefinition` / `FilenameMappingDefinition` state.

1. **`RENAMER`**
   - Unit: `BatchRenamer` / `FileRenamer` with a temp directory and `test=True`.
   - Integration: minimal YAML under `tmp_path` with `BatchJob.BASE_DIR` patched, `type: RENAMER`, assert renamed output or no-op in dry-run.

2. **`DUPLICATE_REMOVER`**
   - Unit: `DuplicateRemover` with synthetic duplicate files in `tmp_path`.
   - Integration: YAML → `construct_duplicate_remover` → `run()` with `test=True`.

3. **`DIRECTORY_OBSERVER`**
   - Unit: `DirectoryObserver` construction and any observable side effects that are safe in tests (may require mocking filesystem watchers if applicable).

4. **`DIRECTORY_FLATTENER`**
   - Unit: `DirectoryFlattener` on nested temp files, `test=True`.

5. **`IMAGE_CATEGORIZER`**
   - Unit: `ImageCategorizer` with tiny fixture images or mocked model calls, depending on dependencies.

6. **`BatchJob.run()` / `run_action`**
   - One smoke test per action type that the dispatcher routes to the right `construct_*` and completes without error on minimal valid YAML (optional cross-cutting test module, e.g. `test/batch/test_action_dispatch_smoke.py`).

## Related code references

- `refacdir/batch.py` — `ActionType`, `run_action`, `construct_*` methods.
- `configs/` / `master_config.yaml` — real configs are not a substitute for automated tests.
