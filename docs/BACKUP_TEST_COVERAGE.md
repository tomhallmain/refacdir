# Backup test coverage reference

Tracks automated coverage for `refacdir/backup/` and batch YAML loading. See `test/backup/*.py`.

## Action types (`BackupMode`)

| Mode | Intent | Integration tests (`test_backup.py`) | `BackupState.verify_integrity` (`test_backup_state.py`) |
|------|--------|--------------------------------------|---------------------------------------------------------|
| `PUSH` | Copy to target | Yes | Yes |
| `PUSH_AND_REMOVE` | Copy then remove source | Yes; `exclude_removal_dirs` uses copy via `_move_func_for_path` | Yes (cached hash after delete) |
| `PUSH_DUPLICATES` | Copy with duplicate handling | Yes | Yes |
| `MIRROR` | Sync target to source | Yes; `test_mirror_removes_file_that_exists_only_on_target` (stale file) | Yes |
| `MIRROR_DUPLICATES` | Same family as mirror | Yes | Yes |

## Other dimensions

| Dimension | Covered | Notes |
|-----------|---------|--------|
| `FileMode.FILES_AND_DIRS` | Default | — |
| `FileMode.DIRS_ONLY` | `test_file_mode_dirs_only`, `test_mirror_dirs_only_leaves_stray_target_files` | MIRROR+DIRS_ONLY: stray **files** on target are **not** removed today because `_is_file_excluded` is true for all files, so `_mirror_remove_stale` skips them. |
| `HashMode.SHA256` | Default | — |
| `HashMode.FILENAME` | `test_verify_integrity_filename_hash_ignores_content` | Basename-only: integrity can pass when bytes differ. |
| `HashMode.FILENAME_AND_PARENT` | `test_verify_integrity_filename_and_parent_hash` | — |
| `exclude_dirs` / `exclude_removal_dirs` / `will_run` / dry-run | Yes | See `test_backup.py` |
| `report_failures` + JSON | `test_backup_report_failures.py` | Patches `_FAILURE_LOG` under `tmp_path`. |
| `BackupTransaction` rollback | `test_backup_transaction.py` | — |

## YAML / batch integration (isolated from `configs/`)

| Area | Status |
|------|--------|
| `BatchJob.run_config_file` + `FiletypesDefinition` `{{name}}` | **`test/backup/test_batch_backup_yaml.py`** — writes YAML under **`pytest tmp_path`**, **`monkeypatch.setattr(BatchJob, "BASE_DIR", str(tmp_path))`**, and `BatchArgs.override_configs({...})` so nothing is read from the repo `configs/` tree. |
| `BatchJob.construct_backup` + named types | Same module: `test_batch_construct_backup_matches_yaml_named_types` builds definitions then calls `construct_backup` with `{{construct_test_types}}`. |

**Registry isolation:** tests use fixtures that snapshot/restore `FiletypesDefinition.NAMED_DEFINITIONS` and `FilenameMappingDefinition.NAMED_FUNCTIONS`, and restore `BatchArgs.configs` after each test.

## Windows vs POSIX

`test_error_handling` (read-only target dir) is **`@pytest.mark.skipif(sys.platform == "win32", ...)`** because directory chmod does not block writes the same way as on POSIX. Keep the skip unless a dedicated ACL-based test is added.

## `BackupSourceData` (`test_backup_source_data.py`)

Separate suite; many cases predate current `BackupSourceData` behavior. Triage independently.

## Related files

- `refacdir/backup/backup_mapping.py`
- `refacdir/backup/backup_state.py`
- `refacdir/backup/backup_manager.py`
- `refacdir/batch.py` — `construct_backup`, `run_config_file`

## Obsolete backlog (was incremental checklist)

The following were implemented or superseded by the tests above: hash-mode cases, `report_failures`, batch YAML isolation, mirror stale file, MIRROR+DIRS_ONLY behavior note.
