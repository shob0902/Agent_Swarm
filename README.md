# Agent Swarm — Autonomous Coding Agent Orchestrator

A multi-agent system that automates a coding task end-to-end through four
cooperating agents — **Planner → Coder → Tester → Reviewer** — coordinated
by a Django/Celery orchestrator, with every decision logged and viewable in
a React UI. Code execution happens in an isolated, network-disabled Docker
container; it never touches the host.

```
Task submitted → Planner (Gemini) → Coder (Gemini) ⇄ Tester (sandbox, no LLM)
                                         ↑______________retry up to 3x______|
                → Reviewer (Groq) → done
```

## Why two LLM providers

- **Planner & Coder → Gemini.** Both need to reason over repo-wide context
  (file tree, plan, prior file contents, prior test failures); Gemini's
  free-tier context window handles that better than Groq's smaller-context
  free models.
- **Tester → no LLM.** It runs the repo's real `pytest`/`npm test` inside
  the sandbox and parses the exit code/output programmatically. Testing
  should be deterministic, not LLM-judged.
- **Reviewer → Groq.** A bounded "does this diff match the plan" check
  doesn't need a large context window, and Groq's low latency makes it a
  snappy final step.

All provider calls go through `backend/agents/llm_client.py`'s
`call_llm(provider="gemini"|"groq", messages=[...])` — swapping which
provider an agent uses is a one-line change, not a rewrite.

> Gemini access uses the current `google-genai` SDK against
> `GEMINI_MODEL=gemini-flash-latest` (Google's own alias for their current
> recommended flash model). The older `google.generativeai` SDK and pinned
> `gemini-1.5-*`/`gemini-2.5-*` model names are already sunset for new API
> keys as of this writing — if `test_llm` 404s on the model, run
> `client.models.list()` (see git history of this file / llm_client.py) to
> see what's currently available to your key and adjust `GEMINI_MODEL` in
> `.env`.

## Repo layout

```
backend/    Django + DRF + Celery orchestrator (agents app: models, services, prompts, sandbox)
frontend/   React 18 + Vite UI (neumorphic theme, light/dark)
demo_repo/  Toy Flask app with failing tests -- the end-to-end demo target
docker-compose.yml   Redis only (broker + Celery result backend)
```

## Prerequisites

- Python 3.11+, Node 18+, Git
- **Docker Desktop** running — required for the sandbox (Coder/Tester execution) and for Redis via compose
- A free [Google AI Studio](https://aistudio.google.com/) API key (Gemini) and a free [Groq](https://console.groq.com/) API key

## Setup

### 1. Redis

```
docker compose up -d
```

### 2. Sandbox image (build once)

`python:3.11-slim` alone has no test runner, and the sandbox has no network
access at run time to `pip install` one — so the image used to run tests
needs pytest/flask baked in ahead of time:

```
cd backend
docker build -t agent-swarm-sandbox:latest -f docker/sandbox.Dockerfile .
```

### 3. Backend

```
cd backend
python -m venv venv
venv\Scripts\activate            # venv/bin/activate on macOS/Linux
pip install -r requirements.txt
copy .env.example .env           # cp on macOS/Linux -- then fill in GOOGLE_API_KEY / GROQ_API_KEY
python manage.py migrate
python manage.py createsuperuser # optional, for the /admin audit-trail view
python manage.py test_llm        # optional smoke test that both API keys work
python manage.py runserver
```

In a second terminal, the Celery worker (Windows needs `-P solo`; drop it on macOS/Linux):

```
cd backend
venv\Scripts\activate
celery -A orchestrator worker --loglevel=info -P solo
```

### 4. Frontend

```
cd frontend
npm install
copy .env.example .env           # cp on macOS/Linux -- defaults already point at localhost:8000
npm run dev
```

Open the printed Vite URL (default `http://localhost:5173`).

> ✅ Verified end-to-end on 2026-08-07: `docker compose up -d` → built the
> sandbox image → `runserver` + `celery worker -P solo` → a real
> `POST /api/tasks/` against `demo_repo` ran Planner (Gemini, 13.3s) → Coder
> (Gemini, 18.6s) → Tester (sandboxed pytest, 1.2s, exit 0, "3 passed") →
> Reviewer (Groq, 0.4s, approved), landed on `done` on the first attempt
> (no retries needed), and the sandbox container was cleaned up
> automatically. `demo_repo` was reset to its pristine failing-test state
> afterward. (This run predates the switch to `github_url` below -- tasks
> pointed at a `repo_path` on the server's own disk at the time.)

Tasks now take a **public GitHub repo URL** (`github_url`) instead of a
local filesystem path -- the pipeline shallow-clones it into a throwaway
temp directory at run time (`services/repo.py`) and cleans it up when the
run ends, so it works against anyone's repo, not just one already checked
out on the machine running Django/Celery. Private repos and non-GitHub
hosts are rejected up front.

## Running the demo

1. With Redis, the sandbox image, `runserver`, the Celery worker, and
   `npm run dev` all up, open the UI.
2. Push `demo_repo/` to a public GitHub repo of your own (or point at any
   public repo with a failing test suite). Submit a task with the
   description from [`demo_repo/README.md`](demo_repo/README.md) and
   `github_url` set to that repo's URL, e.g. `https://github.com/<you>/demo_repo`.
3. Watch the Agent Trace timeline: Planner → Coder → Tester (retrying on
   failure) → Reviewer, ending `done` with the diff shown and all three
   tests in `demo_repo/test_app.py` passing.
4. `/admin/` (Django admin) gives a free, zero-extra-frontend audit trail
   of every `Task` and `AgentRun` — including the raw LLM responses logged
   to `AgentRun.output`, so a run can be debugged without re-calling the API.

## Design notes / deliberate trade-offs

- **Coder output format:** strict JSON `{"files": [{"path", "content"}]}`
  (whole-file rewrites), not a unified diff. LLM-generated unified diffs are
  fragile to parse (context-line drift breaks `git apply`); whole-file
  rewrites are simple to validate and apply. A real `git diff` is computed
  *after* applying the files, so the Reviewer prompt and the frontend's
  `DiffViewer` still see a proper diff even though the model never
  produced one directly.
- **Every stage is defensively parsed.** Planner/Coder/Reviewer JSON output
  is validated with a clear failure path (`AgentRunFailed`) rather than
  letting a `json.loads` crash take down the whole Celery task — this is
  the most common failure mode in agent pipelines (see comments in
  `backend/agents/services/common.py`).
- **Every `AgentRun` row is created *before* its LLM/sandbox call** (status
  `pending`) and updated after, including on exceptions — a crashed agent
  is always visible in the trace, never silently missing
  (`backend/agents/services/common.py::track_run`).
- **Sandbox isolation:** `network_disabled=True`, a 512MB memory cap, and a
  hard timeout (kill + remove the container rather than hang the Celery
  worker) on every Coder-file-write/Tester run.
- **Path-traversal guard:** the Coder agent's file writes are resolved and
  checked against the repo root before touching disk, rejecting anything
  like `../../etc/passwd`.

## Non-goals (v1)

No multi-repo support, no auth/user accounts, no LLM-based test generation,
no code execution outside the sandboxed container. See Section 13 of the
original project brief.
