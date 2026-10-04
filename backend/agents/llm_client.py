# Thin provider-agnostic wrapper around the LLM SDK, with retry and backoff on rate limits.
from __future__ import annotations
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
import groq
from django.conf import settings
logger = logging.getLogger(__name__)
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
class LLMError(Exception):
    # Raised when a provider call fails, including after all retries are used up.
    pass
class LLMRateLimitError(LLMError):
    # Raised when the call stayed rate-limited through every backoff attempt.
    pass
@dataclass
class LLMResponse:
    # Normalised result returned to callers regardless of which provider answered.
    text: str
    provider: str
    model: str
    raw: Any = field(default=None, repr=False)
class _RateLimitError(Exception):
    # Internal signal that triggers the shared backoff loop.
    pass
def call_llm(
    provider: str,
    messages: list[dict],
    *,
    api_key: str,
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
) -> LLMResponse:
    # Sends a chat completion through the named provider, retrying with backoff while it is rate-limited.
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
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{provider} call failed: {exc}") from exc
    raise LLMRateLimitError(f"{provider} call failed after {MAX_RETRIES} retries (rate limited)") from last_exc
_CLIENTS: dict[tuple, Any] = {}
_CLIENTS_LOCK = threading.Lock()
def _groq_client(api_key: str):
    # One SDK client per key for the life of the process, so calls reuse its HTTPS connection pool
    # instead of paying a fresh TLS handshake each time. Keyed on the class too, so a patched SDK gets its own.
    key = (groq.Groq, api_key)
    with _CLIENTS_LOCK:
        if key not in _CLIENTS:
            _CLIENTS[key] = groq.Groq(api_key=api_key)
        return _CLIENTS[key]
def _call_groq(messages: list[dict], *, api_key: str, temperature: float, max_output_tokens: int) -> LLMResponse:
    # Makes the actual Groq call and flags a truncated answer instead of letting it break JSON parsing later.
    client = _groq_client(api_key)
    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_output_tokens,
            **_reasoning_kwargs(settings.GROQ_MODEL),
        )
    except groq.RateLimitError as exc:
        raise _RateLimitError(str(exc)) from exc
    choice = response.choices[0]
    if choice.finish_reason not in (None, "stop"):
        raise LLMError(
            f"groq response did not finish normally (finish_reason={choice.finish_reason}, "
            f"max_output_tokens={max_output_tokens}) -- likely truncated output "
            "rather than a malformed request; increase max_output_tokens for this "
            "call if the requested content is legitimately long"
        )
    return LLMResponse(text=choice.message.content, provider="groq", model=settings.GROQ_MODEL, raw=_safe_raw(response))
# Groq models that accept reasoning_effort; sending it to any other model is a 400.
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss",)
def _reasoning_kwargs(model: str) -> dict:
    # Caps hidden reasoning on gpt-oss models so it doesn't crowd the answer out of max_tokens.
    effort = settings.GROQ_REASONING_EFFORT
    if effort and model.startswith(_REASONING_MODEL_PREFIXES):
        return {"reasoning_effort": effort}
    return {}
_PROVIDERS = {"groq": _call_groq}
def _safe_raw(response: Any) -> Any:
    # Turns the raw SDK response into something JSON-safe so it can be stored on the AgentRun row.
    try:
        if hasattr(response, "model_dump"):
            try:
                return response.model_dump(mode="json")
            except TypeError:
                return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
    except Exception:  # noqa: BLE001
        pass
    return str(response)
