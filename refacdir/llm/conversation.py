"""
Headless draft/validate/retry conversation loop (Phase 3,
docs/LLM_CONFIG_CHAT_SCOPE.md).

Turns a plain-language action description into a validated action dict:
ask the LLM for a single JSON object -> parse it -> dry-construct it via
refacdir.llm.validation.validate_action (Phase 2) -> on a parse or
validation failure, feed the problem back to the LLM and retry, capped at
a small number of attempts.

Deliberately no UI yet (Phase 5) — this module's own ``__main__`` block is
the "testable via script/CLI first" tool called for in the Phase 3 scope
entry, for manually checking whether the retry loop actually converges
against a real Ollama instance before any UI work begins.

Language: English only for now (see SUPPORTED_LANGUAGES) — the schema
descriptions this loop embeds in its system prompt (refacdir/llm/config_schema.py)
are English docstrings, and the prompt explicitly asks the model to respond in
English. Nothing else about this module's structure is English-specific;
extending SUPPORTED_LANGUAGES later would also need the underlying schema
docstrings translated (or a per-language override), which is out of scope here.
"""

from dataclasses import dataclass, field
import json
import re
from typing import List, Optional

from refacdir.batch import ActionType
from refacdir.llm.client import LLM, LLMResponseException
from refacdir.llm.config_schema import get_full_schema_description
from refacdir.llm.safety import apply_safety_defaults
from refacdir.llm.validation import ValidationResult, validate_action

DEFAULT_MAX_ATTEMPTS = 3

# Only language implemented so far — see module docstring.
SUPPORTED_LANGUAGES = ("English",)
DEFAULT_LANGUAGE = "English"


def _validate_language(language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language {language!r}; only {SUPPORTED_LANGUAGES} "
            "implemented so far (see docs/LLM_CONFIG_CHAT_SCOPE.md, Phase 3)."
        )


@dataclass
class DraftAttempt:
    """One round of the conversation: the raw LLM response and what came of it.

    Exactly one of *parse_error* / *validation* is set (parsing happens before
    validation, so a parse failure means validation never ran that round).
    """
    raw_response: str
    parsed: Optional[dict] = None
    parse_error: Optional[str] = None
    validation: Optional[ValidationResult] = None


@dataclass
class DraftResult:
    """Outcome of draft_action(): either a validated draft or the full attempt history."""
    action_type: ActionType
    success: bool
    action_dict: Optional[dict] = None
    warnings: List[str] = field(default_factory=list)
    attempts: List[DraftAttempt] = field(default_factory=list)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def last_error_summary(self) -> str:
        """The most recent failure, ready to show a user or retry manually. Empty if no attempts were made."""
        if not self.attempts:
            return ""
        last = self.attempts[-1]
        if last.parse_error:
            return last.parse_error
        if last.validation is not None:
            return last.validation.error_summary()
        return ""


def _build_system_prompt(action_type: ActionType, language: str) -> str:
    schema = get_full_schema_description(action_type)
    return (
        "You are a configuration-drafting assistant for RefacDir, a file "
        "management batch-job tool. Given a user's plain-language description "
        "of what they want to happen, respond with EXACTLY ONE JSON object "
        f"describing a single {action_type.name} action, matching the schema "
        "below. Do not add commentary, explanation, or markdown code fences — "
        "the response body must be the JSON object and nothing else.\n\n"
        f"Respond only in {language}: every string value you author (names, "
        f"labels, etc.) should be in {language}, even if the user's "
        "description mixes in another language.\n\n"
        f"Schema for a {action_type.name} action:\n\n{schema}"
    )


def _build_retry_prompt(description: str, previous_attempt: DraftAttempt) -> str:
    if previous_attempt.parse_error:
        problem = f"Your last response could not be used: {previous_attempt.parse_error}"
    else:
        problem = (
            "Your last draft was rejected by validation with the following "
            f"error(s):\n{previous_attempt.validation.error_summary()}"
        )
    return (
        f"{problem}\n\n"
        f"Your previous response was:\n{previous_attempt.raw_response}\n\n"
        "Please correct the problem and respond again with a single JSON "
        f"object for the same request:\n{description}"
    )


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a single JSON object from free-form LLM text.

    Strips markdown code fences and a leading "json" language tag (models
    reach for these even when explicitly asked not to), then parses whatever
    lies between the first "{" and the last "}". Raises ValueError with a
    human-readable message on failure — draft_action catches this and records
    it as a parse_error rather than letting it propagate.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    if not cleaned:
        raise ValueError("Empty response")
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in response")
    candidate = cleaned[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


def draft_action(
    description: str,
    action_type: ActionType,
    llm: LLM,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    language: str = DEFAULT_LANGUAGE,
) -> DraftResult:
    """
    Turn *description* into a validated action dict for *action_type*.

    Runs up to *max_attempts* draft/validate rounds: ask *llm* (any object
    exposing ``generate_response(query, system_prompt=...)`` returning
    something with a ``.response`` string — real usage passes an
    ``refacdir.llm.client.LLM`` instance, tests pass a stub), parse its
    response as one JSON object, then dry-construct it via
    ``refacdir.llm.validation.validate_action``. A parse failure or a
    structural validation error is fed back to the LLM as context for the
    next attempt. Warnings (e.g. a not-yet-existing path — see
    ``validation.py``) do not count as failure; the first attempt that
    produces a structurally valid draft ends the loop. A transient
    ``LLMResponseException`` from the LLM call itself is also retried rather
    than raised, consuming one of the capped attempts.

    Raises ``ValueError`` immediately, before any LLM call, for an
    unsupported *action_type* (currently just ``IMAGE_CATEGORIZER`` — same
    boundary as ``config_schema.get_schema_description``) or an unsupported
    *language* (see ``SUPPORTED_LANGUAGES``) or a non-positive *max_attempts*.

    Returns a ``DraftResult`` with ``success=False`` and the full attempt
    history if every attempt is exhausted without a valid draft — callers
    needing the actual failure reason should use
    ``DraftResult.last_error_summary()``.
    """
    _validate_language(language)
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    # Raises ValueError for an unsupported action_type before any LLM call.
    system_prompt = _build_system_prompt(action_type, language)

    attempts: List[DraftAttempt] = []
    query = description

    for _ in range(max_attempts):
        try:
            result = llm.generate_response(query, system_prompt=system_prompt)
        except LLMResponseException as exc:
            attempts.append(DraftAttempt(raw_response="", parse_error=str(exc)))
            continue

        raw_response = result.response

        try:
            parsed = _extract_json_object(raw_response)
        except ValueError as exc:
            attempt = DraftAttempt(raw_response=raw_response, parse_error=str(exc))
            attempts.append(attempt)
            query = _build_retry_prompt(description, attempt)
            continue

        # Force the safest dry-run/confirmation field (Phase 4) before this
        # draft is ever validated or returned — regardless of what the model
        # said (or hallucinated) for it. See refacdir/llm/safety.py.
        parsed = apply_safety_defaults(action_type, parsed)

        validation = validate_action(action_type, parsed)
        attempt = DraftAttempt(raw_response=raw_response, parsed=parsed, validation=validation)
        attempts.append(attempt)

        if validation.valid:
            return DraftResult(
                action_type=action_type,
                success=True,
                action_dict=parsed,
                warnings=list(validation.warnings),
                attempts=attempts,
            )

        query = _build_retry_prompt(description, attempt)

    return DraftResult(action_type=action_type, success=False, attempts=attempts)


if __name__ == "__main__":
    import argparse

    from refacdir.llm.config_schema import supported_action_types

    parser = argparse.ArgumentParser(
        description=(
            "Manually exercise the draft/validate/retry loop against a real "
            "Ollama instance — de-risking script for Phase 3, see "
            "docs/LLM_CONFIG_CHAT_SCOPE.md. Not an automated test: "
            "test/llm/test_conversation.py covers the loop mechanics with a "
            "stub LLM; this script is for checking real-model convergence."
        )
    )
    parser.add_argument(
        "action_type",
        choices=[a.name for a in supported_action_types()],
        help="RefacDir action type to draft.",
    )
    parser.add_argument("description", help="Plain-language description of the desired action.")
    parser.add_argument("--model", default="deepseek-r1:14b")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--endpoint", default=None, help="Override the Ollama endpoint (e.g. for a cloud-routed model).")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="On success, also run the Phase 4 match/affected-file preview (refacdir/llm/preview.py) and print it.",
    )
    args = parser.parse_args()

    llm_instance = LLM(model_name=args.model, endpoint=args.endpoint)
    action_type_arg = ActionType[args.action_type]
    draft_result = draft_action(
        args.description,
        action_type_arg,
        llm_instance,
        max_attempts=args.max_attempts,
    )
    print(f"Attempts: {draft_result.attempt_count}")
    if draft_result.success:
        print("SUCCESS:")
        print(json.dumps(draft_result.action_dict, indent=2))
        if draft_result.warnings:
            print("Warnings:")
            for warning in draft_result.warnings:
                print(f" - {warning}")
        if args.preview:
            from refacdir.llm.preview import preview_action

            preview = preview_action(action_type_arg, draft_result.action_dict)
            print("\nPREVIEW:")
            if preview.available:
                print(preview.summary)
                print(json.dumps(preview.details, indent=2, default=str))
            else:
                print(f"Preview unavailable: {preview.reason}")
    else:
        print("FAILED after exhausting attempts.")
        print(draft_result.last_error_summary())
