# Parses and validates https://github.com/<owner>/<repo> URLs before anything shells out to git or calls the API.
from __future__ import annotations
import re
from dataclasses import dataclass
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$"
)
class InvalidRepoURL(ValueError):
    # Raised when a string is not a plain https://github.com/<owner>/<repo> URL.
    pass
@dataclass(frozen=True)
class RepoRef:
    # An owner/name pair identifying one GitHub repository.
    owner: str
    name: str
    @property
    def full_name(self) -> str:
        # "owner/name", the form the REST API paths use.
        return f"{self.owner}/{self.name}"
    @property
    def clone_url(self) -> str:
        # Anonymous HTTPS clone URL; never carries a token.
        return f"https://github.com/{self.full_name}.git"
    @property
    def html_url(self) -> str:
        # Browser URL for the repository.
        return f"https://github.com/{self.full_name}"
def parse_github_url(github_url: str) -> RepoRef:
    # Returns the RepoRef for a GitHub URL, rejecting extra path segments, queries, credentials and other hosts.
    match = GITHUB_URL_RE.match((github_url or "").strip())
    if not match or match.group("repo") in {".", ".."}:
        raise InvalidRepoURL(
            f"{github_url!r} is not a GitHub repo URL (expected https://github.com/<owner>/<repo>)"
        )
    return RepoRef(owner=match.group("owner"), name=match.group("repo"))
def is_valid_github_url(github_url: str) -> bool:
    # Boolean form of parse_github_url for validators.
    try:
        parse_github_url(github_url)
    except InvalidRepoURL:
        return False
    return True
