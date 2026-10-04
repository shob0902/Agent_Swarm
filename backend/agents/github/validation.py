# Early, best-effort repository checks run when a task is created, so obvious mistakes fail in the form, not minutes later in the runner.
from __future__ import annotations
import logging
from django.conf import settings
from .client import GitHubClient, GitHubError
from .repo_url import InvalidRepoURL, parse_github_url
logger = logging.getLogger(__name__)
def repository_error(github_url: str) -> str | None:
    # Returns a user-facing reason the repo can't be used, or None. Network/rate-limit trouble is not the user's fault, so it passes.
    try:
        ref = parse_github_url(github_url)
    except InvalidRepoURL:
        return "Must be a GitHub repository URL, e.g. https://github.com/owner/repo"
    if settings.ALLOWED_REPO_OWNERS and ref.owner.lower() not in settings.ALLOWED_REPO_OWNERS:
        return f"This deployment only accepts repositories owned by: {', '.join(settings.ALLOWED_REPO_OWNERS)}"
    if not settings.GITHUB_VALIDATE_REPOS:
        return None
    client = GitHubClient(settings.GITHUB_DISPATCH_TOKEN, settings.GITHUB_API_URL)
    try:
        info = client.get_repo(ref.full_name)
    except GitHubError as exc:
        if exc.status == 404:
            return f"Repository {ref.full_name} was not found (it must exist and be public)"
        logger.warning("Could not pre-validate %s: %s", ref.full_name, exc)
        return None
    if info.get("private"):
        return "Only public repositories are supported"
    if info.get("archived"):
        return f"Repository {ref.full_name} is archived and cannot accept pull requests"
    return None
