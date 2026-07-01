"""Directory observer test fixtures.

Cache/config isolation: see root ``test/conftest.py``.

``DirData.file_types`` is class-level state shared across observer instances.
"""
import pytest

from refacdir.directory_observer import DirData


@pytest.fixture(autouse=True)
def restore_dirdata_file_types():
    prev = list(DirData.file_types)
    yield
    DirData.file_types.clear()
    DirData.file_types.extend(prev)
