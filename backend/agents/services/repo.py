# Clones a public GitHub repo into a temp directory for the pipeline to work on.
from __future__ import annotations
import logging
import os
import re
import shutil
import stat
import tempfile
from git import GitCommandError, Repo
logger = logging.getLogger(__name__)
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
class RepoCloneError(Exception):
    # Raised when the URL is malformed or the clone itself fails.
    pass
def is_valid_github_url(github_url: str) -> bool:
    # Checks the URL looks like https://github.com/<owner>/<repo> before we shell out to git.
    return bool(GITHUB_URL_RE.match((github_url or "").strip()))
def clone_repo(github_url: str) -> str:
    # Shallow-clones the repo into a fresh temp directory and returns that path for the caller to clean up.
    if not is_valid_github_url(github_url):
        raise RepoCloneError(
            f"{github_url!r} is not a public GitHub repo URL "
            "(expected https://github.com/<owner>/<repo>)"
        )
    dest = tempfile.mkdtemp(prefix="agent-swarm-repo-")
    try:
        Repo.clone_from(github_url, dest, depth=1, env={"GIT_TERMINAL_PROMPT": "0"})
    except GitCommandError as exc:
        cleanup_clone(dest)
        raise RepoCloneError(f"Could not clone {github_url!r}: {exc}") from exc
    return dest
def _clear_readonly(func, path, exc_info):
    # rmtree hook that clears the read-only bit git leaves on pack files, which trips up Windows.
    os.chmod(path, stat.S_IWRITE)
    func(path)
def cleanup_clone(local_path: str | None) -> None:
    # Deletes the temp clone, logging rather than raising if the directory won't go away.
    if not local_path:
        return
    try:
        shutil.rmtree(local_path, onerror=_clear_readonly)
    except OSError:
        logger.warning("Failed to remove cloned repo at %s", local_path, exc_info=True)
