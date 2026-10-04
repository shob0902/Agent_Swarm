# Test doubles shared across the agents test modules.
from __future__ import annotations
import itertools
import subprocess
import tempfile
from pathlib import Path
from agents.github.client import GitHubAuthError, GitHubError
from agents.pipeline.reporting import Reporter
class FakeReporter(Reporter):
    # In-memory reporter that records every task update and run, for asserting on pipeline behaviour.
    def __init__(self, task_id: int = 1, description: str = "Add caching", github_url: str = "https://github.com/acme/app", status: str = "queued"):
        # Starts with a queued task.
        super().__init__(task_id)
        self.task = {"id": task_id, "description": description, "github_url": github_url, "status": status}
        self.updates: list[dict] = []
        self.finished: dict = {}
        self._ids = itertools.count(1)
    def fetch_task(self) -> dict:
        # Returns the in-memory task.
        return dict(self.task)
    def update_task(self, **fields) -> None:
        # Records and applies the update.
        self.updates.append(fields)
        self.task.update(fields)
    def _start_run(self, **kwargs):
        # Hands out sequential ids.
        return next(self._ids)
    def _finish_run(self, run_id, **kwargs):
        # Remembers the outcome per run.
        self.finished[run_id] = kwargs
    def statuses(self) -> list[str]:
        # The sequence of status values written, in order.
        return [u["status"] for u in self.updates if "status" in u]
class FakeGitHubClient:
    # Records calls and simulates just enough of the GitHub API for the publisher.
    def __init__(
        self,
        *,
        push: bool = True,
        existing_branches: set[str] | None = None,
        archived: bool = False,
        fail_on: str | None = None,
        fail_status: int = 422,
        login: str = "swarm-bot",
        deny_write_on: set[str] | None = None,
    ):
        # Configures the account's permission, the token's identity, repos the token can't write to, and failures.
        self.push = push
        self.archived = archived
        self.existing_branches = set(existing_branches or ())
        self.fail_on = fail_on
        self.fail_status = fail_status
        self.login = login
        self.deny_write_on = set(deny_write_on or ())
        self.calls: list[tuple] = []
    def _maybe_fail(self, name: str) -> None:
        # Raises a GitHubError (GitHubAuthError for 401/403) when the test asked this call to fail.
        if self.fail_on == name:
            cls = GitHubAuthError if self.fail_status in (401, 403) else GitHubError
            raise cls(f"{name} failed", self.fail_status)
    def get_authenticated_user(self):
        # The account the token acts as.
        self.calls.append(("get_authenticated_user",))
        return {"login": self.login}
    def get_repo(self, full_name):
        # Repo metadata with the configured push permission.
        self.calls.append(("get_repo", full_name))
        return {"full_name": full_name, "default_branch": "main", "archived": self.archived, "private": False, "permissions": {"push": self.push}}
    def branch_exists(self, full_name, branch):
        # True for branches listed as existing.
        self.calls.append(("branch_exists", full_name, branch))
        return branch in self.existing_branches
    def get_commit(self, full_name, sha):
        # A commit whose tree is "tree-<sha>".
        self.calls.append(("get_commit", full_name, sha))
        return {"sha": sha, "tree": {"sha": f"tree-{sha}"}}
    def create_tree(self, full_name, base_tree, entries):
        # Echoes back a new tree sha.
        self.calls.append(("create_tree", full_name, base_tree, entries))
        if full_name in self.deny_write_on:
            raise GitHubAuthError("GitHub POST git/trees -> 403: Resource not accessible by personal access token", 403)
        self._maybe_fail("create_tree")
        return {"sha": "newtree"}
    def create_commit(self, full_name, message, tree, parents):
        # Echoes back a new commit sha.
        self.calls.append(("create_commit", full_name, message, tree, parents))
        return {"sha": "newcommit"}
    def create_ref(self, full_name, branch, sha):
        # Records the new branch.
        self.calls.append(("create_ref", full_name, branch, sha))
        self.existing_branches.add(branch)
        return {"ref": f"refs/heads/{branch}"}
    def create_fork(self, full_name):
        # Pretends the fork lands in the token's account.
        self.calls.append(("create_fork", full_name))
        self._maybe_fail("create_fork")
        return {"full_name": f"{self.login}/" + full_name.split("/")[1]}
    def wait_for_ref(self, full_name, branch, **kwargs):
        # Fork is immediately ready.
        self.calls.append(("wait_for_ref", full_name, branch))
    def merge_upstream(self, full_name, branch):
        # Records the sync.
        self.calls.append(("merge_upstream", full_name, branch))
    def create_pull_request(self, full_name, *, title, body, head, base, draft=False):
        # Returns PR #7.
        self.calls.append(("create_pull_request", full_name, title, head, base))
        self._maybe_fail("create_pull_request")
        return {"number": 7, "html_url": f"https://github.com/{full_name}/pull/7"}
    def add_labels(self, full_name, number, labels):
        # Records labels, optionally failing.
        self.calls.append(("add_labels", full_name, number, labels))
        self._maybe_fail("add_labels")
        return [{"name": label} for label in labels]
    def create_commit_status(self, full_name, sha, **kwargs):
        # Records the status.
        self.calls.append(("create_commit_status", full_name, sha, kwargs["state"]))
        return {}
    def call_names(self) -> list[str]:
        # Just the method names, in order.
        return [c[0] for c in self.calls]
def make_git_repo(files: dict[str, str]) -> str:
    # Creates a throwaway git repo with one commit containing files; returns its path.
    root = Path(tempfile.mkdtemp(prefix="agent-swarm-test-"))
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run([*git, "-C", str(root), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return str(root)
