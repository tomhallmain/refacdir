"""
"Dry construct" validation harness for LLM-drafted action dicts.

Runs a candidate dict through the SAME ``BatchJob.construct_*`` method a real
batch run would use, so validation stays correct automatically as the schema
evolves — no separate hand-rolled schema to maintain (see
refacdir/llm/config_schema.py's module docstring for why that matters).

See docs/LLM_CONFIG_CHAT_SCOPE.md, Phase 2.
"""

from dataclasses import dataclass, field
from typing import List

from refacdir.batch import ActionType, BatchArgs, BatchJob
from refacdir.llm.config_schema import SUPPORTED_ACTION_CONSTRUCTORS

# Distinct, stable substrings from the exception messages construct_* methods
# (via DuplicateRemover/DirectoryObserver) raise when a referenced directory
# doesn't exist on disk. Treated as warnings, not errors: the user may be
# describing a not-yet-existing setup, and the YAML's SHAPE is still correct —
# see "Decide how to handle constructors that expect real paths to exist" in
# docs/LLM_CONFIG_CHAT_SCOPE.md's Phase 2 entry. Every other action type's
# construct_* method has no eager path-existence check at all (FileRenamer/
# BackupManager/NamedSubdirCollector resolve paths lazily, at execution time).
_PATH_EXISTENCE_ERROR_MARKERS = (
    "Invalid directory provided",       # DirectoryObserver: sortable/extra/parent/exclude dirs
    "Invalid exclude directory",        # DuplicateRemover
    "Invalid preferred delete directory",  # DuplicateRemover
)


def _is_path_existence_error(message: str) -> bool:
    return any(marker in message for marker in _PATH_EXISTENCE_ERROR_MARKERS)


@dataclass
class ValidationResult:
    """Result of dry-constructing one candidate action dict."""
    action_type: ActionType
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def error_summary(self) -> str:
        """Errors joined into one string, ready to feed back into a retry prompt."""
        return "\n".join(self.errors)


def _build_validation_batch_job() -> BatchJob:
    """
    A minimal BatchJob for dry-constructing action dicts.

    Uses a non-empty placeholder ``configs`` dict so BatchArgs doesn't trigger
    its real disk scan of the configs/ directory (an empty/None configs dict
    would); the placeholder is marked will_run=False and is never read by any
    construct_* method, which only ever receive the action dict passed to
    validate_action directly.
    """
    args = BatchArgs(configs={"__llm_validation_placeholder__.yaml": False})
    return BatchJob(args)


def construct_for_action_type(action_type: ActionType, action_dict: dict):
    """
    Dry-construct ``action_dict`` via the real ``BatchJob.construct_*`` method
    for ``action_type`` and return whatever object it returns (e.g. a
    ``(BatchRenamer, function_name)`` tuple for RENAMER, a ``BackupManager``
    for BACKUP, etc.) — or let the original exception propagate.

    Low-level building block shared by ``validate_action`` (below, which
    turns a construction failure into a structured ``ValidationResult``) and
    ``refacdir/llm/preview.py`` (Phase 4, which needs the actual constructed
    object — not just a valid/invalid verdict — to build a match/affected-file
    preview via each action type's own read-only scan mechanism).

    ``action_dict`` is the shape ``construct_*`` itself expects — e.g. for
    RENAMER, ONE renamer group (name/function/mappings/locations), not the
    outer ``{"type": "RENAMER", "mappings": [...]}`` action wrapper containing
    potentially several groups (matches this feature's v1 scope: one action
    per conversation — see docs/LLM_CONFIG_CHAT_SCOPE.md).

    Raises ``ValueError`` for action types with no constructor yet (currently
    just ``ActionType.IMAGE_CATEGORIZER``) — same boundary as
    ``config_schema.get_schema_description``.
    """
    if action_type not in SUPPORTED_ACTION_CONSTRUCTORS:
        raise ValueError(
            f"No construction support for {action_type.name} yet "
            "(see docs/LLM_CONFIG_CHAT_SCOPE.md — not in Phase 1/2 scope)."
        )

    method_name = SUPPORTED_ACTION_CONSTRUCTORS[action_type]
    batch_job = _build_validation_batch_job()
    constructor = getattr(batch_job, method_name)
    return constructor(action_dict)


def validate_action(action_type: ActionType, action_dict: dict) -> ValidationResult:
    """
    Dry-construct ``action_dict`` via ``construct_for_action_type`` and report
    the result.

    A path-existence failure (see ``_PATH_EXISTENCE_ERROR_MARKERS``) is
    reported as a warning: the draft's shape is correct, the real world just
    doesn't have that directory yet. Any other exception (missing required
    key, wrong type, invalid enum value, etc.) is a structural error — the
    draft itself needs to change, so it's returned for a retry prompt rather
    than silently accepted.

    Raises ``ValueError`` for action types with no constructor yet — see
    ``construct_for_action_type``.
    """
    try:
        construct_for_action_type(action_type, action_dict)
    except ValueError:
        raise
    except KeyError as exc:
        return ValidationResult(
            action_type=action_type,
            valid=False,
            errors=[f"Missing required key: {exc}"],
        )
    except Exception as exc:
        message = str(exc)
        if _is_path_existence_error(message):
            return ValidationResult(action_type=action_type, valid=True, warnings=[message])
        return ValidationResult(action_type=action_type, valid=False, errors=[message])

    return ValidationResult(action_type=action_type, valid=True)
