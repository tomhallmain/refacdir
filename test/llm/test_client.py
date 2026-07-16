"""
Unit tests for ``refacdir/llm/client.py``.

Network calls (``urllib.request.urlopen``) are mocked throughout — no real
Ollama server is required, and none of these should ever depend on one.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from refacdir.llm.client import (
    LLM,
    LLMResponseException,
    LLMResult,
    accumulate_ollama_stream_events,
)


@pytest.fixture(autouse=True)
def reset_failure_counts():
    """LLM._failure_counts is class-level state shared across tests."""
    LLM._failure_counts.clear()
    yield
    LLM._failure_counts.clear()


# ---------------------------------------------------------------------------
# LLMResult
# ---------------------------------------------------------------------------

def test_llm_result_validate_rejects_empty_response():
    result = LLMResult.from_json({"response": "   "})
    assert result.validate() is False


def test_llm_result_validate_accepts_nonempty_response():
    result = LLMResult.from_json({"response": "hello"})
    assert result.validate() is True


def test_get_json_attr_exact_key():
    result = LLMResult.from_json({"response": '{"search_patterns": "*.txt"}'})
    got = result._get_json_attr("search_patterns")
    assert got is not None
    assert got.response == "*.txt"


def test_get_json_attr_fuzzy_key_match():
    """A near-miss key (typo) should still resolve via is_similar_strings."""
    result = LLMResult.from_json({"response": '{"serach_patterns": "*.txt"}'})
    got = result._get_json_attr("search_patterns")
    assert got is not None
    assert got.response == "*.txt"


def test_get_json_attr_strips_markdown_fence_and_json_prefix():
    result = LLMResult.from_json({"response": '```json\n{"rename_tag": "foo_"}\n```'})
    got = result._get_json_attr("rename_tag")
    assert got is not None
    assert got.response == "foo_"


def test_get_json_attr_returns_none_on_malformed_json():
    result = LLMResult.from_json({"response": "not json at all"})
    assert result._get_json_attr("anything") is None


# ---------------------------------------------------------------------------
# accumulate_ollama_stream_events
# ---------------------------------------------------------------------------

def test_accumulate_ollama_stream_events_concatenates_deltas():
    lines = [
        json.dumps({"response": "Hello "}).encode(),
        json.dumps({"response": "world"}).encode(),
        json.dumps({"response": "", "done": True, "done_reason": "stop"}).encode(),
    ]
    text, final = accumulate_ollama_stream_events(iter(lines))
    assert text == "Hello world"
    assert final["done_reason"] == "stop"


def test_accumulate_ollama_stream_events_skips_blank_lines():
    lines = [b"", json.dumps({"response": "hi", "done": True}).encode(), b"  "]
    text, final = accumulate_ollama_stream_events(iter(lines))
    assert text == "hi"
    assert final["done"] is True


# ---------------------------------------------------------------------------
# History file path resolution (see docs/LLM_CONFIG_CHAT_SCOPE.md Phase 0 —
# must not depend on os.getcwd() at write time).
# ---------------------------------------------------------------------------

def test_history_file_path_respects_cache_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    llm = LLM(state_key="unit-test")
    assert llm.prompt_response_history_file == str(tmp_path / "llm_prompt_response_history_unit-test.json")


def test_history_file_path_falls_back_to_stable_absolute_default(monkeypatch):
    monkeypatch.delenv("REFACDIR_CACHE_DIR", raising=False)
    llm = LLM(state_key="unit-test")
    assert os.path.isabs(llm.prompt_response_history_file)
    assert "unit-test" in llm.prompt_response_history_file


def test_history_file_path_sanitizes_state_key(monkeypatch, tmp_path):
    monkeypatch.setenv("REFACDIR_CACHE_DIR", str(tmp_path))
    llm = LLM(state_key="weird key/with:chars")
    expected = tmp_path / "llm_prompt_response_history_weird_key_with_chars.json"
    assert llm.prompt_response_history_file == str(expected)


# ---------------------------------------------------------------------------
# Failure-count circuit breaker
# ---------------------------------------------------------------------------

def test_failure_count_increments_and_resets():
    llm = LLM(state_key="breaker-test")
    assert llm.get_failure_count() == 0
    assert llm.is_failing() is False

    for _ in range(LLM.FAILURE_THRESHOLD):
        llm.increment_failure_count()
    assert llm.is_failing() is True

    llm.reset_failure_count()
    assert llm.get_failure_count() == 0
    assert llm.is_failing() is False


def test_failure_counts_are_independent_per_state_key():
    llm_a = LLM(state_key="state-a")
    llm_b = LLM(state_key="state-b")
    for _ in range(LLM.FAILURE_THRESHOLD):
        llm_a.increment_failure_count()
    assert llm_a.is_failing() is True
    assert llm_b.is_failing() is False


# ---------------------------------------------------------------------------
# Thinking-model detection / timeout extension
# ---------------------------------------------------------------------------

def test_is_thinking_model_matches_known_prefixes():
    assert LLM(model_name="deepseek-r1:14b")._is_thinking_model() is True
    assert LLM(model_name="Qwen3:8b")._is_thinking_model() is True


def test_is_thinking_model_false_for_other_models():
    assert LLM(model_name="llama3.1:8b")._is_thinking_model() is False


def test_get_timeout_extends_for_thinking_models():
    llm = LLM(model_name="deepseek-r1:14b")
    assert llm._get_timeout(60) == 300
    assert llm._get_timeout(400) == 400


def test_get_timeout_unchanged_for_non_thinking_models():
    llm = LLM(model_name="llama3.1:8b")
    assert llm._get_timeout(60) == 60


# ---------------------------------------------------------------------------
# _clean_response_for_models — regression guard: no more CJK rejection
# ---------------------------------------------------------------------------

def test_clean_response_strips_thinking_and_final_answer_prefix():
    llm = LLM()
    cleaned = llm._clean_response_for_models("<think>reasoning</think>Final Answer: the config")
    assert cleaned == "the config"


def test_clean_response_no_longer_rejects_cjk_content():
    """Regression guard: the ported CJK-rejection rule (TTS-specific, unrelated
    to config generation) must not resurface."""
    llm = LLM()
    cjk_text = "設定ファイルのパスは正しいです"
    assert llm._clean_response_for_models(cjk_text) == cjk_text


# ---------------------------------------------------------------------------
# System prompt drop rate — deterministic at both boundaries
# ---------------------------------------------------------------------------

def test_system_prompt_always_included_at_zero_drop_rate():
    llm = LLM()
    for _ in range(20):
        data, included = llm._build_generate_payload(
            "query", stream=False, system_prompt="sys", system_prompt_drop_rate=0.0
        )
        assert included is True
        assert data["system"] == "sys"


def test_system_prompt_always_dropped_at_full_drop_rate():
    llm = LLM()
    for _ in range(20):
        data, included = llm._build_generate_payload(
            "query", stream=False, system_prompt="sys", system_prompt_drop_rate=1.0
        )
        assert included is False
        assert "system" not in data


def test_default_drop_rate_is_zero():
    assert LLM.DEFAULT_SYSTEM_PROMPT_DROP_RATE == 0.0


# ---------------------------------------------------------------------------
# Endpoint override
# ---------------------------------------------------------------------------

def test_endpoint_defaults_to_class_constant():
    assert LLM().endpoint == LLM.ENDPOINT


def test_endpoint_can_be_overridden():
    llm = LLM(endpoint="http://example.internal:11434/api/generate")
    assert llm.endpoint == "http://example.internal:11434/api/generate"
    req = llm._make_generate_request({"model": "x", "prompt": "y", "stream": False})
    assert req.full_url == "http://example.internal:11434/api/generate"


# ---------------------------------------------------------------------------
# from_config no longer silently imports a nonexistent module
# ---------------------------------------------------------------------------

def test_from_config_requires_explicit_config_obj():
    with pytest.raises(TypeError):
        LLM.from_config()  # config_obj is now a required positional argument


def test_from_config_reads_expected_attributes():
    class FakeConfig:
        llm_model_name = "llama3.1:8b"
        llm_use_streaming = True
        llm_stream_redundancy = False
        llm_thinking_budget_chars = 500
        llm_track_prompts_and_responses = False

    llm = LLM.from_config(FakeConfig())
    assert llm.model_name == "llama3.1:8b"
    assert llm.use_streaming is True
    assert llm.thinking_budget_chars == 500


# ---------------------------------------------------------------------------
# generate_response (buffered) with urlopen mocked — no real Ollama dependency
# ---------------------------------------------------------------------------

def test_generate_response_buffered_returns_parsed_result():
    llm = LLM(state_key="buffered-test")
    fake_response_body = json.dumps({"response": "hello world", "done": True}).encode("utf-8")

    fake_http_response = MagicMock()
    fake_http_response.read.return_value = fake_response_body

    with patch("refacdir.llm.client.request.urlopen", return_value=fake_http_response):
        result = llm.generate_response("say hi", stream=False)

    assert result.response == "hello world"
    assert llm.get_failure_count() == 0


def test_generate_response_buffered_raises_on_empty_response():
    llm = LLM(state_key="buffered-empty-test")
    fake_response_body = json.dumps({"response": "", "done": True}).encode("utf-8")

    fake_http_response = MagicMock()
    fake_http_response.read.return_value = fake_response_body

    with patch("refacdir.llm.client.request.urlopen", return_value=fake_http_response):
        with pytest.raises(LLMResponseException):
            llm.generate_response("say nothing", stream=False)


def test_generate_response_increments_failure_count_on_network_error():
    llm = LLM(state_key="network-error-test")
    with patch("refacdir.llm.client.request.urlopen", side_effect=OSError("connection refused")):
        with pytest.raises(LLMResponseException):
            llm.generate_response("say hi", stream=False)
    assert llm.get_failure_count() == 1
