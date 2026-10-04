# Deterministic guards on generated changes: secret patterns and paths the swarm must never write or commit.
from __future__ import annotations
import fnmatch
import re
from dataclasses import dataclass
# Paths that could leak credentials, alter CI, or touch git internals. Checked case-insensitively.
BLOCKED_PATH_PATTERNS = (
    ".git/*",
    ".github/workflows/*",
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "*/id_rsa*",
    "id_ed25519*",
    "*/id_ed25519*",
    ".npmrc",
    ".pypirc",
)
# Example env files are documentation, not secrets.
_ALLOWED_ENV_SUFFIXES = (".example", ".sample", ".template")
SECRET_PATTERNS = (
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9]{30,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
)
@dataclass
class SafetyFinding:
    # One problem found in a generated change.
    path: str
    kind: str
    detail: str
    def as_issue(self) -> str:
        # Human-readable line used in reviewer issues and error messages.
        return f"{self.path}: {self.kind} ({self.detail})"
def is_blocked_path(path: str) -> bool:
    # True when a repo-relative path matches a pattern the swarm must not write.
    normalized = path.replace("\\", "/").lower()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.endswith(_ALLOWED_ENV_SUFFIXES):
        return False
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in BLOCKED_PATH_PATTERNS)
def scan_text_for_secrets(path: str, content: str) -> list[SafetyFinding]:
    # Flags anything in content that looks like a live credential.
    findings = []
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(content):
            findings.append(SafetyFinding(path=path, kind="possible secret", detail=kind))
    return findings
def scan_changes(changes: dict[str, str]) -> list[SafetyFinding]:
    # Runs the path and secret checks over every changed file.
    findings: list[SafetyFinding] = []
    for path, content in changes.items():
        if is_blocked_path(path):
            findings.append(SafetyFinding(path=path, kind="blocked path", detail="credentials, CI or git internals"))
        findings.extend(scan_text_for_secrets(path, content))
    return findings
