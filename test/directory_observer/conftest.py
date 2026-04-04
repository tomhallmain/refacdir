"""``DirData.file_types`` is class state; restore it after each test."""
import pytest

from refacdir.directory_observer import DirData


@pytest.fixture(autouse=True)
def restore_dirdata_file_types():
    prev = list(DirData.file_types)
    yield
    DirData.file_types.clear()
    DirData.file_types.extend(prev)
