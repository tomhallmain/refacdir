"""
Match/affected-file preview for a validated LLM-drafted action dict (Phase 4,
docs/LLM_CONFIG_CHAT_SCOPE.md).

Builds the SAME object ``validate_action`` (Phase 2) would construct — via
the shared ``construct_for_action_type`` — then reads whatever each action
type's own read-only scan mechanism already collects:

- RENAMER, DIRECTORY_FLATTENER: ``BatchRenamer.scan()``.
- DUPLICATE_REMOVER: ``find_duplicates()`` + ``build_review_payload()``.
- DIRECTORY_OBSERVER: ``observe()`` (this action type is inherently read-only
  — there's no distinct "preview" vs. "real run" for it).
- NAMED_SUBDIR_COLLECTOR: ``preview()`` (wraps its existing ``_collect_work``
  scan).
- BACKUP: ``setup()`` + the new ``BackupMapping.preview_changes()``.

Nothing here executes or mutates, regardless of the draft's own
``test``/``skip_confirm`` value — every path below only calls a read-only
scan/observe/find_duplicates method, never ``run()``/``backup()``/``execute()``.
Callers should still run a draft through ``refacdir.llm.safety.apply_safety_defaults``
before this (or before saving it anywhere) — that's a separate, independent
safety net, not something this module depends on.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from refacdir.batch import ActionType
from refacdir.llm.validation import construct_for_action_type


@dataclass
class PreviewResult:
    """Best-effort match/affected-file preview for one action dict."""
    action_type: ActionType
    available: bool
    summary: str = ""
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


def _preview_batch_renamer(action_type: ActionType, renamer) -> PreviewResult:
    scanned_by_location = renamer.scan()
    details = {}
    total = 0
    for location, per_pattern in scanned_by_location.items():
        rules = []
        for pattern, files in per_pattern.items():
            rules.append({"rename_tag": renamer.mappings.get(pattern, ""), "matched_files": files})
            total += len(files)
        details[str(location)] = rules
    summary = f"{total} file(s) matched across {len(scanned_by_location)} location(s)."
    return PreviewResult(action_type=action_type, available=True, summary=summary, details=details)


def _preview_backup(action_type: ActionType, backup_manager) -> PreviewResult:
    details = {}
    total_add_or_update = 0
    total_remove_stale = 0
    for mapping in backup_manager.backup_mappings:
        if not mapping.will_run:
            continue
        mapping.setup(overwrite=backup_manager.overwrite, warn_duplicates=backup_manager.warn_duplicates)
        changes = mapping.preview_changes()
        details[mapping.name] = changes
        total_add_or_update += len(changes["to_add_or_update"])
        total_remove_stale += len(changes["to_remove_stale"])
    summary = (
        f"{total_add_or_update} file(s) would be added/updated, "
        f"{total_remove_stale} stale file(s)/dir(s) would be removed (mirror-mode mappings only)."
    )
    return PreviewResult(action_type=action_type, available=True, summary=summary, details=details)


def _preview_duplicate_remover(action_type: ActionType, duplicate_remover) -> PreviewResult:
    duplicate_remover.find_duplicates()
    payload = duplicate_remover.build_review_payload()
    total = payload["total_duplicate_files"]
    summary = f"{total} duplicate file(s) would be removed across {len(payload['groups'])} group(s)."
    return PreviewResult(action_type=action_type, available=True, summary=summary, details=payload)


def _preview_directory_observer(action_type: ActionType, observer) -> PreviewResult:
    observer.observe()
    details = {directory: dict(dir_data.dict) for directory, dir_data in observer.dir_data.items()}
    summary = (
        f"{observer.total_file_count_types} of {observer.total_file_count} total file(s) "
        f"matched tracked types across {len(details)} directory/directories."
    )
    return PreviewResult(action_type=action_type, available=True, summary=summary, details=details)


def _preview_named_subdir_collector(action_type: ActionType, collector) -> PreviewResult:
    work = collector.preview()
    total = len(work["work_items"])
    summary = f"{total} file(s) would be collected into {len(collector.subdir_names)} named subdirector(y/ies)."
    return PreviewResult(action_type=action_type, available=True, summary=summary, details=work)


_PREVIEW_DISPATCH = {
    ActionType.DUPLICATE_REMOVER: _preview_duplicate_remover,
    ActionType.DIRECTORY_OBSERVER: _preview_directory_observer,
    ActionType.NAMED_SUBDIR_COLLECTOR: _preview_named_subdir_collector,
    ActionType.BACKUP: _preview_backup,
}


def preview_action(action_type: ActionType, action_dict: dict) -> PreviewResult:
    """
    Best-effort match/affected-file preview for ``action_dict``.

    Raises ``ValueError`` immediately for an unsupported ``action_type`` —
    same boundary as ``validation.validate_action``. Any other failure
    (construction error, or a location pointing at a directory that doesn't
    exist yet — a valid, allowed state for a draft, see
    docs/LLM_CONFIG_CHAT_SCOPE.md's Phase 2 entry) is reported via
    ``PreviewResult(available=False, reason=...)``, never raised — a caller
    (e.g. a Phase 5 UI) can always call this on a validated draft and get
    something displayable back.
    """
    try:
        constructed = construct_for_action_type(action_type, action_dict)
    except ValueError:
        raise
    except Exception as exc:
        return PreviewResult(action_type=action_type, available=False, reason=str(exc))

    try:
        if action_type == ActionType.RENAMER:
            renamer, _renamer_function = constructed
            return _preview_batch_renamer(action_type, renamer)
        if action_type == ActionType.DIRECTORY_FLATTENER:
            return _preview_batch_renamer(action_type, constructed.batch_renamer)
        return _PREVIEW_DISPATCH[action_type](action_type, constructed)
    except Exception as exc:
        return PreviewResult(action_type=action_type, available=False, reason=str(exc))
