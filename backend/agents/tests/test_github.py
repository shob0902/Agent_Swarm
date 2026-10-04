# Tests for the GitHub package: URL parsing, the REST client, the PR publisher and the PR body.
from unittest import mock
from django.test import SimpleTestCase
from agents.github.client import GitHubAuthError, GitHubClient, GitHubError
from agents.github.pr_body import build_commit_message, build_pr_body, build_pr_title
from agents.github.publisher import FileChange, PublishError, PublishRequest, PullRequestPublisher, make_branch_name
from agents.github.repo_url import InvalidRepoURL, is_valid_github_url, parse_github_url
from .helpers import FakeGitHubClient
class RepoUrlTests(SimpleTestCase):
    # Only plain https://github.com/<owner>/<repo> URLs are accepted.
    def test_accepts_plain_and_dot_git_urls(self):
        # Trailing slash and .git suffix are tolerated.
        for url in ("https://github.com/acme/app", "https://github.com/acme/app/", "https://github.com/acme/app.git", " https://github.com/a-b/c.d_e "):
            self.assertTrue(is_valid_github_url(url), url)
        self.assertEqual(parse_github_url("https://github.com/acme/app.git").full_name, "acme/app")
    def test_rejects_everything_else(self):
        # Other hosts, schemes, extra segments, credentials and shell metacharacters are refused.
        for url in (
            "http://github.com/acme/app",
            "https://gitlab.com/acme/app",
            "https://github.com/acme",
            "https://github.com/acme/app/tree/main",
            "https://token@github.com/acme/app",
            "https://github.com/acme/app;rm -rf /",
            "https://github.com/acme/..",
            "file:///etc/passwd",
            "",
        ):
            self.assertFalse(is_valid_github_url(url), url)
        with self.assertRaises(InvalidRepoURL):
            parse_github_url("https://github.com/acme")
    def test_clone_url_has_no_credentials(self):
        # The clone URL is always anonymous.
        self.assertEqual(parse_github_url("https://github.com/acme/app").clone_url, "https://github.com/acme/app.git")
class GitHubClientTests(SimpleTestCase):
    # The client raises typed errors and sends the token only as a header.
    def _client(self, status_code, payload=None, headers=None):
        # Client whose session returns one canned response.
        session = mock.Mock()
        session.headers = {}
        response = mock.Mock(status_code=status_code, content=b"{}" if payload is not None else b"", headers=headers or {})
        response.json.return_value = payload
        session.request.return_value = response
        return GitHubClient("secret-token", session=session), session
    def test_sets_auth_header(self):
        # Bearer token and API version headers are set on the session.
        client, session = self._client(200, {"ok": True})
        self.assertEqual(session.headers["Authorization"], "Bearer secret-token")
        self.assertEqual(client.get_repo("acme/app"), {"ok": True})
    def test_auth_errors_are_typed(self):
        # 401/403 become GitHubAuthError with the status preserved.
        client, _ = self._client(403, {"message": "Resource not accessible"})
        with self.assertRaises(GitHubAuthError) as ctx:
            client.get_repo("acme/app")
        self.assertEqual(ctx.exception.status, 403)
    def test_403_names_missing_fine_grained_permission(self):
        # GitHub's X-Accepted-GitHub-Permissions header is surfaced in the error.
        client, _ = self._client(403, {"message": "Resource not accessible by personal access token"}, {"X-Accepted-GitHub-Permissions": "contents=write"})
        with self.assertRaisesMessage(GitHubAuthError, "token needs: contents=write"):
            client.create_tree("acme/app", "t", [])
    def test_dispatch_expects_204(self):
        # workflow_dispatch succeeds on 204 and posts only the inputs given.
        client, session = self._client(204)
        client.dispatch_workflow("me/Agent_Swarm", "agent-swarm.yml", "main", {"task_id": "5"})
        _, kwargs = session.request.call_args
        self.assertEqual(kwargs["json"], {"ref": "main", "inputs": {"task_id": "5"}})
    def test_branch_exists_false_on_404(self):
        # A missing ref is not an error.
        client, _ = self._client(404, {"message": "Not Found"})
        self.assertFalse(client.branch_exists("acme/app", "x"))
def _request(**overrides) -> PublishRequest:
    # A valid publish request with one changed file.
    values = dict(
        repo=parse_github_url("https://github.com/acme/app"),
        task_id=12,
        base_branch="main",
        base_sha="abc123",
        changes=[FileChange("app/cache.py", "CACHE = {}\n")],
        title="Add response caching",
        body="body",
        commit_message="Add response caching",
        labels=["agent-swarm"],
    )
    values.update(overrides)
    return PublishRequest(**values)
class PublisherTests(SimpleTestCase):
    # Branch -> commit -> PR flow, guard rails, and fork mode.
    def test_direct_mode_creates_branch_commit_pr_labels_and_status(self):
        # With push access everything happens on the target repo, on a new branch.
        client = FakeGitHubClient(push=True)
        result = PullRequestPublisher(client).publish(_request())
        self.assertEqual(result.mode, "direct")
        self.assertEqual(result.branch, "agent-swarm/task-12-add-response-caching")
        self.assertEqual(result.pr_number, 7)
        self.assertEqual(result.labels_applied, ["agent-swarm"])
        names = client.call_names()
        self.assertEqual(
            names[names.index("get_commit"):],
            ["get_commit", "create_tree", "create_commit", "create_ref", "create_pull_request", "add_labels", "create_commit_status"],
        )
        tree_call = next(c for c in client.calls if c[0] == "create_tree")
        self.assertEqual(tree_call[2], "tree-abc123")
        self.assertEqual(tree_call[3][0]["path"], "app/cache.py")
        commit_call = next(c for c in client.calls if c[0] == "create_commit")
        self.assertEqual(commit_call[4], ["abc123"])
        pr_call = next(c for c in client.calls if c[0] == "create_pull_request")
        self.assertEqual(pr_call[3:], ("agent-swarm/task-12-add-response-caching", "main"))
    def test_never_updates_existing_refs(self):
        # Only create_ref is ever used -- no call path can move an existing branch such as main.
        client = FakeGitHubClient(push=True)
        PullRequestPublisher(client).publish(_request())
        self.assertNotIn("update_ref", client.call_names())
        ref_calls = [c for c in client.calls if c[0] == "create_ref"]
        self.assertEqual(len(ref_calls), 1)
        self.assertNotEqual(ref_calls[0][2], "main")
    def test_branch_name_gets_suffix_when_taken(self):
        # Re-runs don't collide with earlier branches.
        taken = {"agent-swarm/task-12-add-response-caching", "agent-swarm/task-12-add-response-caching-2"}
        result = PullRequestPublisher(FakeGitHubClient(existing_branches=taken)).publish(_request())
        self.assertEqual(result.branch, "agent-swarm/task-12-add-response-caching-3")
    def test_refuses_default_branch_as_head(self):
        # A prefix that collapses to the default branch name is rejected.
        publisher = PullRequestPublisher(FakeGitHubClient(), branch_prefix="agent-swarm")
        with mock.patch("agents.github.publisher.make_branch_name", return_value="main"):
            with self.assertRaisesMessage(PublishError, "default branch"):
                publisher.publish(_request())
    def test_without_push_access_and_forks_disabled_fails_clearly(self):
        # No silent fallback: the error explains how to fix it.
        with self.assertRaisesMessage(PublishError, "PR_ALLOW_FORKS"):
            PullRequestPublisher(FakeGitHubClient(push=False)).publish(_request())
    def test_fork_mode_opens_cross_repo_pr_without_labels(self):
        # The branch goes to the fork and the PR head is "fork-owner:branch".
        client = FakeGitHubClient(push=False)
        result = PullRequestPublisher(client, allow_fork=True).publish(_request())
        self.assertEqual(result.mode, "fork")
        self.assertEqual(result.head_repo, "swarm-bot/app")
        pr_call = next(c for c in client.calls if c[0] == "create_pull_request")
        self.assertEqual(pr_call[1], "acme/app")
        self.assertEqual(pr_call[3], "swarm-bot:agent-swarm/task-12-add-response-caching")
        self.assertNotIn("add_labels", client.call_names())
        self.assertTrue(any("Labels skipped" in w for w in result.warnings))
    def test_refuses_secrets_and_protected_paths(self):
        # Defense in depth: even an approved change is not committed if it contains a credential or touches CI.
        for change in (FileChange("config.py", "TOKEN = 'ghp_" + "a" * 36 + "'"), FileChange(".github/workflows/ci.yml", "on: push")):
            client = FakeGitHubClient()
            with self.assertRaisesMessage(PublishError, "unsafe"):
                PullRequestPublisher(client).publish(_request(changes=[change]))
            self.assertEqual(client.calls, [])
    def test_allowed_owners_and_archived_repos(self):
        # Owner allow-list and archived repos are enforced before anything is written.
        with self.assertRaisesMessage(PublishError, "ALLOWED_REPO_OWNERS"):
            PullRequestPublisher(FakeGitHubClient(), allowed_owners=["someone-else"]).publish(_request())
        with self.assertRaisesMessage(PublishError, "archived"):
            PullRequestPublisher(FakeGitHubClient(archived=True)).publish(_request())
    def test_direct_mode_records_access_decision(self):
        # The trace shows who the token is and why the direct path was taken.
        result = PullRequestPublisher(FakeGitHubClient(push=True)).publish(_request())
        self.assertEqual(result.access, {"token_user": "swarm-bot", "owns_repo": False, "account_can_push": True, "direct_write_denied": False, "decision": "direct"})
    def test_read_only_token_falls_back_to_fork(self):
        # The account can push but the token can't write: fork, push there, PR fork:branch -> upstream.
        client = FakeGitHubClient(push=True, deny_write_on={"acme/app"})
        result = PullRequestPublisher(client, allow_fork=True).publish(_request())
        self.assertEqual((result.mode, result.head_repo), ("fork", "swarm-bot/app"))
        self.assertTrue(result.access["direct_write_denied"])
        self.assertEqual(result.access["decision"], "fork")
        self.assertTrue(any("from a fork instead" in w for w in result.warnings))
        pr_call = next(c for c in client.calls if c[0] == "create_pull_request")
        self.assertEqual((pr_call[1], pr_call[3]), ("acme/app", "swarm-bot:agent-swarm/task-12-add-response-caching"))
        refs = [c for c in client.calls if c[0] == "create_ref"]
        self.assertEqual([r[1] for r in refs], ["swarm-bot/app"])
    def test_own_repo_with_read_only_token_never_forks(self):
        # GitHub can't fork your own repo into your own account, so the fix is the token's permissions.
        client = FakeGitHubClient(push=True, login="acme", deny_write_on={"acme/app"})
        with self.assertRaisesMessage(PublishError, "'Contents' and 'Pull requests' to 'Read and write'"):
            PullRequestPublisher(client, allow_fork=True).publish(_request())
        self.assertNotIn("create_fork", client.call_names())
    def test_fork_permission_error_explains_token_requirements(self):
        # A token that may not create forks gets the scopes it needs spelled out.
        client = FakeGitHubClient(push=False, fail_on="create_fork", fail_status=403)
        with self.assertRaisesMessage(PublishError, "public_repo"):
            PullRequestPublisher(client, allow_fork=True).publish(_request())
    def test_fork_write_denied_explains_all_repositories_access(self):
        # Fine-grained tokens limited to selected repos can't write to the brand-new fork.
        client = FakeGitHubClient(push=False, deny_write_on={"swarm-bot/app"})
        with self.assertRaisesMessage(PublishError, "All repositories"):
            PullRequestPublisher(client, allow_fork=True).publish(_request())
    def test_upstream_pr_refused_gives_manual_compare_link(self):
        # The branch is in the fork; if GitHub refuses the PR, the user gets a ready-made compare URL.
        client = FakeGitHubClient(push=False, fail_on="create_pull_request", fail_status=403)
        with self.assertRaisesMessage(PublishError, "https://github.com/acme/app/compare/main...swarm-bot:agent-swarm/task-12-add-response-caching"):
            PullRequestPublisher(client, allow_fork=True).publish(_request())
    def test_label_failure_is_only_a_warning(self):
        # The PR still counts as created.
        result = PullRequestPublisher(FakeGitHubClient(fail_on="add_labels")).publish(_request())
        self.assertEqual(result.pr_number, 7)
        self.assertTrue(any("labels" in w for w in result.warnings))
    def test_read_only_token_gets_actionable_error(self):
        # repo.permissions.push can say True for a fine-grained token that can't write; the 403 explains the fix.
        client = FakeGitHubClient(push=True)
        client.create_tree = mock.Mock(side_effect=GitHubAuthError("GitHub POST /repos/acme/app/git/trees -> 403: Resource not accessible by personal access token", 403))
        with self.assertRaisesMessage(PublishError, "'Contents' and 'Pull requests' to 'Read and write'"):
            PullRequestPublisher(client).publish(_request())
        self.assertNotIn("create_ref", client.call_names())
    def test_pr_failure_after_push_is_reported(self):
        # The message says the branch exists so a human can open the PR by hand.
        with self.assertRaisesMessage(PublishError, "was pushed"):
            PullRequestPublisher(FakeGitHubClient(fail_on="create_pull_request")).publish(_request())
    def test_make_branch_name_is_git_safe(self):
        # Odd characters collapse into dashes and long titles are trimmed.
        name = make_branch_name("agent-swarm", 3, "Fix: crash on ünicode / spaces!!" + "x" * 80)
        self.assertRegex(name, r"^agent-swarm/task-3-[a-z0-9-]+$")
        self.assertLessEqual(len(name), len("agent-swarm/task-3-") + 40)
class PrBodyTests(SimpleTestCase):
    # The generated PR description has every section reviewers need.
    def test_body_contains_all_sections(self):
        # Objective, why, plan, files, validation, reviewer decision and the agent trace.
        body = build_pr_body(
            task_id=4,
            request="Improve API performance and add appropriate caching.",
            plan={"title": "Add caching", "summary": "Caches GET /users.", "steps": ["Add cache module", "Add tests"]},
            changed_files=[{"path": "app/cache.py", "change": "added"}, {"path": "app/api.py", "change": "modified"}],
            test_results={"status": "passed", "checks": [{"name": "pytest", "command": ["python", "-m", "pytest"], "status": "passed", "summary": "5 passed", "required": True}], "stack": ["Python", "Flask"]},
            review={"approved": True, "summary": "Looks good.", "issues": [], "suggestions": ["Add TTL config"]},
            runs=[{"agent_type": "planner", "status": "success", "retry_count": 0, "duration_ms": 1200}],
            retry_count=1,
            review_cycles=0,
            run_url="https://github.com/me/Agent_Swarm/actions/runs/1",
        )
        for expected in (
            "## 🤖 Agent Swarm Generated PR", "### Objective", "> Improve API performance", "### Why this change",
            "### Planner summary", "1. Add cache module", "`app/cache.py` (added)", "**Tests:** PASS",
            "**Reviewer:** APPROVED", "| pytest |", "5 passed", "### Reviewer decision", "Add TTL config",
            "Planner → Coder → Tester → Reviewer", "must be reviewed by a human", "[execution log]",
        ):
            self.assertIn(expected, body)
    def test_title_prefers_plan_and_truncates(self):
        # Planner title first; long request lines are cut to 72 chars.
        self.assertEqual(build_pr_title("whatever", {"title": "Add caching"}), "Add caching")
        self.assertLessEqual(len(build_pr_title("x" * 200, {})), 72)
    def test_commit_message_mentions_task_and_review(self):
        # The commit carries the summary and the human-review trailer.
        msg = build_commit_message("Add caching", {"summary": "Caches GET /users."}, 9)
        self.assertTrue(msg.startswith("Add caching\n\nCaches GET /users."))
        self.assertIn("task #9", msg)
class GitHubErrorTests(SimpleTestCase):
    # Error objects keep their status for callers to branch on.
    def test_status_preserved(self):
        # status and payload are attributes.
        exc = GitHubError("boom", 422, {"message": "x"})
        self.assertEqual((exc.status, exc.payload), (422, {"message": "x"}))
