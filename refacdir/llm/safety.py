"""
Safety defaults for LLM-drafted action dicts (Phase 4,
docs/LLM_CONFIG_CHAT_SCOPE.md).

Forces every LLM-drafted action into its safest, no-file-touched state before
it is validated or ever saved into a real config as live — regardless of what
the model's draft said (or hallucinated) for the relevant field.
``refacdir/llm/conversation.py``'s ``draft_action`` applies this to every
parsed draft before validation, so nothing downstream ever sees an
LLM-drafted action that skips confirmation or runs live. A UI (Phase 5)
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
))


def apply_safety_defaults(action_type: ActionType, action_dict: dict) -> dict:
    """
    Return a COPY of ``action_dict`` with the safest dry-run/confirmation
    field forced for ``action_type``:

    - RENAMER, BACKUP, DIRECTORY_FLATTENER, NAMED_SUBDIR_COLLECTOR: top-level
      ``test`` forced to ``True``.
    - DUPLICATE_REMOVER: has no ``test`` field at all (see
      ``construct_duplicate_remover``) — ``skip_confirm`` is forced to
      ``False`` instead, so ``DuplicateRemover.run()``'s own built-in
      interactive / ``app_actions.review_duplicates`` confirmation step is
      never bypassed.
    - DIRECTORY_OBSERVER: read-only reporting, no destructive operation
      exists at all — returned unchanged.

    Raises ``ValueError`` for an unsupported ``action_type`` (currently just
    ``ActionType.IMAGE_CATEGORIZER``) — same boundary as
    ``config_schema.get_schema_description`` / ``validation.validate_action``.
    """
    if action_type not in SUPPORTED_ACTION_CONSTRUCTORS:
        raise ValueError(
            f"No safety defaults defined for {action_type.name} yet "
            "(see docs/LLM_CONFIG_CHAT_SCOPE.md — not in Phase 1/2/4 scope)."
        )

    safe_dict = dict(action_dict)
    if action_type in _TEST_FIELD_ACTION_TYPES:
        safe_dict["test"] = True
    elif action_type == ActionType.DUPLICATE_REMOVER:
        safe_dict["skip_confirm"] = False
    return safe_dict
