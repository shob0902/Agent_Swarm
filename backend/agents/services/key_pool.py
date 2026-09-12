# Rotates the Coder's API keys by least-recently-used, backing off keys that hit a rate limit.
from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
_MAX_RATE_LIMIT_COOLDOWN = 480.0
FAILURE_COOLDOWN_SECONDS = 15.0
@dataclass
class _KeyState:
    # Bookkeeping for one key: how recently it was used and how long it's benched for.
    slot: str
    api_key: str
    last_used_seq: int = 0
    cooldown_until: float = 0.0
    consecutive_rate_limits: int = 0
    index: int = 0
@dataclass
class KeySelection:
    # One candidate key to try, in preference order.
    slot: str
    api_key: str
    cooling: bool = False
@dataclass
class KeyPool:
    # Thread-safe pool that hands out keys and learns from how each one performed.
    _states: list[_KeyState] = field(default_factory=list)
    _use_counter: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, str]]) -> KeyPool:
        # Builds a pool from (slot, key) pairs, ignoring any slot with a blank key.
        pool = cls()
        pool._states = [
            _KeyState(slot=slot, api_key=key, index=i)
            for i, (slot, key) in enumerate(p for p in pairs if p[1])
        ]
        return pool
    @property
    def configured_slots(self) -> list[str]:
        # Names of the keys that were actually configured.
        return [s.slot for s in self._states]
    def select(self, tiebreak: int = 0) -> list[KeySelection]:
        # Returns every key in preference order: ready keys oldest-first, then cooling ones by soonest recovery.
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
        # Bumps the key's recency counter so the next selection rotates away from it.
        with self._lock:
            state = self._find(slot)
            if state:
                self._use_counter += 1
                state.last_used_seq = self._use_counter
    def mark_success(self, slot: str) -> None:
        # Clears any cooldown and the rate-limit streak after a call that worked.
        with self._lock:
            state = self._find(slot)
            if state:
                state.consecutive_rate_limits = 0
                state.cooldown_until = 0.0
    def mark_rate_limited(self, slot: str) -> None:
        # Benches the key for a doubling, capped cooldown after each consecutive 429.
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
        # Applies a short cooldown after a non-rate-limit failure so the sibling key is preferred next.
        with self._lock:
            state = self._find(slot)
            if state:
                state.cooldown_until = max(
                    state.cooldown_until, time.monotonic() + FAILURE_COOLDOWN_SECONDS
                )
    def _find(self, slot: str) -> _KeyState | None:
        # Looks up a key's state by slot name.
        return next((s for s in self._states if s.slot == slot), None)
