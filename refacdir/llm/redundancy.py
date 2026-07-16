"""
Pluggable redundancy detection for streaming LLM responses.

Used by :class:`refacdir.llm.client.LLM` to stop generation early when the model
begins repeating itself. Adapted from a ported voice-assistant project's
``llm_redundancy.py`` — kept available (and off by default) since a chatty local
model can still benefit from it, but not wired into any refacdir feature by
default. See docs/LLM_CONFIG_CHAT_SCOPE.md.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Tuple, runtime_checkable

# Type alias for optional host-project string similarity.
SimilarityFn = Callable[[str, str], bool]


def is_similar_strings(a: str, b: str, threshold: float = 0.8) -> bool:
    """
    Simple case/whitespace-insensitive similarity check.

    A local, dependency-free replacement for the ported project's
    ``Utils.is_similar_strings`` (not available in refacdir). Deliberately
    simpler than the original — exact match after normalizing case/whitespace,
    else a ``difflib`` ratio above ``threshold``.
    """
    norm_a = a.strip().lower()
    norm_b = b.strip().lower()
    if norm_a == norm_b:
        return True
    if not norm_a or not norm_b:
        return False
    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio() >= threshold


@dataclass
class RedundancyVerdict:
    """Result of evaluating one streaming chunk."""
    should_stop: bool
    reason: str = ""
    truncate_to: Optional[str] = None  # when set, replaces accumulated text at stop


@runtime_checkable
class RedundancyPolicy(Protocol):
    """Evaluate streaming output; return ``should_stop=True`` to end generation."""

    def on_chunk(self, chunk) -> RedundancyVerdict:
        """*chunk* is a :class:`refacdir.llm.client.StreamChunk`."""
        ...


# Known thinking wrapper tag names (most common first).
THINKING_TAG_NAMES: Tuple[str, ...] = ("think", "redacted_thinking")

def thinking_tag_pairs() -> List[Tuple[str, str]]:
    """Return ``(open, close)`` tag pairs for all supported thinking wrappers."""
    return [("<" + name + ">", "</" + name + ">") for name in THINKING_TAG_NAMES]


# Primary tag pair — ``think`` is what DeepSeek-R1, Qwen3, etc. emit in practice.
THINKING_OPEN_TAG, THINKING_CLOSE_TAG = thinking_tag_pairs()[0]


def thinking_chars_in_progress(accumulated: str) -> int:
    """Return the number of chars accumulated inside an open (unclosed) thinking block.

    Returns 0 when no thinking block is open or when the accumulated text contains
    no thinking tags at all.
    """
    for open_tag, close_tag in thinking_tag_pairs():
        if open_tag not in accumulated:
            continue
        last_open = accumulated.rfind(open_tag)
        last_close = accumulated.rfind(close_tag)
        if last_close < last_open:
            return len(accumulated) - (last_open + len(open_tag))
    return 0


def visible_text_for_policy(accumulated: str) -> str:
    """Text visible for redundancy checks (skips in-progress thinking blocks).

    When a thinking block is open, returns an empty string so internal monologue
    does not trigger false stops. Supports multiple tag spellings (``think``,
    ``redacted_thinking``, …).
    """
    text = accumulated
    for open_tag, close_tag in thinking_tag_pairs():
        if open_tag not in text:
            continue
        last_open = text.rfind(open_tag)
        last_close = text.rfind(close_tag)
        if last_close < last_open:
            return ""
        if last_close >= 0:
            return text[last_close + len(close_tag) :].strip()
    return text


def strip_thinking_blocks(text: str) -> str:
    """Remove thinking wrappers from *text* (``think``, ``redacted_thinking``, …)."""
    for open_tag, close_tag in thinking_tag_pairs():
        if text.strip().startswith(open_tag) and close_tag in text:
            text = text[text.rfind(close_tag) + len(close_tag) :].strip()
    for open_tag, close_tag in thinking_tag_pairs():
        if open_tag in text:
            text = text.replace(open_tag, "").replace(close_tag, "").strip()
    return text


def streaming_visible_response(accumulated: str) -> str:
    """Answer text exposed during streaming (thinking blocks excluded)."""
    visible = visible_text_for_policy(accumulated)
    if not visible:
        return ""
    return strip_thinking_blocks(visible)


def truncate_duplicate_paragraph(text: str) -> str:
    """Drop the final paragraph when it duplicates an earlier one."""
    parts = text.split("\n\n")
    if len(parts) < 2:
        return text.rstrip()
    last = parts[-1].strip()
    if not last:
        return "\n\n".join(parts[:-1]).rstrip()
    for earlier in parts[:-1]:
        if earlier.strip() == last:
            return "\n\n".join(parts[:-1]).rstrip()
    return text.rstrip()


def _default_similarity(a: str, b: str) -> bool:
    return is_similar_strings(a, b)


class DefaultRedundancyPolicy:
    """Generic repetition detector for streaming LLM output.

  Strategies (in order):
    1. Identical delta stall — same non-empty chunk text repeated *stall_limit* times.
    2. Exact paragraph repeat — final ``\\n\\n`` block matches an earlier block.
    3. Rolling similarity — final paragraph similar to an earlier one beyond tier limits.
    """

    MIN_SIMILARITY_LENGTH = 20
    REDUNDANCY_TIERS: List[Tuple[int, int]] = [
        (300, 1),
        (100, 2),
        (50, 3),
    ]

    def __init__(
        self,
        min_length: int = 200,
        min_paragraph_length: int = 40,
        stall_limit: int = 3,
        similarity_fn: Optional[SimilarityFn] = None,
        thinking_budget_chars: Optional[int] = 8_000,
    ) -> None:
        self.min_length = min_length
        self.min_paragraph_length = min_paragraph_length
        self.stall_limit = stall_limit
        self._similarity = similarity_fn or _default_similarity
        self.thinking_budget_chars = thinking_budget_chars
        self._stall_text: Optional[str] = None
        self._stall_count = 0
        self._similar_counts: dict = {}

    def _tier_limit(self, length: int) -> int:
        for threshold, limit in self.REDUNDANCY_TIERS:
            if length < threshold:
                return limit
        return 0

    def _paragraphs(self, text: str) -> List[str]:
        return [p.strip() for p in text.split("\n\n") if p.strip()]

    def on_chunk(self, chunk) -> RedundancyVerdict:
        # ── Thinking-block budget ───────────────────────────────────────
        # Checked before the visible-text guard so it fires even when the
        # thinking block is still open (visible would be "" in that case).
        if self.thinking_budget_chars is not None:
            in_progress = thinking_chars_in_progress(chunk.accumulated)
            if in_progress > self.thinking_budget_chars:
                return RedundancyVerdict(
                    True,
                    reason="thinking_budget_exceeded",
                    truncate_to="",
                )

        visible = visible_text_for_policy(chunk.accumulated)
        if not visible or len(visible) < self.min_length:
            return RedundancyVerdict(False)

        # ── Stall: identical deltas ─────────────────────────────────────
        delta = chunk.text
        if delta:
            if delta == self._stall_text:
                self._stall_count += 1
            else:
                self._stall_text = delta
                self._stall_count = 1
            if self._stall_count >= self.stall_limit and len(delta.strip()) >= 4:
                trimmed = visible
                excess = delta * (self._stall_count - 1)
                if excess and trimmed.endswith(excess):
                    trimmed = trimmed[: -len(excess)].rstrip()
                return RedundancyVerdict(
                    True,
                    reason="token_stall",
                    truncate_to=trimmed,
                )

        # ── Paragraph-level checks ──────────────────────────────────────
        paragraphs = self._paragraphs(visible)
        if len(paragraphs) < 2:
            return RedundancyVerdict(False)

        last = paragraphs[-1]
        if len(last) < self.min_paragraph_length:
            return RedundancyVerdict(False)

        # Exact duplicate paragraph
        for earlier in paragraphs[:-1]:
            if earlier == last:
                return RedundancyVerdict(
                    True,
                    reason="repeated_paragraph",
                    truncate_to=truncate_duplicate_paragraph(visible),
                )

        # Similar paragraph (tiered allowance)
        if len(last) >= self.MIN_SIMILARITY_LENGTH:
            for earlier in paragraphs[:-1]:
                if len(earlier) < self.MIN_SIMILARITY_LENGTH:
                    continue
                if not self._similarity(last, earlier):
                    continue
                key = earlier[:80]
                count = self._similar_counts.get(key, 0)
                limit = self._tier_limit(len(last))
                if count < limit:
                    self._similar_counts[key] = count + 1
                    return RedundancyVerdict(False)
                return RedundancyVerdict(
                    True,
                    reason="similar_paragraph",
                    truncate_to=truncate_duplicate_paragraph(visible),
                )

        return RedundancyVerdict(False)
