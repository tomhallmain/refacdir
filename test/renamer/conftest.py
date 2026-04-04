"""
Shared fixtures for renamer tests.

Note: ``FileRenamer(test=True)`` and ``BatchRenamer(test=True)`` mean the *user*
dry-run mode (no ``os.rename``), not pytest. Prefer the term "dry-run" in docstrings.
"""
import pytest

from refacdir.filename_ops import FilenameMappingDefinition


@pytest.fixture
def restore_filename_mapping_registry():
    """Isolate ``FilenameMappingDefinition.NAMED_FUNCTIONS`` from other tests."""
    prev = FilenameMappingDefinition.NAMED_FUNCTIONS.copy()
    yield
    FilenameMappingDefinition.NAMED_FUNCTIONS.clear()
    FilenameMappingDefinition.NAMED_FUNCTIONS.update(prev)
