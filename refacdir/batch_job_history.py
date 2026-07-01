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


def _operation_can_reverse(op: dict[str, Any]) -> bool:
    if not op.get("reversible") or op.get("reversed"):
        return False
    if op.get("type") not in REVERSIBLE_OP_TYPES:
        return False
    dest = op.get("dest")
    return bool(dest and os.path.isfile(dest))


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

    history = app_info_cache.get_batch_job_history()
    job_index = next((i for i, j in enumerate(history) if j.get("job_id") == job_id), None)
    if job_index is None:
        raise ValueError(f"Batch job not found in history: {job_id}")

    job = history[job_index]
    result = ReverseResult(job_id=job_id, dry_run=dry_run)

    for op in reversed(job.get("operations", [])):
        if not _operation_matches_filter(op, config=config, mapping_name=mapping_name):
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
        except OSError as exc:
            result.failed += 1
            result.errors.append(f"{dest} -> {source}: {exc}")

    if not dry_run and result.succeeded:
        history[job_index] = job
        app_info_cache.set_batch_job_history(history)

    return result
