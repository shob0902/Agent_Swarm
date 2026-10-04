# HMAC request signing shared by the GitHub Actions runner (client side) and the runner API (server side).
from __future__ import annotations
import hashlib
import hmac
import time
TIMESTAMP_HEADER = "X-Agent-Swarm-Timestamp"
SIGNATURE_HEADER = "X-Agent-Swarm-Signature"
def _message(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    # Canonical string covering the verb, path, time and a hash of the body, so no part can be swapped.
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return f"{timestamp}\n{method.upper()}\n{path}\n{body_hash}".encode()
def sign(secret: str, method: str, path: str, body: bytes, timestamp: str | None = None) -> dict[str, str]:
    # Returns the two headers that authenticate one runner request.
    if not secret:
        raise ValueError("RUNNER_SHARED_SECRET is not configured")
    timestamp = timestamp or str(int(time.time()))
    digest = hmac.new(secret.encode(), _message(method, path, timestamp, body), hashlib.sha256).hexdigest()
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: f"sha256={digest}"}
def verify(secret: str, method: str, path: str, body: bytes, timestamp: str, signature: str, max_age: int, now: float | None = None) -> bool:
    # Constant-time check of the signature, rejecting stale or future-dated timestamps to limit replay.
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > max_age:
        return False
    expected = sign(secret, method, path, body, timestamp)[SIGNATURE_HEADER]
    return hmac.compare_digest(expected, signature)
