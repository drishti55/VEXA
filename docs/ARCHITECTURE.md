# VEXA architecture

## Runtime vs. architecture

Everything that must be identical across an experiment lives in the **runtime** (`backend/agents/crew.py`, `SoftwareEngineeringCrew`):

- the seven specialist agents and their prompts (`prompt_variants.py`)
- their tools and per-role permissions (`guardrails.TOOL_POLICY`)
- their output schemas (`schemas.py`), validated by CrewAI task guardrails
- the LLM and the sandbox
- the test verdict, which always comes from the sandboxed pytest exit code
- the debug budget, the tool-call budget and the time budget

An **architecture** (`backend/orchestration/`) only decides *who runs next* and *how an agent gets its inputs*. It calls the runtime's public steps: `analyze_requirements`, `analyze_project`, `plan`, `code`, `test`, `debug`, `verify` (and `manager_decide` for the hierarchical architecture).

```
POST /agent-runs ─► run_task(workspace, requirement, mode, architecture)
                      ├─ guardrail G1 (requirement screening)
                      ├─ RunObserver (OpenTelemetry trace) + SharedState + MCP servers
                      ├─ Architecture.execute(handle)   ← the experimental variable
                      ├─ status = f(sandbox test result, verification)
                      └─ RunResult → registry (SQLite) → report / trace / export
```

## The four architectures

| | Control | How an agent receives its inputs |
|---|---|---|
| `sequential` | fixed pipeline with a bounded test→debug loop | function arguments (direct output passing) |
| `hierarchical` | a **Manager** reviews every result (accept / revise), writes a brief for each delegation, sends deficient work back (re-plan, re-code, rework after a failed verification; bounded by `VEXA_MANAGER_REVISION_BUDGET`) and decides when to finish; invalid picks are rejected and fed back | from the manager, who holds every result; the brief is appended to the specialist's task |
| `event_driven` | no scheduler; agents subscribe to typed events and publish new ones | event payloads |
| `blackboard` | a controller with an agenda driven by blackboard writes | **only** by reading the blackboard |

On identical, well-formed scripted inputs all four reach the same outcome (`tests/test_architectures.py::TestParity`). They differ in coordination — and Hierarchical additionally *reacts* to deficient results: with the default mock agents (whose Coder changes nothing) Sequential runs 6 dispatches while Hierarchical reviews the empty change, sends it back twice and runs 8 (`TestHierarchicalDiffersFromSequential`). The Manager is a CrewAI agent in real mode (schema-validated `ManagerDecision`) and a deterministic policy with the same review rules in mock mode.

### Blackboard

`backend/orchestration/blackboard.py`:

- **Blackboard**: the run's `SharedState`, a thread-safe, append-only store of knowledge items (`requirement_analysis`, `implementation_plan`, `code_changes`, `test_result`, `debug_report`, `verification`, …). Every write creates a new version with author, global sequence number and provenance (`derived_from`). Every read is logged against the reading agent.
- **Knowledge sources**: the same seven agents. Each declares `reads`, an activation condition and a priority. A source reads its inputs from the blackboard and contributes by writing one item; sources never call each other.
- **Controller**: subscribes to writes. A write puts the sources that read that item on the agenda. The controller runs the highest-priority triggered source and logs every wake-up, decision and stop.

The test → debug → re-test loop is not coded anywhere. It emerges because a `debug_report` newer than the latest `test_result` re-triggers the Tester, and a fresh failing `test_result` triggers the Debugger while budget remains.

The State tab of the dashboard shows the agent × item read/write matrix. In sequential, hierarchical and event-driven runs the matrix has writes only, because the state is an audit mirror there.

## Agents, frameworks and protocols

```
               CrewAI runtime (specialists)                         Google ADK
  ┌──────────────────────────────────────────────────┐        ┌──────────────────────┐
  │ RequirementAnalyst  ProjectAnalyst  Planner      │  A2A   │ vexa_verifier        │
  │ Coder  Tester  Debugger  [Verifier]  (Manager)   │◄──────►│ (LlmAgent, or a      │
  └──────┬───────────────────────────────┬───────────┘ JSON-  │  scripted BaseAgent  │
         │ MCP (stdio)                   │ MCP (stdio) RPC    │  in mock mode)       │
  ┌──────▼─────────────┐        ┌────────▼──────────┐         └──────────────────────┘
  │ vexa-workspace     │        │ vexa-docs-search  │
  │ files, search,     │        │ Tavily search API │
  │ git, run_tests     │        └───────────────────┘
  └────────────────────┘
```

- **MCP** (`mcp_servers/`, `mcp_client/bridge.py`): with `VEXA_TOOL_TRANSPORT=mcp` (the default), each real run starts a `vexa-workspace` MCP server bound to that run's workspace. Tools are discovered with `list_tools`, filtered per role and called with `call_tool`. `vexa-docs-search` starts when `TAVILY_API_KEY` is set. Both servers get a minimal environment and an empty working directory. The run records which servers connected and which tools they offered.
- **A2A** (`a2a_bridge/`): by default (`VEXA_VERIFIER_BACKEND=adk_a2a`, `VEXA_A2A_EMBEDDED=true`) the backend starts the ADK Verifier as a separate ASGI server on localhost with a random bearer token. One `VerifierRouter` ADK agent serves mock requests (deterministic) and real ones (ADK `LlmAgent`; the model/key come from an in-process credential handle, never from the A2A payload). The runtime sends the verification request as an A2A `message/send` to the ADK agent's JSON-RPC endpoint (agent card at `/.well-known/agent-card.json`, bearer auth enforced) and follows the task to a terminal state. The answer is validated against the same `VerifierOutput` schema, and the sandbox ground truth is applied exactly as for the CrewAI Verifier. The ADK agent uses the same Verifier prompt and read-only workspace tools, so framework is the only difference.

## Reports

`GET /agent-runs/{id}/report` (JSON) or `?format=md` returns a validated `RunReport` for every finished run, including failed ones (configuration errors are converted into a stored failed run). It contains the experiment metadata, acceptance criteria, requirement analysis, plan, execution sequence, **real code diffs** (workspace snapshot before/after, with the agent+tool that wrote each file), initial/final tests, debugging, verification (incl. LLM claim vs sandbox), guardrail decision counts, per-agent metrics, usage/cost (with the reason when unavailable), integrations, errors and limitations. Experiments have their own Markdown report (`GET /experiments/{id}/export?format=md`).

## Structured output

`schemas.py` defines what each LLM must return. In real mode every CrewAI task carries a guardrail that validates the answer and re-prompts the agent with the errors, up to `VEXA_OUTPUT_VALIDATION_RETRIES` times; after that the step fails loudly. Every result records `output_valid` and `validation_errors`, and invalid output is never silently defaulted. `reporting.py` turns a `RunResult` into a `RunReport` (`GET /agent-runs/{id}/report`, JSON or `?format=md`).

## Observability and provenance

- **Spans**: `observability/tracing.py` records real OpenTelemetry spans for the run, each agent invocation, each tool call (with transport `direct|mcp|a2a`) and each LLM call (model, tokens, finish reason). Spans are kept per run and exported over OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- **Span events**: state reads/writes (`state.read/write`), guardrail decisions (`guardrail.<decision>`), test verdicts and debug iterations are attached to the active agent span; A2A requests carry a W3C `traceparent` header.
- **Callbacks**: `observability/callbacks.py` listens on CrewAI's event bus for task start/completion (intermediate output, redacted), LLM calls, guardrail retries and tool errors.
- **Provenance**: state entries record the entries they were derived from; `file_provenance` maps each file to the tool call (agent, span) that wrote it; the test verdict is linked to the `run_tests` span.
- **Redaction**: configured secrets and credential-shaped strings are removed from logs, tracebacks, events, traces and stored results.

All of it is in `GET /agent-runs/{id}/trace` and in the registry tables (`spans`, `state_entries`, `state_access`, `coordination_events`, `agent_runs`).
