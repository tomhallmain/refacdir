"""
Safety defaults for LLM-drafted action dicts.

Forces every LLM-drafted action into its safest, no-file-touched state before
it is validated or ever saved into a real config as live — regardless of what
the model's draft said (or hallucinated) for the relevant field.
``refacdir/llm/conversation.py``'s ``draft_action`` applies this to every
parsed draft before validation, so nothing downstream ever sees an
LLM-drafted action that skips confirmation or runs live. A UI
presenting a draft for "run for real" must explicitly and separately clear
the override; nothing in this feature does that itself.
"""

from refacdir.batch import ActionType
from refacdir.llm.config_schema import SUPPORTED_ACTION_CONSTRUCTORS

# Action types whose construct_* accepts a top-level "test" dry-run flag —
# see each one's docstring in refacdir/batch.py.
_TEST_FIELD_ACTION_TYPES = frozenset((
    ActionType.RENAMER,
    ActionType.BACKUP,
    ActionType.DIRECTORY_FLATTENER,
    ActionType.NAMED_SUBDIR_COLLECTOR,
    ActionType.ARCHIVE_EXTRACTOR,
    ActionType.DUPLICATE_REMOVER,
))


def apply_safety_defaults(action_type: ActionType, action_dict: dict) -> dict:
    """
    Return a COPY of ``action_dict`` with the safest dry-run/confirmation
    field forced for ``action_type``:

    - RENAMER, BACKUP, DIRECTORY_FLATTENER, NAMED_SUBDIR_COLLECTOR,
      ARCHIVE_EXTRACTOR, DUPLICATE_REMOVER: top-level ``test`` forced to
      ``True``.
    - DUPLICATE_REMOVER also has ``skip_confirm`` forced to ``False``, so once
      ``test`` is cleared for a live run, ``DuplicateRemover.run()``'s
      interactive / ``app_actions.review_duplicates`` confirmation step is
      still not bypassed.
    - DIRECTORY_OBSERVER: read-only reporting, no destructive operation
      exists at all — returned unchanged.

    Raises ``ValueError`` for an unsupported ``action_type`` (currently just
    ``ActionType.IMAGE_CATEGORIZER``) — same boundary as
    ``config_schema.get_schema_description`` / ``validation.validate_action``.
    """
    if action_type not in SUPPORTED_ACTION_CONSTRUCTORS:
        raise ValueError(
            f"No safety defaults defined for {action_type.name}; it has no "
            "entry in SUPPORTED_ACTION_CONSTRUCTORS."
        )

    safe_dict = dict(action_dict)
    if action_type in _TEST_FIELD_ACTION_TYPES:
        safe_dict["test"] = True
    if action_type == ActionType.DUPLICATE_REMOVER:
        safe_dict["skip_confirm"] = False
    return safe_dict
