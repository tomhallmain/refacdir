"""
Record batch job file operations for optional reversal.

Only non-dry-run renames/moves performed during an active batch session are stored.
History is persisted in the encrypted app_info_cache (max 20 jobs).
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from refacdir.utils.logger import setup_logger

logger = setup_logger("batch_job_history")

MAX_BATCH_JOB_HISTORY = 20
REVERSIBLE_OP_TYPES = frozenset({"rename", "move"})


@dataclass
class ReverseResult:
    job_id: str
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False


class _BatchJobSession:
    def __init__(self, configs: list[str], test: bool):
        self.job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.configs = list(configs)
        self.test = test
        self.operations: list[dict[str, Any]] = []

    def record(self, op_type: str, source: str, dest: str, *, reversible: bool = True, meta: Optional[dict] = None):
        self.operations.append(
            {
                "type": op_type,
                "source": os.path.normpath(source),
                "dest": os.path.normpath(dest),
                "reversible": bool(reversible and op_type in REVERSIBLE_OP_TYPES),
                "reversed": False,
                "meta": _merged_meta(meta),
            }
        )

    def to_record(self, counts_map: dict, failures: list, cancelled: bool) -> dict[str, Any]:
        reversible_count = sum(1 for op in self.operations if op.get("reversible") and not op.get("reversed"))
        return {
            "job_id": self.job_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "configs": self.configs,
            "test": self.test,
            "cancelled": cancelled,
            "failures": list(failures),
            "action_counts": {k.name if hasattr(k, "name") else str(k): v for k, v in counts_map.items()},
            "operations": self.operations,
            "reversible_operation_count": reversible_count,
        }


_active_session: Optional[_BatchJobSession] = None
_recording_context: Optional[dict[str, Any]] = None


@contextmanager
def recording_context(**meta: Any) -> Iterator[None]:
    """Attach metadata (config, mapping_name, etc.) to file operations recorded in this block."""
    global _recording_context
    prev = _recording_context
    _recording_context = {k: v for k, v in meta.items() if v is not None}
    try:
        yield
    finally:
        _recording_context = prev


def _merged_meta(meta: Optional[dict]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if _recording_context:
        merged.update(_recording_context)
    if meta:
        merged.update(meta)
    return merged


def begin_batch_job(configs: list[str], test: bool = False) -> None:
    """Start recording for a batch run. Dry-run jobs are not recorded."""
    global _active_session
    if test:
        _active_session = None
        return
    _active_session = _BatchJobSession(configs, test=False)
    logger.debug("Batch job history session started: %s", _active_session.job_id)


def record_file_operation(
    op_type: str,
    source: str,
    dest: str,
    *,
    reversible: bool = True,
    meta: Optional[dict] = None,
) -> None:
    """Record a file operation from FileRenamer or similar (no-op if no active session)."""
    if _active_session is None:
        return
    _active_session.record(op_type, source, dest, reversible=reversible, meta=meta)


def finish_batch_job(counts_map: dict, failures: list, cancelled: bool = False) -> Optional[str]:
    """Persist the active session to app_info_cache. Returns job_id or None."""
    global _active_session
    if _active_session is None:
        return None

    from refacdir.utils.app_info_cache import app_info_cache

    record = _active_session.to_record(counts_map, failures, cancelled)
    job_id = record["job_id"]
    app_info_cache.prepend_batch_job_record(record)
    logger.info(
        "Batch job history saved: %s (%s file operation(s), %s reversible)",
        job_id,
        len(record["operations"]),
        record["reversible_operation_count"],
    )
    _active_session = None
    return job_id


def get_batch_job_history() -> list[dict[str, Any]]:
    from refacdir.utils.app_info_cache import app_info_cache

    return app_info_cache.get_batch_job_history()


def find_batch_job(job_id: str) -> Optional[dict[str, Any]]:
    for job in get_batch_job_history():
        if job.get("job_id") == job_id:
            return job
    return None


def job_mapping_groups(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarize recorded operations grouped by config + renamer mapping name."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for op in job.get("operations") or []:
        meta = op.get("meta") or {}
        config = meta.get("config") or ""
        mapping_name = meta.get("mapping_name") or ""
        key = (config, mapping_name)
        if key not in groups:
            groups[key] = {
                "config": config,
                "mapping_name": mapping_name,
                "operation_count": 0,
                "reversible_count": 0,
            }
        groups[key]["operation_count"] += 1
        if op.get("reversible") and not op.get("reversed"):
            groups[key]["reversible_count"] += 1
    return sorted(groups.values(), key=lambda g: (g["config"], g["mapping_name"]))


def _operation_matches_filter(
    op: dict[str, Any],
    *,
    config: Optional[str] = None,
    mapping_name: Optional[str] = None,
) -> bool:
    if config is None and mapping_name is None:
        return True
    meta = op.get("meta") or {}
    if config is not None and meta.get("config") != config:
        return False
    if mapping_name is not None and meta.get("mapping_name") != mapping_name:
        return False
    return True


def _legacy_renamer_roots(config: str, mapping_name: str) -> list[str]:
    """
    Best-effort recovery of the root director(y/ies) a "renamer" mapping used,
    by re-reading its config YAML — used only to resolve history entries
    recorded with a path relative to that root, from before ``rename_file``
    started recording absolute paths (see file_renamer.py). Returns an empty
    list rather than raising if the config/mapping can no longer be found
    (edited or deleted since, wrong action type, etc.): this is a best-effort
    rescue, not something callers should depend on succeeding.
    """
    if not config or not mapping_name:
        logger.warning(
            "Cannot look up legacy renamer roots: operation is missing config/mapping_name "
            "in its recorded meta (config=%r, mapping_name=%r) — it was likely recorded "
            "without a recording_context, so there's nothing to re-derive roots from.",
            config, mapping_name,
        )
        return []

    import yaml
    from refacdir.batch import BatchJob

    config_path = os.path.join(BatchJob.BASE_DIR, config)
    if not os.path.isfile(config_path):
        logger.warning(
            "Cannot rescue paths for mapping %r: config file not found at %r "
            "(BatchJob.BASE_DIR=%r, recorded config=%r)",
            mapping_name, config_path, BatchJob.BASE_DIR, config,
        )
        return []
    try:
        with open(config_path, "r") as f:
            config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
    except yaml.YAMLError as exc:
        logger.warning("Cannot rescue paths for mapping %r: failed to parse %r: %s", mapping_name, config_path, exc)
        return []
    if not isinstance(config_wrapper, dict):
        logger.warning("Cannot rescue paths for mapping %r: %r did not parse to a YAML mapping", mapping_name, config_path)
        return []

    from refacdir.batch_renamer import Location

    for action in config_wrapper.get("actions") or []:
        if not isinstance(action, dict) or action.get("type") != "RENAMER":
            continue
        for renamer in action.get("mappings") or []:
            if not isinstance(renamer, dict) or renamer.get("name") != mapping_name:
                continue
            roots = []
            for raw_location in renamer.get("locations") or []:
                # Location.construct applies the same {{USER_HOME}} expansion and
                # separator/normpath fixups the real batch run used when it
                # recorded these paths (see Utils.fix_path) — using the raw YAML
                # string directly would leave "{{USER_HOME}}" unexpanded and
                # never match any real file on disk.
                try:
                    root = Location.construct(raw_location).root
                except (TypeError, KeyError) as exc:
                    logger.warning("Skipping unparseable location %r for %r/%r: %s", raw_location, config, mapping_name, exc)
                    continue
                if root:
                    roots.append(root)
            logger.info("Resolved roots for %r/%r: %r", config, mapping_name, roots)
            return roots
    logger.warning(
        "Cannot rescue paths for mapping %r: no RENAMER mapping with that name found in %r "
        "(the config may have been edited/renamed since this job ran)",
        mapping_name, config_path,
    )
    return []


def _resolve_legacy_operation_paths(op: dict[str, Any], roots: list[str]) -> Optional[tuple[str, str]]:
    """
    ``op``'s source/dest may be relative to whichever root its mapping used
    at record time. Identify which candidate root is correct by checking
    where ``dest`` actually exists as a file today (``source`` can't be used
    for this — it's expected to no longer exist, that's the whole point of a
    rename) and only resolve when exactly one root matches, so an ambiguous
    or unresolvable case is left alone rather than guessed at.
    """
    source, dest = op.get("source"), op.get("dest")
    if not source or not dest:
        logger.warning("Cannot resolve operation with missing source/dest: source=%r dest=%r", source, dest)
        return None
    if os.path.isabs(source) and os.path.isabs(dest):
        return None

    if not roots:
        logger.warning("Cannot resolve relative dest %r: no candidate roots to try", dest)
        return None

    candidates = {
        root: (dest if os.path.isabs(dest) else os.path.normpath(os.path.join(root, dest)))
        for root in roots
    }
    matched_roots = [root for root, candidate in candidates.items() if os.path.isfile(candidate)]

    if not matched_roots:
        logger.warning(
            "Cannot resolve relative dest %r: not found as a file under any candidate root %r "
            "(tried: %r) — it may have been moved/deleted/renamed again since this job ran",
            dest, roots, list(candidates.values()),
        )
        return None
    if len(matched_roots) > 1:
        logger.warning(
            "Cannot resolve relative dest %r: matched more than one candidate root %r "
            "(ambiguous — leaving unresolved rather than guessing)",
            dest, matched_roots,
        )
        return None

    root = matched_roots[0]
    resolved_source = source if os.path.isabs(source) else os.path.normpath(os.path.join(root, source))
    resolved_dest = dest if os.path.isabs(dest) else os.path.normpath(os.path.join(root, dest))
    logger.info("Resolved legacy operation using root %r: %r -> %r, %r -> %r", root, source, resolved_source, dest, resolved_dest)
    return resolved_source, resolved_dest


def rescue_legacy_relative_paths(job_id: str) -> dict[str, int]:
    """
    One-time repair for a job recorded before ``rename_file`` stored absolute
    source/dest paths: relative paths from that era can't be resolved against
    whatever cwd a later reversal happens to run from, so every such
    operation looks "missing" and gets skipped (see ``_operation_can_reverse``).

    Re-reads each operation's config YAML (via its recorded ``meta``) to
    recover the root(s) its mapping used, and rewrites source/dest to
    absolute paths in place wherever that resolution is unambiguous. Safe to
    call on an already-fixed or partially-fixed job: already-absolute
    operations are left untouched, and unresolvable ones are left exactly as
    they were — never corrupted, just still unrevivable until you run this
    again after e.g. moving the file back into a matching root.

    Returns ``{"repaired": n, "unresolved": n}``. Call this before
    ``reverse_job`` for a job whose reversal reports everything "skipped".
    """
    from refacdir.utils.app_info_cache import app_info_cache

    logger.info("Rescuing legacy relative paths for job %s", job_id)

    history = app_info_cache.get_batch_job_history()
    job_index = next((i for i, j in enumerate(history) if j.get("job_id") == job_id), None)
    if job_index is None:
        raise ValueError(f"Batch job not found in history: {job_id}")

    job = history[job_index]
    roots_by_key: dict[tuple[str, str], list[str]] = {}
    repaired = 0
    unresolved = 0
    already_absolute = 0

    for op in job.get("operations", []):
        source, dest = op.get("source"), op.get("dest")
        if source is None or dest is None:
            logger.warning("Operation missing source/dest entirely, skipping: %r", op)
            continue
        if os.path.isabs(source) and os.path.isabs(dest):
            already_absolute += 1
            continue

        meta = op.get("meta") or {}
        key = (meta.get("config") or "", meta.get("mapping_name") or "")
        logger.debug("Operation needs rescue: source=%r dest=%r config=%r mapping_name=%r", source, dest, key[0], key[1])
        if key not in roots_by_key:
            roots_by_key[key] = _legacy_renamer_roots(*key)

        resolved = _resolve_legacy_operation_paths(op, roots_by_key[key])
        if resolved is None:
            unresolved += 1
            continue
        op["source"], op["dest"] = resolved
        repaired += 1

    if repaired:
        history[job_index] = job
        app_info_cache.set_batch_job_history(history)

    logger.info(
        "Rescue complete for job %s: repaired=%d unresolved=%d already_absolute=%d",
        job_id, repaired, unresolved, already_absolute,
    )
    return {"repaired": repaired, "unresolved": unresolved}


def _operation_can_reverse(op: dict[str, Any]) -> bool:
    meta = op.get("meta") or {}
    source, dest = op.get("source"), op.get("dest")
    context = f"source={source!r} dest={dest!r} type={op.get('type')!r} config={meta.get('config')!r} mapping_name={meta.get('mapping_name')!r}"

    if not op.get("reversible"):
        logger.debug("Skipping (not reversible): %s", context)
        return False
    if op.get("reversed"):
        logger.debug("Skipping (already reversed): %s", context)
        return False
    if op.get("type") not in REVERSIBLE_OP_TYPES:
        logger.debug("Skipping (type %r not in %r): %s", op.get("type"), sorted(REVERSIBLE_OP_TYPES), context)
        return False
    if not dest:
        logger.warning("Skipping (no dest recorded): %s", context)
        return False
    if not os.path.isabs(dest):
        logger.warning(
            "Skipping: dest is a relative path, not absolute — this operation predates absolute-path "
            "recording and hasn't been rescued (call rescue_legacy_relative_paths(job_id) first): %s",
            context,
        )
        return False
    if not os.path.isfile(dest):
        logger.warning(
            "Skipping: dest does not exist as a file (may already be reversed outside this tool, "
            "moved, or renamed again since): %s",
            context,
        )
        return False
    return True


def reverse_job(
    job_id: str,
    *,
    config: Optional[str] = None,
    mapping_name: Optional[str] = None,
    dry_run: bool = False,
) -> ReverseResult:
    """
    Reverse reversible file operations for a job (newest operation first).

    When ``config`` and/or ``mapping_name`` are given, only operations from that
    renamer mapping are reversed (still newest-first within the filtered set).

    Each successful reverse moves ``dest`` back to ``source`` when the file still
    exists at ``dest`` and ``source`` is not occupied.
    """
    from refacdir.utils.app_info_cache import app_info_cache

    logger.info("Reversing job %s (config=%r, mapping_name=%r, dry_run=%s)", job_id, config, mapping_name, dry_run)

    history = app_info_cache.get_batch_job_history()
    job_index = next((i for i, j in enumerate(history) if j.get("job_id") == job_id), None)
    if job_index is None:
        raise ValueError(f"Batch job not found in history: {job_id}")

    job = history[job_index]
    result = ReverseResult(job_id=job_id, dry_run=dry_run)
    filtered_out = 0

    for op in reversed(job.get("operations", [])):
        if not _operation_matches_filter(op, config=config, mapping_name=mapping_name):
            filtered_out += 1
            continue
        if not _operation_can_reverse(op):
            if op.get("reversible") and not op.get("reversed"):
                result.skipped += 1
            continue

        source = op["source"]
        dest = op["dest"]
        result.attempted += 1

        if os.path.exists(source):
            msg = f"Cannot reverse: destination already exists: {source}"
            logger.warning(msg)
            result.failed += 1
            result.errors.append(msg)
            continue

        if dry_run:
            result.succeeded += 1
            continue

        try:
            parent = os.path.dirname(source)
            if parent:
                os.makedirs(parent, exist_ok=True)
            os.rename(dest, source)
            op["reversed"] = True
            result.succeeded += 1
            logger.info("Reversed: %s -> %s", dest, source)
        except OSError as exc:
            logger.warning("Failed to reverse %s -> %s: %s", dest, source, exc)
            result.failed += 1
            result.errors.append(f"{dest} -> {source}: {exc}")

    if not dry_run and result.succeeded:
        history[job_index] = job
        app_info_cache.set_batch_job_history(history)

    logger.info(
        "Reverse job %s complete: attempted=%d succeeded=%d failed=%d skipped=%d filtered_out=%d",
        job_id, result.attempted, result.succeeded, result.failed, result.skipped, filtered_out,
    )
    return result
