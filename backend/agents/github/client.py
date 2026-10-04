# Minimal GitHub REST client: one authenticated session, typed errors, and only the endpoints the swarm uses.
from __future__ import annotations
import logging
import time
from typing import Any
from urllib.parse import quote
import requests
logger = logging.getLogger(__name__)
API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT_SECONDS = 30
class GitHubError(Exception):
    # Raised for any non-2xx GitHub response; keeps the status code so callers can branch on 404/409/422.
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        # Stores the HTTP status and parsed body next to the message.
        super().__init__(message)
        self.status = status
        self.payload = payload
class GitHubAuthError(GitHubError):
    # Raised when the token is missing, invalid, or lacks the permission a call needs.
    pass
class GitHubClient:
    # Thin wrapper over the REST API; the token lives only on the session headers and is never logged.
    def __init__(self, token: str = "", api_url: str = "https://api.github.com", session: requests.Session | None = None):
        # Builds the session with the API version header and, when given, the bearer token.
        self.api_url = api_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "agent-swarm",
        })
        self.authenticated = bool(token)
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
    def request(self, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs) -> Any:
        # Sends one request and returns the decoded JSON body, raising GitHubError on anything unexpected.
        url = f"{self.api_url}{path}"
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub {method} {path} failed: {exc}") from exc
        if response.status_code in expected:
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:500]
        message = payload.get("message") if isinstance(payload, dict) else payload
        error_cls = GitHubAuthError if response.status_code in (401, 403) else GitHubError
        # For fine-grained tokens GitHub names the permission the call needed, e.g. "contents=write".
        needed = response.headers.get("X-Accepted-GitHub-Permissions", "") if response.status_code == 403 else ""
        hint = f" (token needs: {needed})" if needed else ""
        raise error_cls(f"GitHub {method} {path} -> {response.status_code}: {message}{hint}", response.status_code, payload)
    # --- repositories ---------------------------------------------------------------
    def get_repo(self, full_name: str) -> dict:
        # Repository metadata, including default_branch, private, archived and (when authenticated) permissions.
        return self.request("GET", f"/repos/{full_name}")
    def get_authenticated_user(self) -> dict:
        # The account the token belongs to.
        return self.request("GET", "/user")
    def create_fork(self, full_name: str) -> dict:
        # Forks the repository into the token owner's account (or returns the existing fork).
        return self.request("POST", f"/repos/{full_name}/forks", expected=(200, 202), json={"default_branch_only": True})
    def wait_for_ref(self, full_name: str, branch: str, attempts: int = 10, delay: float = 3.0) -> None:
        # Forks are created asynchronously; polls until the branch ref is readable.
        for attempt in range(attempts):
            try:
                self.get_ref(full_name, branch)
                return
            except GitHubError as exc:
                if exc.status not in (404, 409) or attempt == attempts - 1:
                    raise
            time.sleep(delay)
    def merge_upstream(self, full_name: str, branch: str) -> None:
        # Fast-forwards a fork's branch to its upstream so the base commit exists in the fork.
        self.request("POST", f"/repos/{full_name}/merge-upstream", json={"branch": branch})
    # --- git data ----------------------------------------------------------------------
    def get_ref(self, full_name: str, branch: str) -> dict:
        # The ref object for refs/heads/<branch>.
        return self.request("GET", f"/repos/{full_name}/git/ref/heads/{quote(branch, safe='/')}")
    def branch_exists(self, full_name: str, branch: str) -> bool:
        # True when refs/heads/<branch> already exists.
        try:
            self.get_ref(full_name, branch)
        except GitHubError as exc:
            if exc.status == 404:
                return False
            raise
        return True
    def get_commit(self, full_name: str, sha: str) -> dict:
        # A git commit object (used to find its tree sha).
        return self.request("GET", f"/repos/{full_name}/git/commits/{sha}")
    def create_tree(self, full_name: str, base_tree: str, entries: list[dict]) -> dict:
        # Creates a tree layered over base_tree; entries carry inline UTF-8 content.
        return self.request("POST", f"/repos/{full_name}/git/trees", json={"base_tree": base_tree, "tree": entries})
    def create_commit(self, full_name: str, message: str, tree: str, parents: list[str]) -> dict:
        # Creates a commit object; it is not reachable from any branch until a ref points at it.
        return self.request("POST", f"/repos/{full_name}/git/commits", json={"message": message, "tree": tree, "parents": parents})
    def create_ref(self, full_name: str, branch: str, sha: str) -> dict:
        # Creates refs/heads/<branch> at sha -- the API equivalent of pushing a new branch.
        return self.request("POST", f"/repos/{full_name}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
    # --- pull requests --------------------------------------------------------------------
    def create_pull_request(self, full_name: str, *, title: str, body: str, head: str, base: str, draft: bool = False) -> dict:
        # Opens a PR from head (a branch, or "owner:branch" for a fork) into base.
        return self.request("POST", f"/repos/{full_name}/pulls", json={
            "title": title, "body": body, "head": head, "base": base,
            "draft": draft, "maintainer_can_modify": True,
        })
    def get_pull_request(self, full_name: str, number: int) -> dict:
        # One PR, including its state and merged flag.
        return self.request("GET", f"/repos/{full_name}/pulls/{number}")
    def update_pull_request(self, full_name: str, number: int, **fields) -> dict:
        # Edits a PR's title/body/state.
        return self.request("PATCH", f"/repos/{full_name}/pulls/{number}", json=fields)
    def add_labels(self, full_name: str, number: int, labels: list[str]) -> list[dict]:
        # Applies labels to an issue/PR; GitHub creates any label that doesn't exist yet.
        return self.request("POST", f"/repos/{full_name}/issues/{number}/labels", json={"labels": labels})
    def create_commit_status(self, full_name: str, sha: str, *, state: str, description: str, context: str, target_url: str = "") -> dict:
        # Attaches a commit status (shown as a check on the PR) to sha.
        payload = {"state": state, "description": description[:140], "context": context}
        if target_url:
            payload["target_url"] = target_url
        return self.request("POST", f"/repos/{full_name}/statuses/{sha}", json=payload)
    # --- actions ---------------------------------------------------------------------------
    def dispatch_workflow(self, full_name: str, workflow: str, ref: str, inputs: dict[str, str]) -> None:
        # Fires a workflow_dispatch event; GitHub answers 204 with no body.
        self.request(
            "POST",
            f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
            expected=(204,),
            json={"ref": ref, "inputs": inputs},
        )
