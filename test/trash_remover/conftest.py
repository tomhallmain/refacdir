"""Trash remover tests never reach the real OS trash.

``send2trash`` is replaced by a stub that records the path and deletes it,
and the system trash is pointed at a freedesktop layout under ``tmp_path``
(``XDG_DATA_HOME``) on every platform, so the Windows recycle bin and a real
``~/.local/share/Trash`` or ``~/.Trash`` are never touched.
"""

import os
import shutil

import pytest


@pytest.fixture(autouse=True)
def trashed_paths(monkeypatch):
    """Paths the remover sent to the system trash, in order."""
    trashed = []

    def fake_send_to_trash(path):
        trashed.append(path)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    monkeypatch.setattr("refacdir.trash_remover._send_to_trash", fake_send_to_trash)
    return trashed


@pytest.fixture(autouse=True)
def fake_system_trash(monkeypatch, tmp_path):
    """A freedesktop trash under tmp_path; returns its ``Trash`` directory."""
    data_home = tmp_path / "xdg_data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr("refacdir.trash_remover._system_trash_platform", lambda: "freedesktop")
    return data_home / "Trash"
