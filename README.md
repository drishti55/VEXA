# VEXA

**Architecture-Aware Autonomous Multi-Agent Software Engineering System**

VEXA turns a natural-language software requirement into a code change in a workspace and verifies it by actually running the tests. It is also a research platform: the same seven agents, tools, prompts and benchmark tasks run under four orchestration architectures, so differences in outcome can be attributed to the architecture (or to a prompt strategy) rather than to anything else.

| | |
|---|---|
| Agents | RequirementAnalyst, ProjectAnalyst, Planner, Coder, Tester, Debugger, Verifier (+ Manager in the hierarchical architecture) |
| Agent frameworks | **CrewAI** (specialists, Manager) and **Google ADK** (Verifier, served over **A2A** by default) |
| Architectures | `sequential`, `hierarchical`, `event_driven`, `blackboard` |
| Tool access | **MCP**: `vexa-workspace` server (files, search, git, sandboxed tests) and `vexa-docs-search` server (Tavily) |
| Output | Pydantic-validated agent outputs (CrewAI guardrails with re-prompting) and a final `RunReport` (JSON + Markdown) |
| Observability | OpenTelemetry spans (run → agent → tool / LLM), CrewAI event callbacks, versioned shared state with provenance, coordination log |
| Persistence | SQLite run registry (Postgres-compatible schema) |
| Evaluation | 10 validated benchmark tasks with hidden tests, repeatable experiments, Wilson/Newcombe intervals, CSV/JSON/Markdown export |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) · [docs/SECURITY.md](docs/SECURITY.md) · research spec [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)

---

## Quick start

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env            # mock mode needs no keys

.venv/bin/python -m pytest -q   # full test suite, no network or API keys needed

# backend (Terminal 1)
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# frontend (Terminal 2)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

API docs: http://localhost:8000/docs

> Use `python -m uvicorn`/`python -m pytest`. If the `.venv` was created in another folder, its console scripts point to the old location.

### Verification

```bash
python -m pytest -q                                   # unit + integration + protocol tests (no keys, no network)
VEXA_LIVE_TESTS=1 python -m pytest -m live -s tests/test_live_providers.py   # live provider (keys from .env)
cd frontend && npx playwright test                    # browser E2E: real Chrome → Vite → real backend (mock mode)
curl -s localhost:8000/agent-runs/provider-status     # provider configured? (names/booleans only, never keys)
```

The browser tests start their own isolated backend (scratch workspaces/database, no `.env`) and use the
locally installed Google Chrome. The test suite never reads `.env` (`VEXA_ENV_FILE=""` in `tests/conftest.py`).

### Mock mode vs real mode

| | Mock | Real |
|---|---|---|
| LLM | none: agents return scripted, schema-valid answers | the configured model (`VEXA_LLM_*`), billed by your provider |
| Tools, MCP, A2A, sandbox, test execution, state, tracing, guardrails | real (agents make scripted, read-only tool calls, tagged `origin=scripted`) | real |
| What a result means | the pipeline and coordination work | the agents' ability to solve the task |

Mock runs never build an LLM client and never touch the network. An unknown `execution_mode` is rejected (HTTP 422) rather than silently falling back to either mode.

### Running a task

In the dashboard pick a workspace, an **architecture**, a **prompt strategy**, the **Verifier** (Google ADK over A2A, or CrewAI) and **agent tools** (MCP or direct), enter the requirement and click **RUN VEXA**. For real mode, enter a model and use **Test model** first (a 1-token call) — the provider is inferred from the model prefix.

Tabs: **Overview** (the actual dispatch sequence, incl. manager revisions), **Coordination** (manager decisions/reviews/briefs, events, A2A and MCP traffic), **State** (blackboard read/write matrix), **Trace** (span hierarchy, per-agent metrics, tool calls, errors/retries, guardrail decisions), **Report** (JSON/Markdown download). Use *Open a previous run* to reload any persisted run; the last viewed run is restored after a page refresh.

From the API:

```bash
curl -X POST localhost:8000/agent-runs -H 'content-type: application/json' -d '{
  "workspace_id": "my-ws", "requirement": "Add a modulo function to calculator.py",
  "architecture": "blackboard", "prompt_variant": "baseline", "execution_mode": "mock"}'
curl localhost:8000/agent-runs/<run_id>/report?format=md
curl localhost:8000/agent-runs/<run_id>/trace
```

### Optional services

| Feature | How to enable |
|---|---|
| Docs search over MCP | set `TAVILY_API_KEY` |
| Google ADK Verifier over A2A | on by default: the backend starts the A2A server on `127.0.0.1:8101`. In real mode it uses your run's model/key (passed in-process as an opaque handle, never over A2A) or `VEXA_ADK_MODEL`. External server: `VEXA_A2A_EMBEDDED=false` |
| Docker sandbox | start Docker, `docker build -t vexa-sandbox:latest -f docker/sandbox.Dockerfile docker`, set `SANDBOX_BACKEND=docker` |
| OTLP trace export | set `OTEL_EXPORTER_OTLP_ENDPOINT` |
| API token | set `API_TOKEN` (backend) and `VITE_VEXA_API_TOKEN` (frontend `.env.local`) |

### Experiments

Use the **Experiments** page: choose tasks, architectures, prompt strategies, tools, Verifier, repeats/seed (and model, prices, spending cap for real mode), **Validate**, **Start**. Progress, **Cancel**, **Resume missing trials**, per-run drill-down (opens the run's report and trace), architecture and prompt comparisons, and CSV/JSON/Markdown export are on the same page. Or from the CLI:

```bash
.venv/bin/python -m backend.evaluation.experiment benchmarks/experiments/pilot_mock.json
```

See [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

---

## Repository layout

```
backend/
  agents/          runtime: crew.py (agents + steps), prompts.py, prompt_variants.py,
                   schemas.py (LLM output schemas), contracts.py, reporting.py, tools.py
  orchestration/   sequential, hierarchical, event_driven, blackboard; SharedState
  mcp_servers/     vexa-workspace and vexa-docs-search MCP servers
  mcp_client/      MCP client bridge → CrewAI tools
  adk_agents/      Google ADK Verifier
  a2a_bridge/      A2A server (ADK) and client (used by the CrewAI runtime)
  observability/   tracing (OpenTelemetry), CrewAI callbacks, redaction
  guardrails.py    input screening, tool policy, injection detection, budgets
  db/              SQLAlchemy models + run registry
  evaluation/      benchmark grading, experiment runner, statistics
  tools/           workspace manager, filesystem/search/git tools, sandbox executors
  api/             FastAPI routers (workspaces, agent-runs, experiments)
benchmarks/        tasks/ (repo, hidden_tests, solution per task) and experiment configs
frontend/          React/Vite dashboard
docker/            sandbox image
tests/             pytest suite
```

## Status and known limitations

- **Verified (Oct 2026):** automated suite (unit, integration, MCP/A2A protocol tests); browser E2E in real Chrome
  against the real backend (mock mode); one live-provider run (Groq `qwen/qwen3.8-27b`, hierarchical, MCP tools,
  ADK verifier over A2A) that fixed a bug, passed the sandbox tests, was verified, and is traced end to end.
- **Tracing:** ADK's own OpenTelemetry spans are linked into the run's trace only when the ADK verifier runs in the
  backend process (embedded, the default). An external ADK server keeps the trace id (W3C `traceparent`) but its
  spans stay in that process; VEXA then rebuilds its tool/LLM calls from A2A telemetry and labels them
  `reconstructed`.
- **Guardrails:** paths, commands, environment, tool arguments, secrets and credential files are enforced by code.
  Injection detection (patterns + an optional model classifier) is a signal, not a boundary.
- **Sandbox:** the local sandbox limits commands and environment but not what test code does; the Docker sandbox
  was not verified here (Docker not installed). See [docs/SECURITY.md](docs/SECURITY.md).
- **Provider limits:** Groq free tier allows ~200k tokens/day per model and a few thousand tokens/minute; one
  hierarchical run used ~32k tokens. Set `VEXA_MAX_RUN_TOKENS` to cap runs. Tavily search is configured but was not
  exercised by the live run.
- **Storage:** SQLite (WAL, busy timeout, additive migrations) is suited to a single local backend; it is not meant
  for several backend processes writing the same file over a network share.

## Licence

MIT
