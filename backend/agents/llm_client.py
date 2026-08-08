"""Provider-agnostic LLM abstraction.

Every agent calls `call_llm(provider="groq", messages=[...], api_key=...)`
instead of hardcoding an SDK inline. The project originally split work
across Gemini (Planner/Coder, for the larger context window) and Groq
(Reviewer, for a fast/cheap final check); it now runs entirely on Groq
because Gemini's free tier caps at 20 requests/day *per Google Cloud
project* -- not per key -- which a single multi-retry pipeline run
exhausts on its own. See Section 3 of the project brief.

The `provider` argument is kept even though only one provider is wired up
today: `AgentRun.provider` records it per run, and adding a second provider
back means adding one `_call_*` function plus one dispatch entry here, not
touching four agent modules.

`api_key` is always passed explicitly by the caller rather than read from
a single global setting -- the project runs one dedicated key per agent
role (GROQ_API_KEY_PLANNER, GROQ_API_KEY_CODER_A, GROQ_API_KEY_CODER_B,
GROQ_API_KEY_REVIEWER; see settings.py), and the Coder additionally rotates
between its two keys (see agents/services/key_pool.py). Keeping this module
key-agnostic is what makes that possible without special-casing it here.

Free-tier rate limits (RPM/RPD/TPM) are hit during normal dev/testing, so
429s are retried with exponential backoff + jitter, capped at MAX_RETRIES,
then surfaced as LLMRateLimitError so callers can tell "this key is out of
quota" (rotate to another key) apart from "this request was bad" (don't).
Any other error is not retried -- retrying a malformed request or an auth
failure just burns free-tier budget for no benefit.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import groq
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


class LLMError(Exception):
    """Raised when a provider call fails (including after exhausting retries)."""


class LLMRateLimitError(LLMError):
    """The call was rate-limited and stayed rate-limited through every
    backoff attempt. Split out from LLMError so a caller holding several
    keys can penalize the specific key that ran out of quota, rather than
    treating a 429 the same as a bad request (see services/key_pool.py)."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    raw: Any = field(default=None, repr=False)


class _RateLimitError(Exception):
    """Internal signal used to trigger the shared backoff loop below."""


def call_llm(
    provider: str,
    messages: list[dict],
    *,
    api_key: str,
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
) -> LLMResponse:
    """Provider-agnostic chat completion call.

    `messages` follows the OpenAI convention: a list of
    {"role": "system"|"user"|"assistant", "content": str} dicts. Each
    provider-specific function below adapts this to its own SDK shape.

    `api_key` is required and always explicit -- see the module docstring
    for why this module never reads a key from settings itself.

    Raises LLMError (or its LLMRateLimitError subclass) on any failure,
    including exhausted retries, so callers can catch a single exception
    type regardless of provider.
    """
    try:
        fn = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown LLM provider: {provider!r}") from None

    if not messages:
        raise ValueError("messages must be a non-empty list")
    if not api_key:
        raise LLMError(f"no API key provided for {provider} call")

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn(messages, api_key=api_key, temperature=temperature, max_output_tokens=max_output_tokens)
        except _RateLimitError as exc:
            last_exc = exc
            if attempt == MAX_RETRIES:
                break
            delay = BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "%s rate-limited (attempt %d/%d), backing off %.1fs",
                provider,
                attempt + 1,
                MAX_RETRIES,
                delay,
            )
            time.sleep(delay)
        except Exception as exc:  # noqa: BLE001 - deliberately wrap every provider error
            raise LLMError(f"{provider} call failed: {exc}") from exc

    raise LLMRateLimitError(f"{provider} call failed after {MAX_RETRIES} retries (rate limited)") from last_exc


def _call_groq(messages: list[dict], *, api_key: str, temperature: float, max_output_tokens: int) -> LLMResponse:
    client = groq.Groq(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )
    except groq.RateLimitError as exc:
        raise _RateLimitError(str(exc)) from exc

    choice = response.choices[0]

    # A response cut off mid-output (finish_reason="length", most commonly
    # the Coder asked to emit a large whole-file rewrite against Groq's
    # tight free-tier token ceiling) produces truncated JSON downstream --
    # json.loads then fails with a confusing, unrelated-looking error like
    # "Unterminated string at char 44" that gives no hint the real cause was
    # an output-length budget. Surfacing finish_reason directly here makes
    # that diagnosable without digging through the raw response.
    if choice.finish_reason not in (None, "stop"):
        raise LLMError(
            f"groq response did not finish normally (finish_reason={choice.finish_reason}, "
            f"max_output_tokens={max_output_tokens}) -- likely truncated output "
            "rather than a malformed request; increase max_output_tokens for this "
            "call if the requested content is legitimately long"
        )

    return LLMResponse(text=choice.message.content, provider="groq", model=settings.GROQ_MODEL, raw=_safe_raw(response))


# Dispatch table -- one entry per supported provider. See the module
# docstring for why this stays a table with a single entry in it.
_PROVIDERS = {"groq": _call_groq}


def _safe_raw(response: Any) -> Any:
    """Best-effort JSON-serializable dump of the raw SDK response, so
    AgentRun.output can persist the full response for offline debugging
    without needing to re-call the API (Section 3).

    `mode="json"` is preferred over plain `model_dump()`: SDK responses can
    carry raw `bytes` fields that plain model_dump() leaves as bytes, which
    then blows up AgentRun.output's JSONField save with a TypeError.
    mode="json" coerces those to JSON-safe values (e.g. base64 strings)
    up front.
    """
    try:
        if hasattr(response, "model_dump"):
            try:
                return response.model_dump(mode="json")
            except TypeError:
                return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
    except Exception:  # noqa: BLE001 - logging is best-effort, never fatal
        pass
    return str(response)
