# Agent Swarm — Autonomous Coding Agent Orchestrator

A multi-agent system that automates a coding task end-to-end through four
cooperating agents — **Planner → Coder → Tester → Reviewer** — coordinated
by a Django/Celery orchestrator, with every decision logged and viewable in
a React UI. Code execution happens in an isolated, network-disabled Docker
container; it never touches the host.

```
Task submitted → Planner (Groq) → Coder (Groq, 2 keys: LRU + cooldown) ⇄ Tester (sandbox, no LLM)
                                                     ↑___________________retry up to 3x______|
                             → Reviewer (Groq) → done
```

## One provider (Groq), four API keys

Every LLM-backed agent runs on **Groq**. The pipeline originally split work
across Gemini and Groq, but Gemini's free tier turned out to be capped per
Google Cloud *project* rather than per key — 20 requests/day, shared by
every key issued under the same project — which a single multi-retry run
exhausts on its own. Groq's per-key limits are both higher and genuinely
independent per key, so spreading load across keys actually buys headroom
there. See "Why Gemini was dropped" below for the receipts.

- **Planner → Groq**, one dedicated key. Reads the task description and a
  trimmed repo file tree, returns an ordered step plan.
- **Coder → Groq**, *two* dedicated keys. The highest-*volume* agent by far
  (one call per plan, plus one more per retry attempt), so unlike the other
  agents it isn't pinned to a single key — see the algorithm below.
- **Tester → no LLM, no key.** It runs the repo's real `pytest`/`npm test`
  inside the sandbox and parses the exit code/output programmatically.
  Testing should be deterministic, not LLM-judged.
- **Reviewer → Groq**, one dedicated key. A bounded "does this diff match
  the plan" check that needs to be fast and cheap, not clever.

All provider calls go through `backend/agents/llm_client.py`'s
`call_llm(provider, messages=[...], api_key=...)` — swapping which provider
(or which key) an agent uses is a one-line change, not a rewrite. The
`provider` argument is kept even though only Groq is wired up today: adding
a second provider back means adding one `_call_*` function and one dispatch
entry, not touching four agent modules. `api_key` is always passed in
explicitly by the caller; the client module itself has no notion of a single
global key.

### Four keys, one per agent role

Each agent *role* gets its own dedicated key rather than one shared Groq key
across the pipeline, so a role that burns through its quota can't starve the
others. All four come from [console.groq.com/keys](https://console.groq.com/keys):

| Role | Env var |
|---|---|
| Planner | `GROQ_API_KEY_PLANNER` |
| Coder (slot A) | `GROQ_API_KEY_CODER_A` |
| Coder (slot B) | `GROQ_API_KEY_CODER_B` |
| Reviewer | `GROQ_API_KEY_REVIEWER` |

Planner and Reviewer each just use their one key directly. The **Coder** is
the one agent that switches between two keys, because it's called far more
often than the other three combined.

**Algorithm — least-recently-used + per-key cooldown + failover**
(`backend/agents/services/key_pool.py`):

1. **Least-recently-used first.** Whichever of the two keys was used
   longest ago serves the next call. In the steady state that's plain
   alternation (A, B, A, B…), halving the request pressure on either key
   across a multi-retry run instead of hammering one key `MAX_TEST_RETRIES`
   times in a row.
2. **Cooldown on 429.** A rate-limited key is benched for a spell that
   *doubles* per consecutive 429 (60s → 120s → 240s, capped at 480s), so
   the next call skips straight to its sibling instead of paying
   `call_llm`'s full backoff cycle against a key that's already known to be
   out of quota. A success clears the penalty. Non-429 failures (bad key,
   malformed request, transient 5xx) get a much shorter 15s bench — enough
   to prefer the sibling on the next call, without writing off what might
   have been one blip.
3. **Failover, and never a hard stop.** If the chosen key's call fails for
   *any* reason, the Coder immediately tries the other one before giving up
   that attempt. Benched keys are still offered as a last resort, ordered by
   whose cooldown expires soonest — so even with both keys throttled a call
   attempts the one closest to recovery rather than failing outright.

Why LRU rather than a plain alternate-by-attempt-number counter: a fixed
counter keeps sending every even attempt to key A even when A is known to be
rate-limited, wasting a full backoff cycle before failing over each time.
LRU + cooldown skips the dead key outright, and self-corrects — the key that
was skipped is the stalest one once it recovers, so it gets picked first and
the load re-balances on its own. Recency is tracked with a pool-wide counter
rather than a timestamp, since `time.monotonic()`'s ~15ms resolution on
Windows makes two nearby calls read as equally recent, which would collapse
the rotation onto one key.

State is per-process and in-memory, which is exactly one shared pool under
`celery -P solo` (what this project documents on Windows). Under a
multi-process worker each process keeps its own view — still correct, just
less well-informed; moving the pool to Redis is the upgrade path, and
nothing outside `key_pool.py` would change.

`AgentRun.output["key_slot"]` records which key actually served a run (the
Agent Trace shows it as *via groq · key A*), and `["keys_tried"]` keeps the
full attempt list either way — so a silent failover is still visible after
the fact rather than looking like a clean first-try success.

### Known free-tier constraints (found in practice, not guessed)

Both of these surfaced with live keys, and are worth knowing before assuming
a failure means a bad key:

- **Groq's `llama-3.1-8b-instant` free tier caps at ~6000 tokens/minute,
  combined prompt + completion, per request.** This is the single biggest
  constraint on the pipeline. Requesting `max_output_tokens=16384` fails
  *every single time* with a 413 ("Request too large … Limit 6000,
  Requested 18269") — the output-token ask alone blows past the ceiling
  before the prompt is even counted. So every agent reserves only what its
  output actually needs, leaving the rest of the budget for the prompt:
  Coder `3000` (`_CODER_MAX_OUTPUT_TOKENS`), Planner `1500`
  (`MAX_PLAN_OUTPUT_TOKENS` — its prompt carries the repo file tree),
  Reviewer `1024` (`MAX_REVIEW_OUTPUT_TOKENS` — its prompt carries 6000
  chars of diff). A Coder response that still gets truncated comes back as
  `finish_reason=length`, which `llm_client.py` raises as an explicit
  token-budget error rather than letting it surface downstream as a
  baffling JSON parse failure.
- **Why Gemini was dropped: its free tier is limited per *Google Cloud
  project*, not per API key** — confirmed via the actual 429 payload:
  `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `limit: 20`
  requests/day. Two keys issued from the same Google account under the same
  project **share that one 20/day pool** — they do not double it, and the
  default "quick create" flow in AI Studio reuses the same project every
  time. 20 requests/day doesn't survive normal dev on a pipeline that makes
  up to 4 Coder calls per run. Groq's per-key limits, by contrast, are
  independent per key, which is what makes the two-key Coder rotation
  worth anything at all.

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
- **Four free API keys**, all from [Groq](https://console.groq.com/keys) — one Groq account can issue multiple keys, so this doesn't require four separate accounts. See "Four keys, one per agent role" above for why four.

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
copy .env.example .env           # cp on macOS/Linux -- then fill in the four GROQ_API_KEY_* vars
python manage.py migrate
python manage.py createsuperuser # optional, for the /admin audit-trail view
python manage.py test_llm        # optional smoke test that all four keys work (tests each individually)
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
> afterward. (This run predates two later changes: the switch to
> `github_url` below -- tasks pointed at a `repo_path` on the server's own
> disk at the time -- and the move to Groq-only, so the Planner/Coder
> providers and timings above are the Gemini-era ones.)

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
