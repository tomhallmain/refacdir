"""The user's own search functions file: seeding, loading, lookup order, failures.

The file lives in the per-test configs dir that ``isolated_app_singletons`` sets.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from refacdir import search_funcs, user_search_funcs
from refacdir.filename_ops import FilenameMappingDefinition


def _write_user_file(source: str) -> str:
    path = user_search_funcs.user_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(source))
    return path


class _Alerts:
    def __init__(self):
        self.alerts = []

    def alert(self, title, message, kind="info"):
        self.alerts.append((title, message, kind))


def test_missing_file_is_created_from_the_template():
    path = user_search_funcs.user_file_path()
    assert not os.path.exists(path)

    user_search_funcs.reload()

    with open(path, encoding="utf-8") as handle, open(
        user_search_funcs.TEMPLATE_PATH, encoding="utf-8"
    ) as template:
        assert handle.read() == template.read()
    assert user_search_funcs.load_error() is None


def test_existing_file_is_not_overwritten():
    path = _write_user_file("def mine(filename):\n    return True\n")
    user_search_funcs.reload()
    with open(path, encoding="utf-8") as handle:
        assert "def mine" in handle.read()


def test_public_functions_defined_in_the_file_are_found():
    _write_user_file(
        """
        import os
        from os.path import basename

        def is_draft(filename):
            return filename.endswith("_draft")

        def _helper(filename):
            return True
        """
    )
    user_search_funcs.reload()

    assert user_search_funcs.find("is_draft")("a_draft") is True
    assert user_search_funcs.find("_helper") is None
    assert user_search_funcs.find("basename") is None  # imported, not defined here


def test_edits_apply_on_reload():
    _write_user_file("def flag(filename):\n    return True\n")
    user_search_funcs.reload()
    assert user_search_funcs.find("flag")("x") is True

    _write_user_file("def flag(filename):\n    return False\n")
    user_search_funcs.reload()
    assert user_search_funcs.find("flag")("x") is False


def test_lookup_order_user_file_then_builtins():
    _write_user_file("def any_file(filename):\n    return False\n")
    user_search_funcs.reload()

    assert FilenameMappingDefinition.compiled("{{any_file}}")("x.txt") is False
    assert FilenameMappingDefinition.compiled("{{random_selection}}") is search_funcs.random_selection


def test_yaml_named_function_wins_over_the_user_file():
    _write_user_file("def four_digits(filename):\n    return True\n")
    user_search_funcs.reload()
    FilenameMappingDefinition.add_named_functions(
        [{"name": "four_digits", "type": "DIGITS", "args": [4]}]
    )
    try:
        assert FilenameMappingDefinition.compiled("{{four_digits}}") == "[0-9][0-9][0-9][0-9]"
    finally:
        FilenameMappingDefinition.reset_registration_state()


def test_builtin_lookup_skips_helpers_and_imports():
    assert user_search_funcs.builtin("is_id") is search_funcs.is_id
    assert user_search_funcs.builtin("_get_runs") is None
    assert user_search_funcs.builtin("Counter") is None
    assert user_search_funcs.builtin("re") is None


def test_broken_file_falls_back_to_builtins_and_reports_once():
    path = _write_user_file("def broken(:\n")
    alerts = _Alerts()

    user_search_funcs.reload(alerts)

    assert path in user_search_funcs.load_error()
    assert len(alerts.alerts) == 1
    assert user_search_funcs.find("broken") is None
    assert FilenameMappingDefinition.compiled("{{any_file}}") is search_funcs.any_file


def test_unknown_name_error_names_the_user_file_and_its_load_error():
    _write_user_file("raise RuntimeError('bad import')\n")
    user_search_funcs.reload()

    with pytest.raises(Exception) as excinfo:
        FilenameMappingDefinition.compiled("{{only_in_user_file}}")
    message = str(excinfo.value)
    assert user_search_funcs.user_file_path() in message
    assert "bad import" in message


def test_configs_dir_change_reloads(tmp_path, monkeypatch):
    _write_user_file("def first(filename):\n    return True\n")
    user_search_funcs.reload()
    assert user_search_funcs.find("first") is not None

    other = tmp_path / "other_configs"
    other.mkdir()
    monkeypatch.setenv("REFACDIR_CONFIGS_DIR", str(other))
    assert user_search_funcs.find("first") is None
