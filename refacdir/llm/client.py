"""
General LLM interface using Ollama.

Adapted from a ported voice-assistant project (see docs/LLM_CONFIG_CHAT_SCOPE.md,
Phase 0) for refacdir's "chat to define configs" feature. Talks to a local Ollama
server's ``/api/generate`` endpoint; Ollama can also proxy this same endpoint to
a signed-in cloud-hosted model without any client-side API key handling, so no
separate cloud provider client is needed here.

Changes from the ported original:
- Logging and the JSON-key fuzzy-match helper no longer depend on the source
  project's ``utils`` package (it doesn't exist in this repo); the fuzzy match
  is now a small local ``difflib``-based helper in ``refacdir.llm.redundancy``.
- Dropped CJK-response rejection and a hardcoded "interaction stopped" string
  match in ``_clean_response_for_models`` — both were TTS-compatibility rules
  specific to the original project, irrelevant (and in the CJK case, actively
  harmful for non-English file paths) here.
- ``DEFAULT_SYSTEM_PROMPT_DROP_RATE`` now defaults to 0 (always include the
  system prompt). The ported default of 0.9 was tuned for a conversational
  voice loop; a config-authoring assistant needs its schema/vocabulary context
  every call.
- The Ollama endpoint is now instance-overridable instead of a fixed constant,
  and the optional prompt/response history file resolves to a stable location
  (honoring ``REFACDIR_CACHE_DIR``) instead of whatever the process's current
  working directory happens to be at write time.
"""

from dataclasses import dataclass
import json
import math
import os
import random
import threading
import time
from typing import Callable, Iterator, List, Optional, Tuple
from urllib import request

from refacdir.llm.redundancy import (
    DefaultRedundancyPolicy,
    RedundancyPolicy,
    is_similar_strings,
    strip_thinking_blocks,
    streaming_visible_response,
)
from refacdir.utils.cache_paths import refacdir_cache_dir
from refacdir.utils.logger import setup_logger

logger = setup_logger("llm_client")

# Sentinel: omit *redundancy_policy* to follow :attr:`LLM.use_redundancy_elimination`.
_USE_INSTANCE_REDUNDANCY = object()

class LLMResponseException(Exception):
    """Raised when LLM call fails"""
    pass


class LLMGenerationCancelled(Exception):
    """Generation stopped by the caller (skip, cancel_generation, stream close)."""
    pass


@dataclass
class StreamChunk:
    """One increment of a streaming Ollama ``/api/generate`` response."""
    text: str
    accumulated: str
    done: bool


def accumulate_ollama_stream_events(
    lines: Iterator[bytes],
) -> Tuple[str, dict]:
    """Parse NDJSON *lines* into full text and the final metadata object.

    Exported for unit tests. Each non-empty line must be a JSON object with an
    optional ``response`` delta; the last object with ``done: true`` supplies
    timing and context fields for :class:`LLMResult`.
    """
    accumulated = ""
    final: dict = {}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        event = json.loads(raw.decode("utf-8"))
        accumulated += event.get("response", "") or ""
        if event.get("done"):
            final = event
    if not final:
        final = {"done": True, "response": accumulated}
    return accumulated, final


@dataclass
class LLMResult:
    """Encapsulates the response data from an Ollama LLM call."""
    response: str
    context: Optional[List[int]]
    context_provided: bool
    created_at: str
    done: bool
    done_reason: Optional[str]
    total_duration: int
    load_duration: int
    prompt_eval_count: int
    prompt_eval_duration: int
    eval_count: int
    eval_duration: int
    truncated: bool = False
    truncation_reason: str = ""

    @classmethod
    def from_json(cls, data: dict, context_provided=False) -> 'LLMResult':
        """Create a LLMResult instance from the JSON response data."""
        return cls(
            response=data.get("response", ""),
            context=data.get("context", None),
            context_provided=context_provided,
            created_at=data.get("created_at", ""),
            done=data.get("done", False),
            done_reason=data.get("done_reason", ""),
            total_duration=data.get("total_duration", 0),
            load_duration=data.get("load_duration", 0),
            prompt_eval_count=data.get("prompt_eval_count", 0),
            prompt_eval_duration=data.get("prompt_eval_duration", 0),
            eval_count=data.get("eval_count", 0),
            eval_duration=data.get("eval_duration", 0)
        )

    def validate(self):
        if self.response is None or self.response.strip() == "":
            return False
        return True

    def _get_json_attr(self, attr_name):
        try:
            if attr_name is None or attr_name.strip() == "":
                raise Exception(f"Invalid attr name: \"{attr_name}\"")
            json_str = self.response
            if json_str is None or json_str.strip() == "" or ("{" not in json_str or "}" not in json_str or ":" not in json_str):
                raise Exception("No or malformed JSON object found in JSON string!")
            json_str = json_str.replace("```", "").strip()
            if json_str.startswith("json"):
                json_str = json_str[4:].strip()
            json_obj = json.loads(json_str)
            assert(isinstance(json_obj, dict))
            if attr_name not in json_obj:
                for key in json_obj.keys():
                    if is_similar_strings(attr_name, key):
                        self.response = json_obj[key]
                        return self
            self.response = json_obj[attr_name]
            return self
        except Exception as e:
            logger.error(f"{e} - Failed to get json attr {attr_name} from json response: {json}")
            return None


class LLM:
    """Interface for interacting with the Ollama LLM API.

    Optional streaming and redundancy elimination — see
    refacdir/llm/redundancy.py and docs/LLM_CONFIG_CHAT_SCOPE.md.
    """
    ENDPOINT = "http://localhost:11434/api/generate"
    DEFAULT_TIMEOUT = 180
    # Always include the system prompt by default (0 = never drop). See module
    # docstring: the ported default of 0.9 was tuned for a different use case.
    DEFAULT_SYSTEM_PROMPT_DROP_RATE = 0.0
    CHECK_INTERVAL = 0.1  # How often to check for cancellation
    FAILURE_THRESHOLD = 3  # Number of consecutive failures before considering LLM unavailable
    DEFAULT_STATE = "local"  # Default state key for instances without a specific state
    PROMPT_RESPONSE_HISTORY_MAX_ITEMS = 200

    # Class-level failure tracking: maps state keys to failure counts
    _failure_counts = {}

    def __init__(
        self,
        model_name="deepseek-r1:14b",
        run_context=None,
        state_key=None,
        track_prompts_and_responses=False,
        use_streaming: bool = False,
        use_redundancy_elimination: bool = False,
        thinking_budget_chars: Optional[int] = None,
        endpoint: Optional[str] = None,
    ):
        self.model_name = model_name
        self.run_context = run_context
        self.state_key = state_key if state_key is not None else LLM.DEFAULT_STATE
        self.track_prompts_and_responses = bool(track_prompts_and_responses)
        self.use_streaming = bool(use_streaming)
        self.use_redundancy_elimination = bool(use_redundancy_elimination)
        self.thinking_budget_chars = thinking_budget_chars
        self.endpoint = endpoint or LLM.ENDPOINT
        self.prompt_response_history = []
        self._prompt_response_lock = threading.Lock()
        state_suffix = "".join(
            c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(self.state_key)
        )
        self.prompt_response_history_file = self._resolve_history_file_path(state_suffix)
        self._cancelled = False
        self._result = None
        self._exception = None
        self._thread = None
        self._active_http_response = None
        logger.info(
            "Using LLM model: %s (state: %s, stream=%s, redundancy=%s)",
            self.model_name,
            self.state_key,
            self.use_streaming,
            self.use_redundancy_elimination,
        )
        if self.track_prompts_and_responses:
            logger.info(
                "LLM prompt/response tracking is enabled (file: %s)",
                self.prompt_response_history_file,
            )

    @staticmethod
    def _resolve_history_file_path(state_suffix: str) -> str:
        """
        Stable, cwd-independent location for the optional prompt/response
        history file, honoring ``REFACDIR_CACHE_DIR`` when set. Renamer/backup
        actions can chdir during a batch run, so resolving this relative to
        ``os.getcwd()`` (the ported original's behavior) risked scattering the
        file into whatever directory happened to be current at write time.
        """
        filename = f"llm_prompt_response_history_{state_suffix}.json"
        override = refacdir_cache_dir()
        if override:
            os.makedirs(override, exist_ok=True)
            return os.path.join(override, filename)
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename
        )

    @classmethod
    def from_config(
        cls,
        config_obj,
        *,
        state_key: Optional[str] = None,
        run_context=None,
        track_prompts_and_responses: Optional[bool] = None,
    ) -> "LLM":
        """Build an :class:`LLM` from a host-application config object.

        Reads optional attributes (all default to off when absent):

        - ``llm_model_name``
        - ``llm_use_streaming``
        - ``llm_stream_redundancy``
        - ``llm_thinking_budget_chars``
        - ``llm_track_prompts_and_responses``

        ``config_obj`` is required (no default-import fallback): refacdir has
        no dedicated LLM settings object yet (see docs/LLM_CONFIG_CHAT_SCOPE.md,
        Phase 5), so pass whatever settings object your caller uses.
        """
        raw_budget = getattr(config_obj, "llm_thinking_budget_chars", None)
        thinking_budget = int(raw_budget) if raw_budget is not None else None
        return cls(
            model_name=getattr(config_obj, "llm_model_name", "deepseek-r1:14b"),
            run_context=run_context,
            state_key=state_key,
            track_prompts_and_responses=(
                bool(getattr(config_obj, "llm_track_prompts_and_responses", False))
                if track_prompts_and_responses is None
                else track_prompts_and_responses
            ),
            use_streaming=bool(getattr(config_obj, "llm_use_streaming", False)),
            use_redundancy_elimination=bool(
                getattr(config_obj, "llm_stream_redundancy", False)
            ),
            thinking_budget_chars=thinking_budget,
        )

    @classmethod
    def _get_failure_count_for_state(cls, state_key):
        """Get the failure count for a specific state."""
        return cls._failure_counts.get(state_key, 0)

    @classmethod
    def _increment_failure_count_for_state(cls, state_key):
        """Increment the failure count for a specific state."""
        if state_key not in cls._failure_counts:
            cls._failure_counts[state_key] = 0
        cls._failure_counts[state_key] += 1
        logger.warning(f"LLM failure count increased to {cls._failure_counts[state_key]} for state '{state_key}'")

    @classmethod
    def _reset_failure_count_for_state(cls, state_key):
        """Reset the failure count for a specific state."""
        if state_key in cls._failure_counts and cls._failure_counts[state_key] > 0:
            logger.info(f"Resetting LLM failure count from {cls._failure_counts[state_key]} to 0 for state '{state_key}'")
        cls._failure_counts[state_key] = 0

    @classmethod
    def _is_failing_for_state(cls, state_key):
        """Check if the LLM is in a failing state for a specific state key."""
        return cls._get_failure_count_for_state(state_key) >= cls.FAILURE_THRESHOLD

    def get_failure_count(self):
        """Get the failure count for this instance's state."""
        return self._get_failure_count_for_state(self.state_key)

    def increment_failure_count(self):
        """Increment the failure count for this instance's state."""
        self._increment_failure_count_for_state(self.state_key)

    def reset_failure_count(self):
        """Reset the failure count for this instance's state."""
        self._reset_failure_count_for_state(self.state_key)

    def is_failing(self):
        """Check if the LLM is in a failing state for this instance's state."""
        return self._is_failing_for_state(self.state_key)

    @classmethod
    def is_failing_for_state(cls, state_key=None):
        """Check if the LLM is in a failing state for a specific state (or default)."""
        if state_key is None:
            state_key = cls.DEFAULT_STATE
        return cls._is_failing_for_state(state_key)

    def get_llm_penalty(self):
        """Get penalty value based on failure count for this instance's state."""
        return 1.0 / (1.0 + math.log2(1.0 + self.get_failure_count()))

    def ask(
        self,
        query,
        json_key=None,
        timeout=DEFAULT_TIMEOUT,
        context=None,
        system_prompt=None,
        system_prompt_drop_rate=DEFAULT_SYSTEM_PROMPT_DROP_RATE,
        stream: Optional[bool] = None,
        on_stream_chunk: Optional[Callable[[StreamChunk], None]] = None,
        redundancy_policy=_USE_INSTANCE_REDUNDANCY,
        interrupt_on_skip: bool = True,
    ):
        """Ask the LLM a question and optionally extract a JSON value."""
        logger.debug(f"LLM.ask called with query length: {len(query)}, json_key: {json_key}")
        if json_key is not None:
            return self.generate_json_get_value(
                query,
                json_key,
                timeout=timeout,
                context=context,
                system_prompt=system_prompt,
                system_prompt_drop_rate=system_prompt_drop_rate,
                interrupt_on_skip=interrupt_on_skip,
            )
        return self.generate_response_async(
            query,
            timeout=timeout,
            context=context,
            system_prompt=system_prompt,
            system_prompt_drop_rate=system_prompt_drop_rate,
            stream=stream,
            on_stream_chunk=on_stream_chunk,
            redundancy_policy=redundancy_policy,
            interrupt_on_skip=interrupt_on_skip,
        )

    def _resolve_redundancy_policy(self, redundancy_policy) -> Optional[RedundancyPolicy]:
        """Resolve policy: sentinel → instance flag; ``None`` → off; else use policy."""
        if redundancy_policy is _USE_INSTANCE_REDUNDANCY:
            if self.use_redundancy_elimination:
                kwargs = {}
                if self.thinking_budget_chars is not None:
                    kwargs["thinking_budget_chars"] = self.thinking_budget_chars
                return DefaultRedundancyPolicy(**kwargs)
            return None
        return redundancy_policy

    def _build_generate_payload(
        self,
        query: str,
        *,
        stream: bool,
        context=None,
        system_prompt=None,
        system_prompt_drop_rate=DEFAULT_SYSTEM_PROMPT_DROP_RATE,
    ) -> Tuple[dict, bool]:
        """Return (request body, system_prompt_included)."""
        data = {
            "model": self.model_name,
            "prompt": query,
            "stream": stream,
        }
        if context is not None:
            data["context"] = context
            logger.debug(f"Adding context to LLM request, length: {len(context)}")

        system_prompt_included = False
        if system_prompt is not None and random.random() >= system_prompt_drop_rate:
            data["system"] = system_prompt
            system_prompt_included = True
            logger.debug("Including system prompt in LLM request")
        elif system_prompt is not None:
            logger.debug("Dropping system prompt from LLM request")
        return data, system_prompt_included

    def _make_generate_request(self, data: dict) -> request.Request:
        return request.Request(
            self.endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(data).encode("utf-8"),
        )

    def _finalize_result(
        self,
        result: LLMResult,
        *,
        query: str,
        context_provided: bool,
        system_prompt_included: bool,
    ) -> LLMResult:
        result.response = self._clean_response_for_models(result.response)
        self._track_prompt_response(
            prompt=query,
            response=result.response,
            context_provided=context_provided,
            system_prompt_included=system_prompt_included,
            truncated=result.truncated,
            truncation_reason=result.truncation_reason,
        )
        logger.debug(f"LLM response received, length: {len(result.response)}")
        if result.validate():
            self.reset_failure_count()
        else:
            raise LLMResponseException("LLM response is invalid!")
        return result

    def _iter_ollama_stream_events(self, req: request.Request, timeout: float) -> Iterator[dict]:
        """Yield parsed JSON objects from an Ollama streaming response."""
        with request.urlopen(req, timeout=timeout) as resp:
            self._active_http_response = resp
            try:
                for raw in resp:
                    if self._cancelled:
                        logger.debug("Stopping Ollama stream read (cancelled)")
                        break
                    raw = raw.strip()
                    if not raw:
                        continue
                    yield json.loads(raw.decode("utf-8"))
            finally:
                self._active_http_response = None

    def _generate_response_buffered(
        self,
        query: str,
        timeout: float,
        context,
        system_prompt,
        system_prompt_drop_rate,
    ) -> LLMResult:
        data, system_prompt_included = self._build_generate_payload(
            query,
            stream=False,
            context=context,
            system_prompt=system_prompt,
            system_prompt_drop_rate=system_prompt_drop_rate,
        )
        req = self._make_generate_request(data)
        logger.debug("Making LLM request (buffered)...")
        response = request.urlopen(req, timeout=timeout).read().decode("utf-8")
        resp_json = json.loads(response)
        result = LLMResult.from_json(resp_json, context_provided=context is not None)
        return self._finalize_result(
            result,
            query=query,
            context_provided=context is not None,
            system_prompt_included=system_prompt_included,
        )

    def _close_active_stream(self) -> None:
        if self._active_http_response is not None:
            try:
                self._active_http_response.close()
            except Exception as exc:
                logger.debug("Error closing LLM stream: %s", exc)

    def _generate_response_streaming(
        self,
        query: str,
        timeout: float,
        context,
        system_prompt,
        system_prompt_drop_rate,
        on_stream_chunk: Optional[Callable[[StreamChunk], None]] = None,
        redundancy_policy: Optional[RedundancyPolicy] = None,
    ) -> LLMResult:
        data, system_prompt_included = self._build_generate_payload(
            query,
            stream=True,
            context=context,
            system_prompt=system_prompt,
            system_prompt_drop_rate=system_prompt_drop_rate,
        )
        req = self._make_generate_request(data)
        logger.debug("Making LLM request (streaming)...")

        accumulated_raw = ""
        final: dict = {}
        truncated = False
        truncation_reason = ""
        for event in self._iter_ollama_stream_events(req, timeout):
            delta = event.get("response", "") or ""
            if delta:
                accumulated_raw += delta
            done = bool(event.get("done"))
            # streaming_visible_response is a no-op when no thinking tags are
            # present, so calling it unconditionally is safe for all models.
            accumulated_visible = streaming_visible_response(accumulated_raw)
            stream_chunk = StreamChunk(
                text=delta,
                accumulated=accumulated_visible,
                done=done,
            )
            if on_stream_chunk is not None:
                on_stream_chunk(stream_chunk)
            if redundancy_policy is not None and not done:
                policy_chunk = StreamChunk(
                    text=delta,
                    accumulated=accumulated_raw,
                    done=done,
                )
                verdict = redundancy_policy.on_chunk(policy_chunk)
                if verdict.should_stop:
                    if verdict.truncate_to is not None:
                        accumulated_raw = verdict.truncate_to
                    truncation_reason = verdict.reason or "redundancy"
                    truncated = True
                    final = dict(event)
                    final["done"] = True
                    final["done_reason"] = truncation_reason
                    logger.info(
                        "LLM stream stopped early (%s); %d chars kept",
                        truncation_reason,
                        len(accumulated_raw),
                    )
                    self._close_active_stream()
                    break
            if done:
                final = event
                break

        if self._cancelled:
            raise LLMGenerationCancelled()

        if not final:
            final = {"done": True, "response": accumulated_raw}
        elif not accumulated_raw and final.get("response"):
            accumulated_raw = final.get("response", "") or ""

        result = LLMResult.from_json(
            {**final, "response": accumulated_raw},
            context_provided=context is not None,
        )
        result.truncated = truncated
        result.truncation_reason = truncation_reason
        return self._finalize_result(
            result,
            query=query,
            context_provided=context is not None,
            system_prompt_included=system_prompt_included,
        )

    def generate_response(
        self,
        query,
        timeout=DEFAULT_TIMEOUT,
        context=None,
        system_prompt=None,
        system_prompt_drop_rate=DEFAULT_SYSTEM_PROMPT_DROP_RATE,
        stream: Optional[bool] = None,
        on_stream_chunk: Optional[Callable[[StreamChunk], None]] = None,
        redundancy_policy=_USE_INSTANCE_REDUNDANCY,
    ):
        """Generate a response from the LLM.

        When *stream* is ``True`` (or :attr:`use_streaming` / a redundancy
        *redundancy_policy* is set), reads Ollama's NDJSON stream and assembles
        the full text before returning. *on_stream_chunk* is called after each
        delta. *redundancy_policy* may stop generation early on repetition.

        Pass ``redundancy_policy=None`` explicitly to disable redundancy even
        when :attr:`use_redundancy_elimination` is on (e.g. JSON extraction).
        """
        logger.debug(f"LLM.generate_response called with query length: {len(query)}")
        query = self._sanitize_query(query)
        timeout = self._get_timeout(timeout)
        policy = self._resolve_redundancy_policy(redundancy_policy)
        use_stream = self.use_streaming if stream is None else stream
        if policy is not None:
            use_stream = True
        logger.info(
            f"Asking LLM {self.model_name} (stream={use_stream}, "
            f"redundancy={'on' if policy else 'off'}):\n{query}"
        )
        try:
            if use_stream:
                return self._generate_response_streaming(
                    query,
                    timeout,
                    context,
                    system_prompt,
                    system_prompt_drop_rate,
                    on_stream_chunk=on_stream_chunk,
                    redundancy_policy=policy,
                )
            return self._generate_response_buffered(
                query,
                timeout,
                context,
                system_prompt,
                system_prompt_drop_rate,
            )
        except LLMGenerationCancelled:
            raise
        except LLMResponseException:
            raise
        except Exception as e:
            logger.error(f"Failed to generate LLM response: {e}")
            self.increment_failure_count()
            raise LLMResponseException(f"Failed to generate LLM response: {e}")

    def _track_prompt_response(
        self,
        prompt,
        response,
        context_provided=False,
        system_prompt_included=False,
        truncated=False,
        truncation_reason="",
    ):
        """Record prompt/response pairs for debugging when enabled."""
        if not self.track_prompts_and_responses:
            return
        entry = {
            "timestamp": time.time(),
            "model": self.model_name,
            "prompt": prompt,
            "response": response,
            "context_provided": bool(context_provided),
            "system_prompt_included": bool(system_prompt_included),
            "truncated": bool(truncated),
            "truncation_reason": truncation_reason or "",
        }
        with self._prompt_response_lock:
            self.prompt_response_history.append(entry)
            if len(self.prompt_response_history) > self.PROMPT_RESPONSE_HISTORY_MAX_ITEMS:
                self.prompt_response_history = self.prompt_response_history[
                    -self.PROMPT_RESPONSE_HISTORY_MAX_ITEMS:
                ]
            self._persist_prompt_response_history()
            logger.debug(
                "Tracked LLM prompt/response pair (history size: %s)",
                len(self.prompt_response_history),
            )

    def _persist_prompt_response_history(self):
        """Persist tracked prompt/response history to a readable JSON file."""
        payload = {
            "model": self.model_name,
            "state_key": self.state_key,
            "updated_at": time.time(),
            "max_items": self.PROMPT_RESPONSE_HISTORY_MAX_ITEMS,
            "items": self.prompt_response_history,
        }
        try:
            with open(self.prompt_response_history_file, "w", encoding="utf-8") as out_file:
                json.dump(payload, out_file, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to persist LLM prompt/response history: %s", e)

    def generate_response_async(
        self,
        query,
        timeout=DEFAULT_TIMEOUT,
        context=None,
        system_prompt=None,
        system_prompt_drop_rate=DEFAULT_SYSTEM_PROMPT_DROP_RATE,
        stream: Optional[bool] = None,
        on_stream_chunk: Optional[Callable[[StreamChunk], None]] = None,
        redundancy_policy=_USE_INSTANCE_REDUNDANCY,
        interrupt_on_skip: bool = True,
    ):
        """Generate a response from the LLM in a separate thread with cancellation support.

        When *interrupt_on_skip* is ``False`` the generation thread is allowed to
        run to completion even if a skip is requested mid-generation. The caller
        is still responsible for checking whether to use the result after returning.
        """
        logger.debug(f"LLM.generate_response_async called with query length: {len(query)}")
        self._cancelled = False
        self._result = None
        self._exception = None
        self._thread = None

        def run_generation():
            try:
                logger.debug("Starting LLM generation in thread")
                result = self.generate_response(
                    query,
                    timeout,
                    context,
                    system_prompt,
                    system_prompt_drop_rate,
                    stream=stream,
                    on_stream_chunk=on_stream_chunk,
                    redundancy_policy=redundancy_policy,
                )
                if not self._cancelled:
                    self._result = result
                    logger.debug("LLM generation completed successfully")
                else:
                    logger.debug("LLM generation cancelled before completion")
            except LLMGenerationCancelled:
                logger.debug("LLM generation cancelled during streaming")
            except Exception as e:
                if not self._cancelled:
                    self._exception = e
                    logger.error(f"Exception in LLM generation thread: {e}")

        # Start the generation in a separate thread
        self._thread = threading.Thread(target=run_generation)
        self._thread.daemon = True  # Make it a daemon thread so it won't prevent program exit
        self._thread.start()
        logger.info("LLM generation thread started")

        # Wait for completion or cancellation
        try:
            while self._thread and self._thread.is_alive():
                if interrupt_on_skip and self.run_context and self.run_context.should_skip():
                    logger.debug("Cancelling LLM generation due to skip request")
                    self.cancel_generation()
                    return None
                time.sleep(self.CHECK_INTERVAL)
        except Exception as e:
            self._exception = e
            logger.error(f"Exception while monitoring LLM thread: {e}")
        finally:
            self._thread = None  # Clean up thread reference when done

        # Handle the result
        if self._exception:
            logger.error(f"Failed to generate LLM response: {self._exception}")
            raise LLMResponseException(f"Failed to generate LLM response: {self._exception}")

        return self._result

    def generate_json_get_value(
        self,
        query,
        json_key,
        timeout=DEFAULT_TIMEOUT,
        context=None,
        system_prompt=None,
        system_prompt_drop_rate=DEFAULT_SYSTEM_PROMPT_DROP_RATE,
        interrupt_on_skip: bool = True,
    ):
        """Generate a response and extract a specific JSON value.

        Always uses buffered (non-streaming) mode without redundancy so partial
        JSON is never returned.
        """
        result = self.generate_response_async(
            query,
            timeout=timeout,
            context=context,
            system_prompt=system_prompt,
            system_prompt_drop_rate=system_prompt_drop_rate,
            stream=False,
            redundancy_policy=None,
            interrupt_on_skip=interrupt_on_skip,
        )
        if result is None:
            raise LLMResponseException("Failed to generate LLM response - Result is None")
        return result._get_json_attr(json_key)

    # Model name prefixes known to use <think>…</think> reasoning blocks.
    _THINKING_MODEL_PREFIXES = ("deepseek-r1", "qwen3", "qwq")

    def _is_thinking_model(self) -> bool:
        """Return True if the model is known to emit thinking-block wrapper tags."""
        name_lower = self.model_name.lower()
        return any(name_lower.startswith(p) for p in self._THINKING_MODEL_PREFIXES)

    def _clean_response_for_models(self, response_text):
        """Strip thinking-block wrappers and a common "Final Answer:" prefix some models emit."""
        response_text = strip_thinking_blocks(response_text)

        if response_text.strip().startswith("Final Answer:"):
            response_text = response_text[response_text.find("Final Answer:") + len("Final Answer:"):].strip()

        return response_text

    def _sanitize_query(self, query):
        return query

    def _get_timeout(self, timeout=DEFAULT_TIMEOUT):
        if self._is_thinking_model():
            # Thinking models have internal prompt mechanisms which
            # can take a while to complete for complex requests.
            return max(timeout, 300)
        return timeout

    def cancel_generation(self):
        """Cancel any ongoing LLM generation."""
        self._cancelled = True
        self._close_active_stream()
        if self._thread and self._thread.is_alive():
            logger.info("Cancelling LLM generation")
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                logger.error("Thread did not terminate gracefully, forcing cleanup")
            self._thread = None  # Force cleanup even if thread is still alive

    def __del__(self):
        """Ensure cleanup on object destruction."""
        self.cancel_generation()


if __name__ == "__main__":
    llm = LLM()
    print(llm.generate_response("What is the meaning of life?"))
