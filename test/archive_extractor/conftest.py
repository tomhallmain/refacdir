"""Archive extractor tests never reach the OS trash.

``delete_sources`` defaults to True, so every live run trashes the archives it
fully extracted through ``send2trash``. The stub records each path instead and
leaves the file in place.
"""

import pytest


@pytest.fixture(autouse=True)
def removed_archives(monkeypatch):
    """Paths the extractor asked to remove, in order."""
    removed = []
    monkeypatch.setattr(
        "refacdir.archive_extractor.remove_file",
        lambda path: removed.append(path) or True,
    )
    return removed
