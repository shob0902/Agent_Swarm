# Tests for the individual agents: repository analysis, Tester, Reviewer, Coder change tracking and the safety checks.
import json
import tempfile
from pathlib import Path
from unittest import mock
from django.test import SimpleTestCase, override_settings
from agents.llm_client import LLMResponse
from agents.pipeline.context import PipelineContext
from agents.sandbox import SandboxError, SandboxResult
from agents.services import reviewer, tester
from agents.services.analyzer import detect_project
from agents.services.coder import (
    MAX_FILE_CHARS,
    _apply_files_and_diff,
    _format_file_contents,
    _safe_relative_path,
    _validate_files,
    apply_files,
    summarize_changes,
)
from agents.services.common import AgentRunFailed, parse_strict_json
from agents.services.repo import cleanup_clone, head_info, reset_tracked_files
from agents.services.safety import is_blocked_path, scan_changes
from .helpers import FakeReporter, make_git_repo
def _write_tree(files: dict[str, str]) -> str:
    # Plain (non-git) temp directory with the given files.
    root = Path(tempfile.mkdtemp(prefix="agent-swarm-analyze-"))
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    return str(root)
class AnalyzerTests(SimpleTestCase):
    # Stack detection must not assume Python.
    def tearDown(self):
        # Removes the temp tree.
        cleanup_clone(getattr(self, "root", None))
    def checks(self, profile):
        # name -> (command, required, category)
        return {c.name: (c.command, c.required, c.category) for c in profile.checks}
    def test_python_flask_with_pytest_and_ruff(self):
        # requirements -> pip install into the deps dir; tests -> pytest; ruff config -> advisory lint.
        self.root = _write_tree({
            "requirements.txt": "flask==3.0\n",
            "app.py": "import flask\n",
            "tests/test_app.py": "def test_x(): pass\n",
            "pyproject.toml": "[tool.ruff]\nline-length = 100\n",
        })
        profile = detect_project(self.root)
        self.assertEqual(profile.languages, ["Python"])
        self.assertIn("Flask", profile.frameworks)
        self.assertEqual(profile.install_steps[0].command[-2:], ["-r", "requirements.txt"])
        self.assertIn("--target", profile.install_steps[0].command)
        checks = self.checks(profile)
        self.assertEqual(checks["pytest"][1:], (True, "test"))
        self.assertEqual(checks["ruff"][1:], (False, "lint"))
        self.assertTrue(profile.has_tests)
    def test_node_with_lockfile_build_test_lint(self):
        # npm ci, build, npm test, advisory lint; the npm-init placeholder test script is ignored elsewhere.
        self.root = _write_tree({
            "package.json": json.dumps({"scripts": {"build": "vite build", "test": "vitest run", "lint": "eslint ."}, "dependencies": {"react": "18", "express": "4"}}),
            "package-lock.json": "{}",
            "src/index.js": "",
        })
        profile = detect_project(self.root)
        self.assertEqual(profile.languages, ["JavaScript"])
        self.assertEqual(set(profile.frameworks), {"React", "Express"})
        self.assertEqual(profile.install_steps[0].command[:2], ["npm", "ci"])
        checks = self.checks(profile)
        self.assertEqual(checks["build"][0], ["npm", "run", "build", "--silent"])
        self.assertEqual(checks["npm test"][1:], (True, "test"))
        self.assertEqual(checks["lint"][1:], (False, "lint"))
    def test_typescript_without_build_uses_tsc_and_ignores_placeholder_test(self):
        # tsconfig + typescript dependency -> tsc --noEmit; "no test specified" is not a test suite.
        self.root = _write_tree({
            "package.json": json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}, "devDependencies": {"typescript": "5"}}),
            "tsconfig.json": "{}",
            "yarn.lock": "",
            "src/a.ts": "",
        })
        profile = detect_project(self.root)
        self.assertEqual(profile.languages, ["TypeScript"])
        self.assertEqual(profile.package_managers, ["yarn"])
        checks = self.checks(profile)
        self.assertIn("typecheck", checks)
        self.assertNotIn("npm test", checks)
        self.assertFalse(profile.has_tests)
    def test_unknown_stack_has_no_checks(self):
        # A docs-only repo gets no commands at all.
        self.root = _write_tree({"README.md": "# hi"})
        profile = detect_project(self.root)
        self.assertEqual((profile.languages, profile.checks, profile.install_steps), ([], [], []))
        self.assertIn("no test suite", profile.summary())
def _sandbox(results: dict):
    # Fake run_in_sandbox keyed by the first distinctive command word.
    calls = []
    def fake(repo_path, command, timeout=None, environment=None, allow_network=False):
        # Records the call and returns the scripted result.
        calls.append({"command": command, "allow_network": allow_network, "environment": environment})
        key = next((k for k in results if k in " ".join(command)), None)
        exit_code, logs = results.get(key, (0, "ok"))
        return SandboxResult(exit_code=exit_code, logs=logs)
    return fake, calls
@override_settings(SANDBOX_INSTALL_DEPENDENCIES=True)
class TesterTests(SimpleTestCase):
    # The Tester decides pass/fail from required checks, installs deps once, and never gives tests network.
    def setUp(self):
        # Small Python repo with tests and a lint config.
        self.root = _write_tree({
            "requirements.txt": "flask\n",
            "app.py": "x = 1\n",
            "test_app.py": "def test_x(): pass\n",
            ".flake8": "[flake8]\n",
        })
        self.ctx = PipelineContext(task_id=1, description="d", github_url="https://github.com/a/b", reporter=FakeReporter(), local_path=self.root)
    def tearDown(self):
        # Removes the temp tree.
        cleanup_clone(self.root)
    def test_pass_with_advisory_lint_failure(self):
        # Lint failing alone doesn't fail the run; only the install step gets network.
        fake, calls = _sandbox({"pytest": (0, "3 passed in 0.10s"), "flake8": (1, "E501 line too long")})
        with mock.patch.object(tester, "run_in_sandbox", side_effect=fake):
            result = tester.run_tester(self.ctx, ["app.py"])
        self.assertTrue(result.passed)
        self.assertEqual(result.status, "passed")
        by_name = {c.name: c for c in result.checks}
        self.assertEqual(by_name["pytest"].summary, "3 passed")
        self.assertEqual(by_name["flake8"].status, "failed")
        self.assertEqual(by_name["compile"].command, ["python", "-m", "py_compile", "app.py"])
        self.assertEqual([c["allow_network"] for c in calls], [True, False, False, False])
        self.assertIn("PYTHONPATH", calls[1]["environment"])
    def test_required_failure_produces_coder_feedback(self):
        # A failing test run is a failure with the log as feedback.
        fake, _ = _sandbox({"pytest": (1, "FAILED test_app.py::test_x - assert 1 == 2\n1 failed in 0.1s")})
        with mock.patch.object(tester, "run_in_sandbox", side_effect=fake):
            result = tester.run_tester(self.ctx, ["app.py"])
        self.assertFalse(result.passed)
        self.assertIn("assert 1 == 2", result.output)
    def test_dependencies_installed_once_until_manifest_changes(self):
        # Retries reuse the install; editing requirements.txt triggers a reinstall.
        fake, calls = _sandbox({})
        with mock.patch.object(tester, "run_in_sandbox", side_effect=fake):
            tester.run_tester(self.ctx, ["app.py"])
            tester.run_tester(self.ctx, ["app.py"])
            Path(self.root, "requirements.txt").write_text("flask\nrequests\n", encoding="utf-8")
            tester.run_tester(self.ctx, ["requirements.txt"])
        installs = [c for c in calls if "install" in c["command"]]
        self.assertEqual(len(installs), 2)
    def test_install_failure_blocks(self):
        # If deps don't install, checks are not run and the run fails.
        fake, calls = _sandbox({"install": (1, "No matching distribution")})
        with mock.patch.object(tester, "run_in_sandbox", side_effect=fake):
            result = tester.run_tester(self.ctx, [])
        self.assertFalse(result.passed)
        self.assertEqual(len(calls), 1)
    def test_no_tests_collected_is_skipped_not_failed(self):
        # pytest exit 5 means "no tests", which shouldn't block a PR.
        fake, _ = _sandbox({"pytest": (5, "no tests ran in 0.01s")})
        with mock.patch.object(tester, "run_in_sandbox", side_effect=fake):
            result = tester.run_tester(self.ctx, [])
        self.assertTrue(result.passed)
        self.assertEqual(result.status, "skipped")
    def test_sandbox_outage_aborts_instead_of_retrying(self):
        # Docker being down is infrastructure, not something the Coder can fix.
        with mock.patch.object(tester, "run_in_sandbox", side_effect=SandboxError("Docker unreachable")):
            with self.assertRaises(AgentRunFailed):
                tester.run_tester(self.ctx, [])
def _llm(payload) -> LLMResponse:
    # Fake LLM response carrying payload as JSON text.
    return LLMResponse(text=json.dumps(payload) if not isinstance(payload, str) else payload, provider="groq", model="m", raw={})
class ReviewerTests(SimpleTestCase):
    # Structured output, plus deterministic vetoes the model can't override.
    def setUp(self):
        # Context without a real repo; the reviewer only reads the change summary.
        self.ctx = PipelineContext(task_id=1, description="Add caching", github_url="https://github.com/a/b", reporter=FakeReporter())
        self.changes = {"diff": "diff", "changed_files": [{"path": "app.py", "change": "modified"}], "contents": {"app.py": "CACHE = {}\n"}}
        self.passed = tester.TestResult(passed=True, output="", exit_code=0, status="passed")
    def review(self, payload, changes=None, test_result=None):
        # Runs the reviewer against a canned model response.
        with mock.patch.object(reviewer.llm_client, "call_llm", return_value=_llm(payload)):
            return reviewer.run_reviewer(self.ctx, {"steps": ["x"]}, changes or self.changes, test_result or self.passed)
    def test_structured_output(self):
        # The verdict has the documented shape.
        verdict = self.review({
            "approved": True, "summary": "Implements caching.", "issues": [], "suggestions": ["Add TTL"],
            "checks": {"implements_request": True, "regression_risk": "low", "bogus": 1},
        })
        self.assertEqual(set(verdict), {"approved", "summary", "issues", "suggestions", "checks"})
        self.assertTrue(verdict["approved"])
        self.assertEqual(verdict["checks"], {"implements_request": True, "regression_risk": "low"})
    def test_legacy_concerns_key_still_parsed(self):
        # Older-style {"approved", "concerns"} answers still work.
        verdict = self.review({"approved": False, "concerns": ["Missing invalidation"]})
        self.assertEqual(verdict["issues"], ["Missing invalidation"])
    def test_secret_in_change_vetoes_approval(self):
        # The model said yes; the safety scan says no.
        changes = {**self.changes, "contents": {"settings.py": "KEY = 'gsk_" + "A" * 40 + "'"}}
        verdict = self.review({"approved": True, "summary": "fine"}, changes=changes)
        self.assertFalse(verdict["approved"])
        self.assertTrue(any("possible secret" in i for i in verdict["issues"]))
        self.assertTrue(verdict["summary"].startswith("Rejected by automated safety checks"))
    def test_empty_change_is_rejected(self):
        # Approving a no-op would open an empty PR.
        verdict = self.review({"approved": True}, changes={"diff": "", "changed_files": [], "contents": {}})
        self.assertFalse(verdict["approved"])
    def test_garbage_output_raises(self):
        # Non-JSON from the model is a stage failure, not an approval.
        with self.assertRaises(AgentRunFailed):
            self.review("I think it looks fine!")
class CoderChangeTrackingTests(SimpleTestCase):
    # The cumulative diff is always against the original commit, across attempts.
    def setUp(self):
        # Real git repo with two files.
        self.root = make_git_repo({"app.py": "print('v1')\n", "util.py": "X = 1\n"})
    def tearDown(self):
        # Removes the repo.
        cleanup_clone(self.root)
    def test_summarize_changes_across_attempts(self):
        # Attempt 1 edits app.py, attempt 2 adds new.py and edits app.py again; util.py rewritten unchanged is ignored.
        _apply_files_and_diff(self.root, [{"path": "app.py", "content": "print('v2')\n"}])
        _apply_files_and_diff(self.root, [
            {"path": "app.py", "content": "print('v3')\n"},
            {"path": "pkg/new.py", "content": "Y = 2\n"},
            {"path": "util.py", "content": "X = 1\n"},
        ])
        summary = summarize_changes(self.root, ["app.py", "pkg/new.py", "util.py"])
        self.assertEqual(summary["changed_files"], [{"path": "app.py", "change": "modified"}, {"path": "pkg/new.py", "change": "added"}])
        self.assertEqual(summary["contents"]["app.py"], "print('v3')\n")
        app_diff = next(d for d in summary["file_diffs"] if d["path"] == "app.py")
        self.assertEqual(app_diff["old_content"], "print('v1')\n")
        self.assertEqual(summary["modes"]["app.py"], "100644")
        self.assertIn("print('v3')", summary["diff"])
        self.assertEqual(head_info(self.root).branch, "main")
    def test_reset_and_reapply_undoes_what_tests_wrote(self):
        # A test run rewrote a Coder file and an untouched tracked file; restoring brings back exactly the Coder's output.
        _apply_files_and_diff(self.root, [{"path": "app.py", "content": "print('coder')\n"}, {"path": "pkg/new.py", "content": "Y = 2\n"}])
        saved = summarize_changes(self.root, ["app.py", "pkg/new.py"])["contents"]
        for rel in ("app.py", "util.py", "pkg/new.py"):
            (Path(self.root) / rel).write_text("tampered by a test\n", encoding="utf-8")
        reset_tracked_files(self.root)
        apply_files(self.root, [{"path": p, "content": c} for p, c in saved.items()])
        read = lambda rel: (Path(self.root) / rel).read_text(encoding="utf-8")  # noqa: E731
        self.assertEqual((read("app.py"), read("util.py"), read("pkg/new.py")), ("print('coder')\n", "X = 1\n", "Y = 2\n"))
    def test_protected_and_escaping_paths_rejected(self):
        # Path traversal and protected files never get written.
        root = Path(self.root).resolve()
        for bad in ("../outside.py", ".git/hooks/pre-commit", ".env", ".github/workflows/ci.yml"):
            with self.assertRaises(AgentRunFailed, msg=bad):
                _safe_relative_path(root, bad)
        self.assertEqual(str(_safe_relative_path(root, ".env.example")), ".env.example")
class CoderOutputTests(SimpleTestCase):
    # Files the model only saw in part can be edited in place but never rewritten whole.
    def setUp(self):
        # A repo with one file longer than the prompt's per-file cap and one short file.
        self.long = "".join(f"line {i}\n" for i in range(MAX_FILE_CHARS // 4)) + "TAIL = True\n"
        self.root = make_git_repo({"big.py": self.long, "small.py": "A = 1\n"})
    def tearDown(self):
        # Removes the repo.
        cleanup_clone(self.root)
    def validate(self, files, truncated=frozenset({"big.py"})):
        # Runs _validate_files on a model answer built from `files`.
        return _validate_files(json.dumps({"files": files}), self.root, truncated)
    def test_long_files_are_reported_truncated(self):
        # The prompt marks the file and the caller learns which files were cut.
        text, truncated = _format_file_contents(self.root, ["big.py", "small.py"])
        self.assertEqual(truncated, {"big.py"})
        self.assertIn("### big.py  (TRUNCATED", text)
        self.assertNotIn("TAIL = True", text)
    def test_whole_rewrite_of_truncated_file_is_rejected(self):
        # Rewriting a file the model never saw the end of would drop that end.
        with self.assertRaisesMessage(AgentRunFailed, "TRUNCATED"):
            self.validate([{"path": "big.py", "content": "line 0\n"}])
    def test_edits_keep_the_unseen_part(self):
        # Search/replace changes the shown part and leaves the tail intact.
        files = self.validate([
            {"path": "./big.py", "edits": [{"search": "line 1\n", "replace": "line one\n"}]},
            {"path": "small.py", "content": "A = 2\n"},
        ])
        result = {f["path"]: f["content"] for f in files}
        self.assertTrue(result["big.py"].startswith("line 0\nline one\nline 2\n"))
        self.assertTrue(result["big.py"].endswith("TAIL = True\n"))
        self.assertEqual(result["small.py"], "A = 2\n")
    def test_edits_must_match_exactly_once(self):
        # Missing or ambiguous search text is an error the Coder is asked to fix, never a silent no-op.
        for search, problem in (("nope", "was not found"), ("line", "matches"), ("", "is empty")):
            with self.assertRaisesMessage(AgentRunFailed, problem):
                self.validate([{"path": "big.py", "edits": [{"search": search, "replace": "x"}]}])
    def test_edits_need_an_existing_file_and_one_mode(self):
        # Edits can't create files, and an entry can't carry both content and edits.
        with self.assertRaisesMessage(AgentRunFailed, "does not exist"):
            self.validate([{"path": "missing.py", "edits": [{"search": "a", "replace": "b"}]}])
        with self.assertRaisesMessage(AgentRunFailed, "exactly one"):
            self.validate([{"path": "small.py", "content": "B\n", "edits": []}])
class SafetyAndParsingTests(SimpleTestCase):
    # Small pure helpers.
    def test_blocked_paths(self):
        # Credentials, CI and git internals are blocked; example env files are not.
        for path in (".env", "config/.env.production", "deploy/key.pem", ".github/workflows/x.yml", "./.git/config", "id_rsa"):
            self.assertTrue(is_blocked_path(path), path)
        for path in (".env.example", "src/app.py", "docs/github-workflows.md"):
            self.assertFalse(is_blocked_path(path), path)
    def test_secret_scan(self):
        # Known token formats are flagged; ordinary code isn't.
        findings = scan_changes({"a.py": "AWS = '" + "AKIA" + "ABCDEFGHIJKLMNOP'", "b.py": "token = os.environ['GITHUB_TOKEN']"})
        self.assertEqual([f.path for f in findings], ["a.py"])
    def test_parse_strict_json_tolerates_fences_and_trailing_text(self):
        # Existing behaviour preserved.
        self.assertEqual(parse_strict_json('```json\n{"steps": ["a"]}\n```'), {"steps": ["a"]})
        self.assertEqual(parse_strict_json('Sure! {"a": 1}\nHope that helps'), {"a": 1})
        with self.assertRaises(AgentRunFailed):
            parse_strict_json('{"a": ')
