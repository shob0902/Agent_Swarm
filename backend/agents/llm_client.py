"""Provider-agnostic LLM abstraction.

Every agent calls `call_llm(provider="gemini"|"groq", messages=[...])`
instead of hardcoding an SDK inline. See Section 3 of the project brief for
why two providers are used deliberately (Gemini for Planner/Coder's larger
context window, Groq for the Reviewer's fast/cheap final check).

Free-tier rate limits (RPM/RPD) on both providers are hit during normal
dev/testing, so 429s are retried with exponential backoff + jitter, capped
at MAX_RETRIES. Any other error is not retried -- retrying a malformed
request or an auth failure just burns free-tier budget for no benefit.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import groq
from django.conf import settings
from google import genai
from google.genai import types as genai_types
from google.genai.errors import ClientError as GenaiClientError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


class LLMError(Exception):
    """Raised when a provider call fails (including after exhausting retries)."""


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
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
) -> LLMResponse:
    """Provider-agnostic chat completion call.

    `messages` follows the OpenAI convention: a list of
    {"role": "system"|"user"|"assistant", "content": str} dicts. Each
    provider-specific function below adapts this to its own SDK shape.

    Raises LLMError on any failure (including exhausted retries) so callers
    can catch a single exception type regardless of provider.
    """
    if provider == "gemini":
        fn = _call_gemini
    elif provider == "groq":
        fn = _call_groq
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    if not messages:
        raise ValueError("messages must be a non-empty list")

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn(messages, temperature=temperature, max_output_tokens=max_output_tokens)
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

    raise LLMError(f"{provider} call failed after {MAX_RETRIES} retries (rate limited)") from last_exc


def _call_gemini(messages: list[dict], *, temperature: float, max_output_tokens: int) -> LLMResponse:
    """Uses the `google-genai` SDK (the older `google.generativeai` package
    this originally targeted has since been fully sunset by Google, along
    with the gemini-1.5-* models -- see GEMINI_MODEL in settings.py)."""
    if not settings.GOOGLE_API_KEY:
        raise LLMError("GOOGLE_API_KEY is not set")

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    system_instruction = "\n\n".join(system_parts) or None

    # Gemini's chat history uses role "model" instead of "assistant"; the
    # final non-system message becomes the new prompt, everything before it
    # is prior turns.
    turns = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    if not turns:
        raise ValueError("messages must include at least one non-system message")
    *history, last_turn = turns

    chat = client.chats.create(
        model=settings.GEMINI_MODEL,
        history=history,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    try:
        response = chat.send_message(last_turn["parts"][0]["text"])
    except GenaiClientError as exc:
        if exc.code == 429:
            raise _RateLimitError(str(exc)) from exc
        raise

    return LLMResponse(text=response.text, provider="gemini", model=settings.GEMINI_MODEL, raw=_safe_raw(response))


def _call_groq(messages: list[dict], *, temperature: float, max_output_tokens: int) -> LLMResponse:
    if not settings.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set")

    client = groq.Groq(api_key=settings.GROQ_API_KEY)
    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )
    except groq.RateLimitError as exc:
        raise _RateLimitError(str(exc)) from exc

    text = response.choices[0].message.content
    return LLMResponse(text=text, provider="groq", model=settings.GROQ_MODEL, raw=_safe_raw(response))


def _safe_raw(response: Any) -> Any:
    """Best-effort JSON-serializable dump of the raw SDK response, so
    AgentRun.output can persist the full response for offline debugging
    without needing to re-call the API (Section 3).

    `mode="json"` is required, not just `model_dump()` -- Gemini responses
    include raw `bytes` fields (e.g. candidates[].content.parts[].thought_signature)
    that plain model_dump() leaves as bytes, which then blows up
    AgentRun.output's JSONField save with a TypeError. mode="json" coerces
    those to JSON-safe values (e.g. base64 strings) up front.
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
