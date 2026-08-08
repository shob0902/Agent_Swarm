"""Least-recently-used + cooldown rotation across several API keys for the
same provider.

Every agent now runs on Groq (see llm_client.py), with one dedicated key per
role -- except the Coder, which gets two (GROQ_API_KEY_CODER_A/_B) because
it's called once per plan *plus* once per retry attempt, several times more
often than the other agents combined. This module is what decides which of
those two keys serves a given call.

The naive version -- alternate strictly by attempt number -- wastes calls:
if key A is already rate-limited, every even attempt still goes to A first,
eats a full backoff cycle inside `llm_client.call_llm`, and only then fails
over. So selection here is driven by *observed key state* rather than by a
counter:

  1. Keys that aren't configured (empty string) are dropped entirely.
  2. Keys whose cooldown has expired are tried first, **least recently used
     first**. In the steady state that's plain alternation (A, B, A, B...),
     but it self-corrects: a key skipped because it was cooling down is the
     stalest one when it recovers, so it's picked first and the load
     re-balances on its own instead of staying permanently lopsided.
  3. Keys still cooling down are appended *after* those, ordered by whose
     cooldown expires soonest -- so a call never hard-fails just because
     every key is throttled; it still tries the one closest to recovery.
  4. A 429 puts that key on an exponentially growing cooldown (doubling per
     consecutive rate limit, capped), so a genuinely exhausted key stops
     being picked first rather than being re-tried every single call. Any
     other failure gets a much shorter fixed cooldown -- enough to prefer
     the sibling key on the next call, without writing off what might have
     been one transient blip. A success clears both.

State is per-process and in-memory: with `celery -P solo` (what this project
documents on Windows) that's exactly one pool shared by every pipeline run,
which is what makes the LRU ordering meaningful across tasks. Under a
multi-process worker each process keeps its own view -- still correct, just
less well-informed. Moving this to Redis is the upgrade path if that ever
matters; nothing outside this module would change.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Base penalty applied to a rate-limited key, doubled per consecutive 429 up
# to _MAX_RATE_LIMIT_COOLDOWN. Groq's free-tier limits are per-minute, so one
# minute is the natural floor -- anything shorter just re-hits the same 429.
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
_MAX_RATE_LIMIT_COOLDOWN = 480.0
# Non-429 failures (bad key, malformed request, transient 5xx) aren't quota
# problems, so this only needs to be long enough to de-prioritize the key for
# the immediate next call rather than to wait out a quota window.
FAILURE_COOLDOWN_SECONDS = 15.0


@dataclass
class _KeyState:
    slot: str
    api_key: str
    # Recency is tracked as a pool-wide counter rather than a timestamp:
    # time.monotonic() has ~15ms resolution on Windows, so two calls close
    # together read as *equally* recent, the LRU comparison ties, and
    # rotation silently collapses onto whichever key wins the tiebreak. A
    # counter is exact at any call rate. (Cooldowns below still use real
    # time -- those genuinely are about wall-clock quota windows.)
    last_used_seq: int = 0
    cooldown_until: float = 0.0
    consecutive_rate_limits: int = 0
    # Position at construction time -- only used to break ties deterministically
    # between keys that have never been used (all last_used_seq == 0).
    index: int = 0


@dataclass
class KeySelection:
    """One candidate key to attempt, in preference order."""

    slot: str
    api_key: str
    cooling: bool = False


@dataclass
class KeyPool:
    """Thread-safe rotation over a fixed set of same-provider API keys.

    Callers walk `select()` in order and report the outcome of each attempt
    back via `mark_success` / `mark_rate_limited` / `mark_failed`, which is
    what feeds the next call's ordering.
    """

    _states: list[_KeyState] = field(default_factory=list)
    _use_counter: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, str]]) -> KeyPool:
        """`pairs` is [(slot_name, api_key), ...]; blank keys are dropped."""
        pool = cls()
        pool._states = [
            _KeyState(slot=slot, api_key=key, index=i)
            for i, (slot, key) in enumerate(p for p in pairs if p[1])
        ]
        return pool

    @property
    def configured_slots(self) -> list[str]:
        return [s.slot for s in self._states]

    def select(self, tiebreak: int = 0) -> list[KeySelection]:
        """Candidate keys, best first. Empty only if no key is configured.

        `tiebreak` (the pipeline's retry-attempt number) only matters on a
        cold pool where every key is equally stale -- it makes the very first
        Coder calls of a worker's life still alternate instead of both
        starting on slot A.
        """
        now = time.monotonic()
        with self._lock:
            if not self._states:
                return []
            n = len(self._states)
            available = [s for s in self._states if s.cooldown_until <= now]
            cooling = [s for s in self._states if s.cooldown_until > now]
            available.sort(key=lambda s: (s.last_used_seq, (s.index - tiebreak) % n))
            cooling.sort(key=lambda s: s.cooldown_until)
            return [
                *(KeySelection(s.slot, s.api_key, cooling=False) for s in available),
                *(KeySelection(s.slot, s.api_key, cooling=True) for s in cooling),
            ]

    def mark_used(self, slot: str) -> None:
        """Record an attempt regardless of outcome, so the LRU ordering
        reflects requests actually sent (a key that fails still consumed a
        request against its quota)."""
        with self._lock:
            state = self._find(slot)
            if state:
                self._use_counter += 1
                state.last_used_seq = self._use_counter

    def mark_success(self, slot: str) -> None:
        with self._lock:
            state = self._find(slot)
            if state:
                state.consecutive_rate_limits = 0
                state.cooldown_until = 0.0

    def mark_rate_limited(self, slot: str) -> None:
        with self._lock:
            state = self._find(slot)
            if not state:
                return
            state.consecutive_rate_limits += 1
            penalty = min(
                RATE_LIMIT_COOLDOWN_SECONDS * (2 ** (state.consecutive_rate_limits - 1)),
                _MAX_RATE_LIMIT_COOLDOWN,
            )
            state.cooldown_until = time.monotonic() + penalty

    def mark_failed(self, slot: str) -> None:
        with self._lock:
            state = self._find(slot)
            if state:
                state.cooldown_until = max(
                    state.cooldown_until, time.monotonic() + FAILURE_COOLDOWN_SECONDS
                )

    def _find(self, slot: str) -> _KeyState | None:
        return next((s for s in self._states if s.slot == slot), None)
