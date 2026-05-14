"""Tests for filename / filetype definition registry reset (batch isolation)."""

from refacdir.batch import BatchArgs, BatchJob
from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition

# ``BatchArgs()`` calls ``setup_configs()`` when ``len(BatchArgs.configs) == 0``, which reloads
# the real master_config from disk. Never use ``override_configs({})`` before ``BatchArgs()``:
# use a non-empty map with ``will_run=False`` so no YAML is opened and no user batch runs.
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
    prev_configs = dict(BatchArgs.configs)
    try:
        BatchArgs.override_configs(dict(_NOOP_CONFIG_ENTRY))
        FilenameMappingDefinition.add_named_functions(
            [{"name": "batch_clear_fn", "type": "DIGITS", "args": [1]}]
        )
        FiletypesDefinition.add_named_definitions(
            [{"name": "batch_clear_types", "extensions": [".bc"]}]
        )
        args = BatchArgs()
        assert args.persist_definition_caches_across_batch_runs is False
        BatchJob(args).run()
        assert "batch_clear_fn" not in FilenameMappingDefinition.NAMED_FUNCTIONS
        assert "batch_clear_types" not in FiletypesDefinition.NAMED_DEFINITIONS
    finally:
        BatchArgs.configs = prev_configs
        FilenameMappingDefinition.reset_registration_state()
        FiletypesDefinition.reset_registration_state()


def test_batch_run_keeps_registries_when_persisting():
    prev_configs = dict(BatchArgs.configs)
    try:
        BatchArgs.override_configs(dict(_NOOP_CONFIG_ENTRY))
        FilenameMappingDefinition.add_named_functions(
            [{"name": "batch_persist_fn", "type": "DIGITS", "args": [2]}]
        )
        args = BatchArgs()
        args.persist_definition_caches_across_batch_runs = True
        BatchJob(args).run()
        assert "batch_persist_fn" in FilenameMappingDefinition.NAMED_FUNCTIONS
    finally:
        BatchArgs.configs = prev_configs
        FilenameMappingDefinition.reset_registration_state()
        FiletypesDefinition.reset_registration_state()
