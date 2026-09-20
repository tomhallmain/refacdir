"""
Prompt-facing description of refacdir's config YAML dialect, assembled from
docstrings on the actual ``BatchJob.construct_*`` methods (and a few shared
building blocks) rather than a hand-maintained duplicate. Keeping the schema
description physically attached to the code it describes means a change to
one is far more likely to surface the other in the same review. A separate
hand-maintained copy drifts silently, and drift here degrades LLM output
quality rather than merely going stale.

Covers only the action types with LLM-assisted generation support.
IMAGE_CATEGORIZER is deliberately excluded: ``get_schema_description`` raises
for it rather than handing the model an incomplete schema.
"""

import inspect

from refacdir.batch import ActionType, BatchJob
from refacdir.batch_renamer import Location
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition

# ActionType -> BatchJob construct_* method name. IMAGE_CATEGORIZER intentionally
# omitted. Public (not underscore-prefixed): refacdir/llm/validation.py
# shares this registry rather than duplicating it.
SUPPORTED_ACTION_CONSTRUCTORS = {
    ActionType.RENAMER: "construct_batch_renamer",
    ActionType.BACKUP: "construct_backup",
    ActionType.DUPLICATE_REMOVER: "construct_duplicate_remover",
    ActionType.DIRECTORY_OBSERVER: "construct_directory_observer",
    ActionType.DIRECTORY_FLATTENER: "construct_directory_flattener",
    ActionType.NAMED_SUBDIR_COLLECTOR: "construct_named_subdir_collector",
    ActionType.ARCHIVE_EXTRACTOR: "construct_archive_extractor",
}

# Shared building blocks referenced by more than one action type's schema.
_SHARED_REFERENCE_SOURCES = [
    Location.construct,
    FilenameMappingDefinition.construct_mappings,
    FiletypesDefinition.get_definitions,
]


def supported_action_types() -> list:
    """Action types with a schema description (excludes IMAGE_CATEGORIZER)."""
    return list(SUPPORTED_ACTION_CONSTRUCTORS.keys())


def _clean_doc(func) -> str:
    doc = inspect.getdoc(func)
    if not doc:
        raise ValueError(
            f"{func.__qualname__} has no docstring — this schema description "
            "relies on construct_* (and shared helper) docstrings staying "
            "populated. Add one before using this in an LLM prompt."
        )
    return doc


def get_schema_description(action_type: ActionType) -> str:
    """
    Return the prompt-facing schema description for one action type, sourced
    directly from its ``BatchJob.construct_*`` docstring.

    Raises ``ValueError`` for action types not yet supported (currently just
    ``ActionType.IMAGE_CATEGORIZER``) so a caller can't silently hand the
    model an empty or wrong schema.
    """
    if action_type not in SUPPORTED_ACTION_CONSTRUCTORS:
        raise ValueError(
            f"No LLM-facing schema description for {action_type.name}; it has "
            "no entry in SUPPORTED_ACTION_CONSTRUCTORS."
        )
    method_name = SUPPORTED_ACTION_CONSTRUCTORS[action_type]
    method = getattr(BatchJob, method_name)
    return _clean_doc(method)


def get_shared_vocabulary_description() -> str:
    """
    Cross-cutting vocabulary shared by more than one action type: locations,
    the ``{{...}}`` filename pattern templating system (including the inline
    ``{{type:arg1:arg2}}`` syntax), and named filetype definitions.
    """
    sections = [_clean_doc(func) for func in _SHARED_REFERENCE_SOURCES]
    return "\n\n".join(sections)


def get_full_schema_description(action_type: ActionType) -> str:
    """Shared vocabulary + one action type's schema, ready to embed in a system prompt."""
    return (
        get_shared_vocabulary_description()
        + "\n\n---\n\n"
        + get_schema_description(action_type)
    )
