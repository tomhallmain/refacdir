"""
Shared fixtures for renamer tests.

Reserve ``FileRenamer(test=True)`` / ``BatchRenamer(test=True)`` / YAML ``test: true``
only for assertions about *user* dry-run behavior (no ``os.rename``). For other tests,
use ``test=False`` (the default) so the flag is not confused with pytest.
"""
import os

# Before any refacdir import: ``batch`` pulls in ``encryptor`` / optional oqs.
os.environ.setdefault("REFACDIR_DISABLE_APP_INFO_CACHE_LOAD", "1")

import pytest

from refacdir.batch import BatchArgs
from refacdir.filename_ops import FilenameMappingDefinition


@pytest.fixture
def restore_batch_configs():
    """Restore ``BatchArgs.configs`` after tests that call ``override_configs``."""
    prev = dict(BatchArgs.configs)
    yield
    BatchArgs.configs = prev


@pytest.fixture
def restore_filename_mapping_registry():
    """Isolate ``FilenameMappingDefinition.NAMED_FUNCTIONS`` from other tests."""
    prev = FilenameMappingDefinition.NAMED_FUNCTIONS.copy()
    yield
    FilenameMappingDefinition.NAMED_FUNCTIONS.clear()
    FilenameMappingDefinition.NAMED_FUNCTIONS.update(prev)
