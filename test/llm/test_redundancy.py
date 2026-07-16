"""
Unit tests for ``refacdir/llm/redundancy.py``.

Covers ``is_similar_strings`` (the local replacement for the ported project's
``Utils.is_similar_strings``, which doesn't exist in this repo) and the
thinking-block / redundancy-detection helpers used by the LLM client.
"""

from refacdir.llm.redundancy import (
    DefaultRedundancyPolicy,
    RedundancyVerdict,
    is_similar_strings,
    strip_thinking_blocks,
    streaming_visible_response,
    thinking_chars_in_progress,
    truncate_duplicate_paragraph,
    visible_text_for_policy,
)


class _Chunk:
    """Minimal stand-in for refacdir.llm.client.StreamChunk (avoids import coupling)."""

    def __init__(self, text: str, accumulated: str, done: bool = False):
        self.text = text
        self.accumulated = accumulated
        self.done = done


# ---------------------------------------------------------------------------
# is_similar_strings
# ---------------------------------------------------------------------------

def test_is_similar_strings_exact_match():
    assert is_similar_strings("response", "response") is True


def test_is_similar_strings_case_and_whitespace_insensitive():
    assert is_similar_strings("  Response ", "response") is True


def test_is_similar_strings_catches_close_typo():
    assert is_similar_strings("response", "resposne") is True


def test_is_similar_strings_rejects_dissimilar():
    assert is_similar_strings("response", "totally_different_key") is False


def test_is_similar_strings_empty_strings_not_similar_to_nonempty():
    assert is_similar_strings("", "response") is False
    assert is_similar_strings("response", "") is False


# ---------------------------------------------------------------------------
# thinking-block helpers
# ---------------------------------------------------------------------------

def test_strip_thinking_blocks_leading_block():
    text = "<think>internal monologue</think>final answer"
    assert strip_thinking_blocks(text) == "final answer"


def test_strip_thinking_blocks_no_tags_unchanged():
    assert strip_thinking_blocks("just a plain response") == "just a plain response"


def test_thinking_chars_in_progress_open_block():
    accumulated = "<think>partial thoughts so far"
    assert thinking_chars_in_progress(accumulated) == len("partial thoughts so far")


def test_thinking_chars_in_progress_closed_block_is_zero():
    accumulated = "<think>thoughts</think>answer"
    assert thinking_chars_in_progress(accumulated) == 0


def test_thinking_chars_in_progress_no_tags_is_zero():
    assert thinking_chars_in_progress("no tags here") == 0


def test_visible_text_for_policy_hides_open_thinking_block():
    assert visible_text_for_policy("<think>still thinking") == ""


def test_visible_text_for_policy_shows_text_after_closed_block():
    assert visible_text_for_policy("<think>thoughts</think>the answer") == "the answer"


def test_streaming_visible_response_strips_thinking():
    assert streaming_visible_response("<think>t</think>answer") == "answer"


def test_truncate_duplicate_paragraph_drops_repeat():
    text = "first paragraph\n\nfirst paragraph"
    assert truncate_duplicate_paragraph(text) == "first paragraph"


def test_truncate_duplicate_paragraph_no_repeat_unchanged():
    text = "first paragraph\n\nsecond paragraph"
    assert truncate_duplicate_paragraph(text) == text


# ---------------------------------------------------------------------------
# DefaultRedundancyPolicy
# ---------------------------------------------------------------------------

def test_redundancy_policy_no_stop_below_min_length():
    policy = DefaultRedundancyPolicy(min_length=200)
    verdict = policy.on_chunk(_Chunk(text="hi", accumulated="hi"))
    assert verdict.should_stop is False


def test_redundancy_policy_thinking_budget_exceeded():
    policy = DefaultRedundancyPolicy(thinking_budget_chars=10)
    accumulated = "<think>" + ("x" * 20)
    verdict = policy.on_chunk(_Chunk(text="x", accumulated=accumulated))
    assert verdict.should_stop is True
    assert verdict.reason == "thinking_budget_exceeded"


def test_redundancy_policy_detects_identical_delta_stall():
    policy = DefaultRedundancyPolicy(min_length=5, stall_limit=3)
    long_prefix = "a" * 20
    verdict = None
    for _ in range(3):
        long_prefix += "loop"
        verdict = policy.on_chunk(_Chunk(text="loop", accumulated=long_prefix))
    assert verdict.should_stop is True
    assert verdict.reason == "token_stall"


def test_redundancy_policy_detects_repeated_paragraph():
    policy = DefaultRedundancyPolicy(min_length=5, min_paragraph_length=5)
    paragraph = "x" * 50
    accumulated = f"{paragraph}\n\n{paragraph}"
    verdict = policy.on_chunk(_Chunk(text=paragraph, accumulated=accumulated))
    assert verdict.should_stop is True
    assert verdict.reason == "repeated_paragraph"
    assert verdict.truncate_to == paragraph
