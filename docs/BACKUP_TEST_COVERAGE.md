# Backup test coverage reference

This document tracks automated test coverage for `refacdir/backup/` (modes, state, manager) and highlights gaps for incremental work. Last reviewed alongside `test/backup/*.py`.

## Action types (`BackupMode`)

| Mode | Intent | Integration tests (`test_backup.py`) | `BackupState.verify_integrity` (`test_backup_state.py`) |
|------|--------|--------------------------------------|---------------------------------------------------------|
| `PUSH` | Copy to target | Yes — `test_basic_push`, file types, exclude dirs, multiple mappings, atomic ops | Yes — `test_verify_integrity_push`, hash mismatch |
| `PUSH_AND_REMOVE` | Copy then remove source | Yes — `test_push_and_remove`; `test_exclude_removal_dirs_with_push_and_remove` (copy-not-move under `exclude_removal_dirs`) | Yes — `test_verify_integrity_push_and_remove_uses_cached_source_hash` |
| `PUSH_DUPLICATES` | Copy with duplicate handling | Yes — `test_duplicate_handling` | Yes — `test_verify_integrity_push_duplicates` |
| `MIRROR` | Sync target to source (add/update/remove) | Yes — `test_mirror` (two runs + deletes) | Yes — mismatch / hash tests |
| `MIRROR_DUPLICATES` | Same family as mirror | Yes — `test_mirror_duplicates_mode` (smoke) | Yes — `test_verify_integrity_mirror_duplicates_mismatch` |

## Other dimensions

| Dimension | Covered | Gaps / notes |
|-----------|---------|----------------|
| `FileMode.FILES_AND_DIRS` | Default in most tests | — |
| `FileMode.DIRS_ONLY` | `test_file_mode_dirs_only` | No combination with `MIRROR` / `PUSH_AND_REMOVE`. |
| `HashMode.SHA256` | Default | Primary path for real backups. |
| `HashMode.FILENAME` | — | No integration or `BackupState` test; semantics are basename-only. |
| `HashMode.FILENAME_AND_PARENT` | — | No automated test. |
| `exclude_dirs` | `test_exclude_dirs` | — |
| `exclude_removal_dirs` | `test_exclude_removal_dirs_with_push_and_remove` | Requires copy for excluded paths when mode is `PUSH_AND_REMOVE` (see `_move_func_for_path` in `backup_mapping.py`). |
| `will_run` on `BackupMapping` | `test_will_run_false_skips_mapping` | — |
| `BackupManager.test` (dry run) | `test_manager_dry_run_leaves_target_empty` | Could assert zero transaction ops / logs if needed. |
| `BackupManager` confirm prompt | — | Interactive; not unit-tested (would need mock of `input`). |
| `report_failures` / JSON log | — | Could add temp-dir test that forces a failure and asserts file + contents. |
| `BackupTransaction` rollback | `test_backup_transaction.py` | End-to-end rollback on failed copy is only indirectly covered. |

## YAML / batch integration

| Area | Status |
|------|--------|
| `BatchJob.construct_backup` + `FiletypesDefinition` `{{name}}` | Not covered in `test/backup/` (manual / app-level). |
| Full config load from `configs/*.yaml` | Optional e2e or small fixture YAML in `test/backup/`. |

## `BackupSourceData` (`test_backup_source_data.py`)

Large module with its own suite. Many tests predate current behavior; treat failures there as a separate triage (metadata, locks, compression). Not included in the matrix above.

## Incremental improvement checklist

Use this as a backlog; none of these block the core mapping tests.

1. **Hash modes** — Add one small `test_backup_state` (or integration) case each for `FILENAME` and `FILENAME_AND_PARENT` documenting expected match/mismatch behavior.
2. **MIRROR + DIRS_ONLY** — If supported, add scenario; if not, document “unsupported” in code or doc.
3. **Failure paths** — Unit test `report_failures` writes `backup_failures.json` and logs (temporary directory, forced `FailureType`).
4. **Windows vs POSIX** — `test_error_handling` is skipped on Windows; optional ctypes/ACL test or keep skip documented.
5. **Batch YAML** — Single test that builds a `BackupMapping` from a minimal dict matching `construct_backup` (optional `FiletypesDefinition` registration).
6. **Stale mirror removal** — Target-only extra files with same relative layout as `test_mirror` already exercises removal; optional explicit “extra file on target only” assert.

## Related files

- `refacdir/backup/backup_mapping.py` — push/mirror/setup/reporting.
- `refacdir/backup/backup_state.py` — validation and integrity.
- `refacdir/backup/backup_manager.py` — orchestration, `test` flag, `will_run`.
- `refacdir/batch.py` — `construct_backup` YAML wiring.
