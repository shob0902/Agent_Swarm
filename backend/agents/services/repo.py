"""GitHub repo acquisition: turns a public `github_url` into a local
checkout the rest of the pipeline can treat exactly like the old
`repo_path` (planner/coder/tester all just want a directory on disk).

Public repos only (Section 3/13 non-goals: no auth/user accounts, no
secrets management for per-user GitHub tokens) -- private repos and any
non-github.com host are rejected before we ever shell out to git.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import tempfile

from git import GitCommandError, Repo

logger = logging.getLogger(__name__)

# https://github.com/<owner>/<repo>[.git][/] -- owner/repo segments are the
# same charset GitHub itself allows (alphanumerics, hyphen, underscore, dot).
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class RepoCloneError(Exception):
    """Raised when a github_url is malformed or the clone itself fails
    (repo doesn't exist, is private, network unreachable, ...)."""


def is_valid_github_url(github_url: str) -> bool:
    return bool(GITHUB_URL_RE.match((github_url or "").strip()))


def clone_repo(github_url: str) -> str:
    """Shallow-clones `github_url` into a fresh temp directory and returns
    its path. Caller owns cleanup (see `cleanup_clone`) -- the pipeline
    task removes it in a `finally` once the run is over, success or not.
    """
    if not is_valid_github_url(github_url):
        raise RepoCloneError(
            f"{github_url!r} is not a public GitHub repo URL "
            "(expected https://github.com/<owner>/<repo>)"
        )

    dest = tempfile.mkdtemp(prefix="agent-swarm-repo-")
    try:
        # depth=1: we only ever need the current tree, never history --
        # keeps the clone fast and cheap on the free-tier bandwidth this
        # project targets (Section 3).
        # GIT_TERMINAL_PROMPT=0: a private/nonexistent repo would otherwise
        # make git hang waiting for a username/password on stdin (there is
        # none to give -- Section 13, no auth) -- this makes it fail fast
        # with GitCommandError instead.
        Repo.clone_from(github_url, dest, depth=1, env={"GIT_TERMINAL_PROMPT": "0"})
    except GitCommandError as exc:
        cleanup_clone(dest)
        raise RepoCloneError(f"Could not clone {github_url!r}: {exc}") from exc
    return dest


def _clear_readonly(func, path, exc_info):
    """`shutil.rmtree` onerror hook: git leaves its `.git/objects/pack/*`
    files read-only, which makes a plain rmtree raise PermissionError on
    Windows -- clear the read-only bit and retry once before giving up.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup_clone(local_path: str | None) -> None:
    if not local_path:
        return
    try:
        shutil.rmtree(local_path, onerror=_clear_readonly)
    except OSError:
        # Best-effort: don't let a stuck temp-dir removal fail/mask the
        # pipeline's actual result. Logged so leaked clones are visible
        # instead of silently accumulating under the OS temp dir.
        logger.warning("Failed to remove cloned repo at %s", local_path, exc_info=True)
