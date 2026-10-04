# Clones a public GitHub repo into a temp directory for the pipeline to work on.
from __future__ import annotations
import logging
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from git import GitCommandError, Repo
from ..github.repo_url import InvalidRepoURL, is_valid_github_url, parse_github_url
logger = logging.getLogger(__name__)
__all__ = ["RepoCloneError", "CloneInfo", "is_valid_github_url", "clone_repo", "head_info", "checkout_commit", "cleanup_clone"]
class RepoCloneError(Exception):
    # Raised when the URL is malformed or the clone itself fails.
    pass
@dataclass
class CloneInfo:
    # The branch and commit the agents start from; the PR is opened against exactly this base.
    branch: str
    sha: str
def clone_repo(github_url: str) -> str:
    # Shallow-clones the repo anonymously into a fresh temp directory and returns that path for the caller to clean up.
    try:
        ref = parse_github_url(github_url)
    except InvalidRepoURL as exc:
        raise RepoCloneError(str(exc)) from exc
    dest = tempfile.mkdtemp(prefix="agent-swarm-repo-")
    try:
        Repo.clone_from(ref.clone_url, dest, depth=1, env={"GIT_TERMINAL_PROMPT": "0"}).close()
    except GitCommandError as exc:
        cleanup_clone(dest)
        raise RepoCloneError(f"Could not clone {github_url!r} (is it public?): {exc}") from exc
    return dest
def head_info(local_path: str) -> CloneInfo:
    # Reads the checked-out branch name and commit sha of a fresh clone.
    with Repo(local_path) as repo:
        try:
            branch = repo.active_branch.name
        except TypeError:
            branch = ""
        return CloneInfo(branch=branch, sha=repo.head.commit.hexsha)
def checkout_commit(local_path: str, sha: str) -> None:
    # Puts a fresh shallow clone on an exact commit, so a resumed run applies its saved changes to the
    # same base the original run used even if the default branch has moved on since.
    try:
        with Repo(local_path) as repo:
            if repo.head.commit.hexsha == sha:
                return
            repo.git.fetch("--depth", "1", "origin", sha)
            repo.git.checkout("--detach", sha)
    except GitCommandError as exc:
        raise RepoCloneError(f"Could not check out base commit {sha[:12]}: {exc}") from exc
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
