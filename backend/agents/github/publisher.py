# GitHub agent: turns a validated set of file changes into a new branch, one commit and a pull request -- directly when the
# token can write to the repository, otherwise from a fork in the token's account. Never touches the default branch.
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from ..services.safety import scan_changes
from .client import GitHubClient, GitHubError
from .repo_url import RepoRef
logger = logging.getLogger(__name__)
MAX_BRANCH_SUFFIX_ATTEMPTS = 5
STATUS_CONTEXT = "agent-swarm/validation"
class PublishError(Exception):
    # Raised when the PR can't be created; the message is safe to show the user.
    pass
@dataclass
class FileChange:
    # Final content for one file, with its git mode carried over from the original when it existed.
    path: str
    content: str
    mode: str = "100644"
@dataclass
class PublishRequest:
    # Everything the publisher needs, assembled by the pipeline from the agents' outputs.
    repo: RepoRef
    task_id: int
    base_branch: str
    base_sha: str
    changes: list[FileChange]
    title: str
    body: str
    commit_message: str
    branch_hint: str = ""
    labels: list[str] = field(default_factory=list)
    validation_state: str = "success"
    validation_description: str = ""
    target_url: str = ""
@dataclass
class PublishResult:
    # What was created on GitHub.
    branch: str
    commit_sha: str
    pr_url: str
    pr_number: int
    head_repo: str
    mode: str
    labels_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    access: dict = field(default_factory=dict)
class _WriteDenied(Exception):
    # Internal: a git-data write got 403, i.e. the token may not write to that repository.
    def __init__(self, error: GitHubError):
        # Keeps the original GitHub error for the message.
        super().__init__(str(error))
        self.error = error
def _token_write_message(full_name: str, error: GitHubError | None, *, fork_hint: bool) -> str:
    # How to fix a token that can read but not write the target repository.
    detail = f" ({error})" if error else ""
    fix = (
        f"The GitHub token is not allowed to write to {full_name}{detail}. Edit the token at "
        "https://github.com/settings/personal-access-tokens, give it access to this repository, and set "
        "'Contents' and 'Pull requests' to 'Read and write'. Then click Retry."
    )
    if fork_hint:
        fix += " Or set PR_ALLOW_FORKS=true to open the PR from a fork instead."
    return fix
def make_branch_name(prefix: str, task_id: int, hint: str) -> str:
    # Builds "<prefix>/task-<id>-<slug>", keeping only characters git and GitHub both accept.
    slug = re.sub(r"[^a-z0-9]+", "-", (hint or "").lower()).strip("-")[:40].rstrip("-")
    prefix = re.sub(r"[^A-Za-z0-9._/-]+", "-", prefix).strip("/-") or "agent-swarm"
    return f"{prefix}/task-{task_id}" + (f"-{slug}" if slug else "")
class PullRequestPublisher:
    # Validates the target repository and creates branch, commit and PR through the REST API.
    def __init__(
        self,
        client: GitHubClient,
        *,
        branch_prefix: str = "agent-swarm",
        allow_fork: bool = False,
        allowed_owners: list[str] | None = None,
    ):
        # Stores the client and the policy knobs from settings.
        self.client = client
        self.branch_prefix = branch_prefix
        self.allow_fork = allow_fork
        self.allowed_owners = [o.lower() for o in (allowed_owners or [])]
    def validate_target(self, repo: RepoRef) -> dict:
        # Confirms the repo exists, is allowed, and is not archived; returns its metadata.
        if self.allowed_owners and repo.owner.lower() not in self.allowed_owners:
            raise PublishError(f"Repository owner {repo.owner!r} is not in ALLOWED_REPO_OWNERS")
        try:
            info = self.client.get_repo(repo.full_name)
        except GitHubError as exc:
            if exc.status == 404:
                raise PublishError(f"Repository {repo.full_name} was not found or is not visible to the token") from exc
            raise PublishError(f"Could not read repository {repo.full_name}: {exc}") from exc
        if info.get("archived"):
            raise PublishError(f"Repository {repo.full_name} is archived and cannot accept pull requests")
        return info
    def publish(self, req: PublishRequest) -> PublishResult:
        # GitHub agent: decide direct vs fork from the token's real write access, push the branch, open the PR.
        #   write access  -> branch + PR on the target repo
        #   no access     -> fork into the token's account, push the branch there, PR fork:branch -> upstream
        if not req.changes:
            raise PublishError("No file changes to commit")
        findings = scan_changes({c.path: c.content for c in req.changes})
        if findings:
            raise PublishError("Refusing to commit unsafe changes: " + "; ".join(f.as_issue() for f in findings))
        info = self.validate_target(req.repo)
        default_branch = info.get("default_branch") or req.base_branch
        warnings: list[str] = []
        access = self._access_check(req.repo, info)
        wanted = make_branch_name(self.branch_prefix, req.task_id, req.branch_hint or req.title)
        mode = "fork"
        if access["account_can_push"]:
            try:
                branch, commit_sha = self._push(req.repo.full_name, req, wanted, default_branch)
                mode = "direct"
            except _WriteDenied as exc:
                # The account may push, but this token may not (e.g. a fine-grained token with read-only Contents).
                access["direct_write_denied"] = True
                if access["owns_repo"] or not self.allow_fork:
                    raise PublishError(_token_write_message(req.repo.full_name, exc.error, fork_hint=not self.allow_fork)) from exc
                warnings.append(f"The token can't write to {req.repo.full_name} ({exc.error.status}); opened the PR from a fork instead")
        elif not self.allow_fork:
            raise PublishError(
                f"The GitHub account behind the token has no write access to {req.repo.full_name}. "
                "Set PR_ALLOW_FORKS=true to fork it and open the pull request from the fork."
            )
        elif access["owns_repo"]:
            raise PublishError(_token_write_message(req.repo.full_name, None, fork_hint=False))
        if mode == "fork":
            head_repo = self._prepare_fork(req, warnings)
            try:
                branch, commit_sha = self._push(head_repo, req, wanted, default_branch)
            except _WriteDenied as exc:
                raise PublishError(
                    f"The fork {head_repo} was created, but the token can't write to it ({exc.error}). A fine-grained "
                    "token needs 'All repositories' access (the fork is a new repository) with 'Contents' set to "
                    "'Read and write'; a classic token needs the 'public_repo' scope."
                ) from exc
        else:
            head_repo = req.repo.full_name
        access["decision"] = mode
        head = branch if mode == "direct" else f"{head_repo.split('/')[0]}:{branch}"
        try:
            pr = self.client.create_pull_request(
                req.repo.full_name, title=req.title, body=req.body, head=head, base=req.base_branch,
            )
        except GitHubError as exc:
            if mode == "fork" and exc.status == 403:
                raise PublishError(
                    f"Branch {branch} was pushed to the fork {head_repo}, but GitHub refused to open the pull request on "
                    f"{req.repo.full_name} ({exc}). Fine-grained tokens can be blocked from opening pull requests on "
                    "repositories outside their owner; a classic token with the 'public_repo' scope can. You can also "
                    f"open it by hand: https://github.com/{req.repo.full_name}/compare/{req.base_branch}...{head}"
                ) from exc
            raise PublishError(f"Branch {branch} was pushed, but opening the pull request failed: {exc}") from exc
        result = PublishResult(
            branch=branch,
            commit_sha=commit_sha,
            pr_url=pr["html_url"],
            pr_number=pr["number"],
            head_repo=head_repo,
            mode=mode,
            warnings=warnings,
            access=access,
        )
        if mode == "direct":
            self._apply_labels(req, result)
            self._set_status(req, result)
        elif req.labels:
            warnings.append("Labels skipped: the token has no write access to the upstream repository")
        return result
    def _access_check(self, repo: RepoRef, info: dict) -> dict:
        # Who the token acts as and whether that account may push. The account's permission is only a first
        # signal: for fine-grained tokens the real answer comes from the first write (see publish()).
        login = ""
        try:
            login = (self.client.get_authenticated_user() or {}).get("login", "")
        except GitHubError:
            pass
        return {
            "token_user": login,
            "owns_repo": bool(login) and login.lower() == repo.owner.lower(),
            "account_can_push": bool((info.get("permissions") or {}).get("push")),
            "direct_write_denied": False,
            "decision": "",
        }
    def _push(self, head_repo: str, req: PublishRequest, wanted: str, default_branch: str) -> tuple[str, str]:
        # Picks a free branch name in head_repo and commits the changes onto it; returns (branch, commit sha).
        branch = self._unique_branch(head_repo, wanted)
        if branch in {default_branch, req.base_branch}:
            raise PublishError("Refusing to write to the repository's default branch")
        return branch, self._commit(head_repo, req, branch)
    def _prepare_fork(self, req: PublishRequest, warnings: list[str]) -> str:
        # Forks the target into the token's account (or reuses the existing fork), waits for it, and syncs its base branch.
        try:
            fork = self.client.create_fork(req.repo.full_name)
            fork_name = fork["full_name"]
            self.client.wait_for_ref(fork_name, req.base_branch)
        except GitHubError as exc:
            if exc.status == 403:
                raise PublishError(
                    f"The token isn't allowed to fork {req.repo.full_name} ({exc}). A classic token needs the "
                    "'public_repo' scope; a fine-grained token needs 'All repositories' access with 'Administration', "
                    "'Contents' and 'Pull requests' set to 'Read and write'."
                ) from exc
            raise PublishError(f"Could not fork {req.repo.full_name}: {exc}") from exc
        try:
            self.client.merge_upstream(fork_name, req.base_branch)
        except GitHubError as exc:
            warnings.append(f"Could not sync fork {fork_name} with upstream: {exc}")
        return fork_name
    def _unique_branch(self, head_repo: str, wanted: str) -> str:
        # Returns wanted, or wanted-2, wanted-3... if earlier runs already used the name.
        for i in range(1, MAX_BRANCH_SUFFIX_ATTEMPTS + 1):
            candidate = wanted if i == 1 else f"{wanted}-{i}"
            try:
                exists = self.client.branch_exists(head_repo, candidate)
            except GitHubError as exc:
                raise PublishError(f"Could not check branch {candidate}: {exc}") from exc
            if not exists:
                return candidate
        raise PublishError(f"Branch names {wanted} .. {wanted}-{MAX_BRANCH_SUFFIX_ATTEMPTS} are all taken")
    def _commit(self, head_repo: str, req: PublishRequest, branch: str) -> str:
        # Layers the changed files over the base commit's tree, commits, and points a new branch at it.
        try:
            base_commit = self.client.get_commit(head_repo, req.base_sha)
        except GitHubError as exc:
            raise PublishError(f"Base commit {req.base_sha[:12]} is not available in {head_repo}: {exc}") from exc
        entries = [
            {"path": c.path, "mode": c.mode, "type": "blob", "content": c.content}
            for c in req.changes
        ]
        try:
            tree = self.client.create_tree(head_repo, base_commit["tree"]["sha"], entries)
            commit = self.client.create_commit(head_repo, req.commit_message, tree["sha"], [req.base_sha])
            self.client.create_ref(head_repo, branch, commit["sha"])
        except GitHubError as exc:
            if exc.status == 403:
                # repo.permissions.push reflects the *account*; a token that can't write only shows up here.
                raise _WriteDenied(exc) from exc
            raise PublishError(f"Could not push branch {branch} to {head_repo}: {exc}") from exc
        return commit["sha"]
    def _apply_labels(self, req: PublishRequest, result: PublishResult) -> None:
        # Labels the PR; a failure here is a warning, not a reason to call the PR failed.
        if not req.labels:
            return
        try:
            self.client.add_labels(req.repo.full_name, result.pr_number, req.labels)
            result.labels_applied = list(req.labels)
        except GitHubError as exc:
            result.warnings.append(f"Could not apply labels: {exc}")
    def _set_status(self, req: PublishRequest, result: PublishResult) -> None:
        # Publishes the Tester/Reviewer verdict as a commit status so it shows up in the PR's checks.
        try:
            self.client.create_commit_status(
                req.repo.full_name,
                result.commit_sha,
                state=req.validation_state,
                description=req.validation_description or "Agent Swarm validation",
                context=STATUS_CONTEXT,
                target_url=req.target_url,
            )
        except GitHubError as exc:
            result.warnings.append(f"Could not set commit status: {exc}")
