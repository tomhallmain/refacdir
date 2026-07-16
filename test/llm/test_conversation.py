"""
Tests for refacdir/llm/conversation.py — the Phase 3 headless draft/validate/
retry conversation loop (docs/LLM_CONFIG_CHAT_SCOPE.md).

Uses a FakeLLM stub (queued canned responses) rather than a real Ollama
instance, so the retry mechanics are exercised deterministically in CI —
checking real-model convergence is what conversation.py's own ``__main__``
script is for instead (see its docstring).
"""

import json

import pytest

from refacdir.batch import ActionType
from refacdir.llm.client import LLMResponseException
from refacdir.llm.conversation import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    draft_action,
)

_NONEXISTENT_PATH = "/definitely/does/not/exist/anywhere/refacdir-llm-tests"


class _FakeResult:
    def __init__(self, response):
        self.response = response


class FakeLLM:
    """Stub matching the slice of LLM.generate_response's interface conversation.py uses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.queries = []
        self.system_prompts = []

    def generate_response(self, query, system_prompt=None, **kwargs):
        self.queries.append(query)
        self.system_prompts.append(system_prompt)
        if not self._responses:
            raise LLMResponseException("FakeLLM exhausted its canned responses")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return _FakeResult(next_response)


def _valid_renamer_json():
    return json.dumps({
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    })


def _renamer_json_missing_rename_tag():
    return json.dumps({
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
    })


def test_draft_action_succeeds_on_first_attempt():
    llm = FakeLLM([_valid_renamer_json()])
    result = draft_action("rename my text files", ActionType.RENAMER, llm)
    assert result.success is True
    assert result.attempt_count == 1
    assert result.action_dict["name"] == "Test renamer"
    assert result.warnings == []


def test_draft_action_retries_after_malformed_json_then_succeeds():
    llm = FakeLLM(["not json at all", _valid_renamer_json()])
    result = draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=3)
    assert result.success is True
    assert result.attempt_count == 2
    assert result.attempts[0].parse_error is not None
    assert result.attempts[1].parsed is not None


def test_draft_action_retries_after_validation_error_then_succeeds():
    llm = FakeLLM([_renamer_json_missing_rename_tag(), _valid_renamer_json()])
    result = draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=3)
    assert result.success is True
    assert result.attempt_count == 2
    assert result.attempts[0].validation.valid is False
    assert "rename_tag" in result.attempts[0].validation.error_summary()


def test_draft_action_gives_up_after_exhausting_max_attempts():
    llm = FakeLLM(["still not json", "also not json", "nope"])
    result = draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=3)
    assert result.success is False
    assert result.attempt_count == 3
    assert result.action_dict is None
    assert "no json object found" in result.last_error_summary().lower()


def test_draft_action_strips_markdown_code_fences():
    fenced = "```json\n" + _valid_renamer_json() + "\n```"
    llm = FakeLLM([fenced])
    result = draft_action("rename my text files", ActionType.RENAMER, llm)
    assert result.success is True


def test_draft_action_surfaces_warnings_without_treating_them_as_failure():
    # DIRECTORY_OBSERVER's extra_dirs check is eager; a nonexistent path is a
    # warning (see refacdir/llm/validation.py), not a validation failure — the
    # first attempt should succeed immediately, not retry.
    observer_json = json.dumps({"name": "Test observer", "extra_dirs": [_NONEXISTENT_PATH]})
    llm = FakeLLM([observer_json])
    result = draft_action("watch this folder", ActionType.DIRECTORY_OBSERVER, llm)
    assert result.success is True
    assert result.attempt_count == 1
    assert len(result.warnings) == 1


def test_draft_action_recovers_from_llm_response_exception():
    llm = FakeLLM([LLMResponseException("transient network error"), _valid_renamer_json()])
    result = draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=3)
    assert result.success is True
    assert result.attempt_count == 2
    assert result.attempts[0].parse_error == "transient network error"


def test_draft_action_raises_for_image_categorizer_without_calling_llm():
    llm = FakeLLM([])
    with pytest.raises(ValueError):
        draft_action("categorize my images", ActionType.IMAGE_CATEGORIZER, llm)
    assert llm.queries == []


def test_draft_action_rejects_unsupported_language():
    llm = FakeLLM([])
    with pytest.raises(ValueError):
        draft_action("rename my text files", ActionType.RENAMER, llm, language="French")
    assert llm.queries == []


def test_draft_action_rejects_non_positive_max_attempts():
    llm = FakeLLM([])
    with pytest.raises(ValueError):
        draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=0)


def test_default_language_is_english_and_is_supported():
    assert DEFAULT_LANGUAGE == "English"
    assert DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES


def test_system_prompt_mentions_language_and_schema():
    llm = FakeLLM([_valid_renamer_json()])
    draft_action("rename my text files", ActionType.RENAMER, llm)
    assert "English" in llm.system_prompts[0]
    assert "search_patterns" in llm.system_prompts[0]


def test_draft_action_forces_safety_defaults_onto_successful_draft():
    """Phase 4: a successful draft's action_dict must already carry the forced
    safety field, regardless of what the model's JSON said — see
    refacdir/llm/safety.py."""
    action_dict_without_test_field = json.dumps({
        "name": "Test renamer",
        "function": "rename_by_ctime",
        "mappings": [{"search_patterns": "*.txt", "rename_tag": "renamed_"}],
        "locations": [{"root": _NONEXISTENT_PATH}],
        "test": False,
    })
    llm = FakeLLM([action_dict_without_test_field])
    result = draft_action("rename my text files", ActionType.RENAMER, llm)
    assert result.success is True
    assert result.action_dict["test"] is True


def test_draft_action_forces_skip_confirm_false_for_duplicate_remover():
    dedup_json = json.dumps({
        "name": "Test dedup",
        "source_dirs": [_NONEXISTENT_PATH],
        "skip_confirm": True,
    })
    llm = FakeLLM([dedup_json])
    result = draft_action("remove duplicates", ActionType.DUPLICATE_REMOVER, llm)
    assert result.success is True
    assert result.action_dict["skip_confirm"] is False


def test_retry_prompt_feeds_previous_error_back_to_llm():
    llm = FakeLLM([_renamer_json_missing_rename_tag(), _valid_renamer_json()])
    draft_action("rename my text files", ActionType.RENAMER, llm, max_attempts=3)
    assert "rename_tag" in llm.queries[1]
