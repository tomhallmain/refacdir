"""Tests for filename / filetype definition registry reset (batch isolation)."""

from refacdir.batch import BatchArgs, BatchJob
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition

_NOOP_CONFIG_ENTRY = {"configs/.registry_test_placeholder_do_not_create.yaml": False}


def test_reset_registration_state_clears_registries():
    FilenameMappingDefinition.add_named_functions(
        [{"name": "reset_test_fn", "type": "DIGITS", "args": [1]}]
    )
    FilenameMappingDefinition.call_from_cache(
        FilenameMappingDefinition.NAMED_FUNCTIONS["reset_test_fn"]
    )
    assert FilenameMappingDefinition.GENERATED_PATTERNS

    FiletypesDefinition.add_named_definitions(
        [{"name": "reset_test_types", "extensions": [".rst"]}]
    )

    FilenameMappingDefinition.reset_registration_state()
    assert not FilenameMappingDefinition.NAMED_FUNCTIONS
    assert not FilenameMappingDefinition.GENERATED_PATTERNS

    FiletypesDefinition.reset_registration_state()
    assert not FiletypesDefinition.NAMED_DEFINITIONS


def test_batch_run_clears_registries_when_not_persisting():
    try:
        args = BatchArgs(configs=dict(_NOOP_CONFIG_ENTRY))
        FilenameMappingDefinition.add_named_functions(
            [{"name": "batch_clear_fn", "type": "DIGITS", "args": [1]}]
        )
        FiletypesDefinition.add_named_definitions(
            [{"name": "batch_clear_types", "extensions": [".bc"]}]
        )
        assert args.persist_definition_caches_across_batch_runs is False
        BatchJob(args).run()
        assert "batch_clear_fn" not in FilenameMappingDefinition.NAMED_FUNCTIONS
        assert "batch_clear_types" not in FiletypesDefinition.NAMED_DEFINITIONS
    finally:
        FilenameMappingDefinition.reset_registration_state()
        FiletypesDefinition.reset_registration_state()


def test_batch_run_keeps_registries_when_persisting():
    try:
        args = BatchArgs(configs=dict(_NOOP_CONFIG_ENTRY))
        FilenameMappingDefinition.add_named_functions(
            [{"name": "batch_persist_fn", "type": "DIGITS", "args": [2]}]
        )
        args.persist_definition_caches_across_batch_runs = True
        BatchJob(args).run()
        assert "batch_persist_fn" in FilenameMappingDefinition.NAMED_FUNCTIONS
    finally:
        FilenameMappingDefinition.reset_registration_state()
        FiletypesDefinition.reset_registration_state()
