"""LocalizedText: English as a str, translated through localized()/localized_str."""

from __future__ import annotations

import copy
import pickle

import pytest

from refacdir.utils.translations import I18N, LocalizedText, as_localized_text, localized_str

_CATALOG = {"Invalid directory provided: {0}": "Ungültiges Verzeichnis: {0}"}


@pytest.fixture
def german(monkeypatch):
    monkeypatch.setattr(I18N, "_", staticmethod(lambda text: _CATALOG.get(text, text)))


def test_str_operations_see_the_english_text(german):
    text = LocalizedText("Invalid directory provided: {0}", "/x")

    assert text == "Invalid directory provided: /x"
    assert "Invalid directory provided" in text
    assert str(Exception(text)) == "Invalid directory provided: /x"
    assert f"{Exception(text)}" == "Invalid directory provided: /x"


def test_localized_translates_the_template_at_call_time(german):
    text = LocalizedText("Invalid directory provided: {0}", "/x")

    assert text.localized() == "Ungültiges Verzeichnis: /x"
    assert localized_str(text) == "Ungültiges Verzeichnis: /x"
    assert localized_str(Exception(text)) == "Ungültiges Verzeichnis: /x"


def test_text_without_arguments_is_not_formatted():
    assert LocalizedText("keep {{braces}}") == "keep {{braces}}"
    assert LocalizedText("keep {{braces}}").localized() == "keep {{braces}}"


def test_other_values_fall_back_to_str():
    assert localized_str(ValueError("plain")) == "plain"
    assert localized_str(KeyError("name")) == "'name'"
    assert as_localized_text(ValueError("plain")) == "plain"


def test_pickle_and_copy_keep_the_template(german):
    text = LocalizedText("Invalid directory provided: {0}", "/x")

    for clone in (pickle.loads(pickle.dumps(text)), copy.deepcopy(text)):
        assert clone == text
        assert clone.localized() == "Ungültiges Verzeichnis: /x"
    restored = pickle.loads(pickle.dumps(Exception(text)))
    assert localized_str(restored) == "Ungültiges Verzeichnis: /x"


def test_validation_keeps_english_for_the_prompt_and_translates_for_display(german, tmp_path):
    from refacdir.batch import ActionType
    from refacdir.llm.validation import ValidationResult

    missing = str(tmp_path / "missing")
    result = ValidationResult(
        action_type=ActionType.DIRECTORY_OBSERVER,
        valid=False,
        errors=[LocalizedText("Invalid directory provided: {0}", missing)],
    )

    assert result.error_summary() == f"Invalid directory provided: {missing}"
    assert result.localized_error_summary() == f"Ungültiges Verzeichnis: {missing}"
