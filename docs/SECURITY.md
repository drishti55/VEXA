# Security model

VEXA lets LLM agents write code and run tests on your machine. This document states what is protected, how, and what is **not** protected.

## Assets and adversaries

| Category | What it covers |
|---|---|
| **Assets** | the host machine, credentials (LLM, search and A2A keys, API token), other workspaces, the integrity of experiment results |
| **Adversaries** | a malicious or careless requirement; untrusted repository content, test output or web search results that try to steer an agent (indirect prompt injection); a misbehaving model (loops, wrong tool, writing secrets into code, fabricated success) |

## Boundaries (enforced)

| Control | Where |
|---|---|
| API on localhost, CORS allowlist, optional bearer token | `backend/main.py`, `API_TOKEN` |
| Workspace IDs are single safe path components; file paths are resolved and must stay inside the workspace; host-absolute paths are rejected | `tools/workspace.py` |
| Custom output folders only under `WORKSPACE_ALLOWED_OUTPUT_ROOTS` (disabled by default) | `tools/workspace.py` |
| Command policy by argv: `python -m pytest/ruff/mypy`, read-only git subcommands, safe pytest flags; no `python -c`, no pip, no `-p` plugins, no paths outside the workspace | `tools/execution.py` |
| Allowlisted environment for every subprocess and MCP server (no inherited keys) | `build_sandbox_env` |
| Process-group kill on timeout; CPU, file-size and (where the OS supports it) memory rlimits; output captured to files with a size cap | `LocalSandboxExecutor` |
| Docker sandbox: no network, read-only root, all capabilities dropped, memory/CPU/PID limits, only the workspace mounted, no silent fallback to local | `DockerSandboxExecutor` |
| Web preview is CSP-sandboxed (opaque origin) and the iframe has no `allow-same-origin`, so generated JavaScript cannot call the API | `api/workspaces.py`, `WebPreview.tsx` |
| Test verdicts come from the sandbox exit code; LLM claims of success are overridden and recorded | `crew.py` |
| A2A verifier: bearer auth enforced (ADK only advertises it), reads only the named workspace, workspace chosen by a callback rather than the LLM | `a2a_bridge/verifier_server.py`, `adk_agents/verifier.py` |
| Secrets redacted from logs, tracebacks, traces and stored results | `observability/redaction.py` |
| CrewAI anonymous telemetry disabled | `backend/__init__.py` |

## Guardrails

Every decision — including *allowed* and *sanitized* ones — is recorded in `RunResult.guardrail_events` with `rule` (G1–G8), `decision` (allowed | blocked | sanitized | flagged | indeterminate), `action` (proceed | reject | retry | sanitize | stop | record), `reason`, timestamp and run id, attached to the trace as span events, and shown in the Trace tab and the report.

| ID | Guard | Action |
|---|---|---|
| G1 | requirement screening (credential exfiltration, host access, sandbox escape, destructive host commands) | block (HTTP 422) |
| G2 | per-role tool authorization (`TOOL_POLICY`), applied to direct and MCP tools | block |
| G3 | tool-call budget per agent invocation | block |
| G4 | writing a registered secret into a file | block |
| G5 | risky code patterns (shell, eval, network, env access, recursive delete) | flag |
| G6 | instruction-like text in tool output; all tool output wrapped in `<untrusted_tool_output>` and every prompt carries a security preamble | flag + spotlight |
| G7 | wall-clock budget per run | stop |
| G8 | Pydantic schema validation of every agent output (CrewAI guardrail re-prompts in real mode) | allow / retry / record (result marked invalid) |

## Limits

- G1, G5 and G6 are pattern matchers. They miss paraphrased or obfuscated attacks and can flag benign text. They make attacks visible and add friction, but they are **not** a security boundary. Toxicity filtering is not used as an injection defence.
- **The local sandbox does not isolate test code.** A test file written by an agent runs with your user's permissions. The command policy only stops the agent from launching arbitrary commands directly. Use `SANDBOX_BACKEND=docker` for untrusted tasks.
- RLIMIT_AS (memory) is not enforced by macOS; use Docker for a hard memory cap.
- API keys typed into the UI are used for that run/experiment only: they are never persisted, never returned by the API, redacted from logs and results, and reach the embedded ADK verifier only as an opaque in-process handle (never inside an A2A message).
- The bearer token is a shared secret, not per-user authentication. Do not expose the API beyond localhost.
- The ADK verifier and the backend must share the workspace storage; the verifier trusts any workspace that exists under its own `WORKSPACE_ROOT`.
