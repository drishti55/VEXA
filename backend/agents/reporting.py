"""
VEXA — Final Run Report

``build_run_report`` turns a RunResult into a validated RunReport;
``render_markdown`` renders it for humans. Everything is derived from the
RunResult — nothing is re-computed or invented. Measurements that do not
exist are reported as unavailable (None + a reason), never as zero.
Failed runs produce a report too, with whatever was reached and the errors.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agents.contracts import AgentResult, RunResult

CriterionStatus = Literal["satisfied", "failed", "unassessed"]


class CriterionRow(BaseModel):
    criterion: str
    status: CriterionStatus


class AgentRow(BaseModel):
    agent: str
    framework: str
    status: str
    invocations: int
    duration_ms: float
    llm_calls: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    tool_calls: int
    tool_errors: int
    validation_retries: int
    guardrail_blocks: int
    failures: int
    output_valid: bool | None
    usage_note: str | None = None


class SequenceStep(BaseModel):
    seq: int
    kind: str
    actor: str
    target: str | None
    detail: str
    decided_by: str | None = Field(default=None, description="manager_llm | rule_policy | mock_policy (hierarchical)")


class TestSummary(BaseModel):
    executed: bool
    passed: bool
    no_tests: bool
    exit_code: int | None
    tests_found: int
    tests_passed: int
    tests_failed: int
    failures: list[str] = Field(default_factory=list)
    verdict_source: str


class DebugRow(BaseModel):
    iteration: int
    root_cause: str
    fix_applied: str
    files: list[str]
    tests_passed_after: bool | None


class CodeChange(BaseModel):
    path: str
    change: str
    lines_added: int
    lines_removed: int
    diff: str
    truncated: bool = False
    written_by: list[str] = Field(default_factory=list, description="agent/tool that wrote it (provenance)")


class VerificationSummary(BaseModel):
    verified: bool
    llm_claimed_verified: bool | None
    overridden_by_tests: bool
    backend: str
    remote: dict[str, Any] | None
    requirements_satisfied: list[str]
    requirements_failed: list[str]
    evidence: str


class GuardrailSummary(BaseModel):
    counts: dict[str, dict[str, int]] = Field(description="rule → decision → count")
    notable: list[dict[str, Any]] = Field(description="every blocked, flagged or indeterminate decision")
    by_rule: dict[str, str] = Field(default_factory=dict, description=(
        "G1–G10 → fail (something was blocked) | not_evaluated (no decision recorded, or a check gave no "
        "verdict) | warning (flagged) | pass. A rule with no recorded decision is never reported as pass."))
    version: str | None = Field(default=None, description="guardrail implementation version(s) used by the run")


def guardrail_status_by_rule(events: list[dict[str, Any]]) -> dict[str, str]:
    by_rule: dict[str, set[str]] = {f"G{i}": set() for i in range(1, 11)}
    for g in events:
        by_rule.setdefault(g.get("rule", "G?"), set()).add(g.get("decision", "indeterminate"))
    out = {}
    for rule, decisions in by_rule.items():
        if "blocked" in decisions:
            out[rule] = "fail"
        elif not decisions or "indeterminate" in decisions:
            out[rule] = "not_evaluated"
        elif "flagged" in decisions:
            out[rule] = "warning"
        else:
            out[rule] = "pass"
    return out


class Measured(BaseModel):
    value: float | int | None
    unavailable_reason: str | None = None


class UsageSummary(BaseModel):
    input_tokens: Measured
    output_tokens: Measured
    total_tokens: Measured
    estimated_cost_usd: Measured
    cost_basis: str
    models_used: list[str] = Field(default_factory=list)
    llm_calls: int
    tool_calls: int
    agent_invocations: int


class RunReport(BaseModel):
    run_id: str
    trace_id: str | None
    status: str
    requirement: str
    architecture: str
    execution_mode: str
    provider: str | None
    model: str | None
    prompt_variant: str | None
    prompt_version: str | None
    tool_transport: str | None
    verifier_backend: str | None
    sandbox_backend: str | None
    experiment: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None
    total_duration_ms: float
    acceptance_criteria: list[CriterionRow]
    requirement_analysis: dict[str, Any] | None
    implementation_plan: dict[str, Any] | None
    execution_sequence: list[SequenceStep]
    files_changed: list[str]
    code_changes: list[CodeChange]
    initial_tests: TestSummary | None
    tests: TestSummary | None
    test_attempts: int
    debug: list[DebugRow]
    verification: VerificationSummary | None
    guardrails: GuardrailSummary
    agents: list[AgentRow]
    usage: UsageSummary
    integrations: dict[str, Any]
    orchestration: dict[str, Any] = Field(default_factory=dict,
                                          description="Who made control decisions; the mock policy if one was used")
    errors: list[str]
    limitations: list[str]


def _criterion_status(c: str, satisfied: list[str], failed: list[str]) -> CriterionStatus:
    if c in failed:
        return "failed"
    if c in satisfied:
        return "satisfied"
    return "unassessed"


def _tests(t) -> TestSummary | None:
    if t is None:
        return None
    return TestSummary(executed=t.exit_code is not None, passed=t.passed, no_tests=t.no_tests, exit_code=t.exit_code,
                       tests_found=t.tests_found, tests_passed=t.tests_passed, tests_failed=t.tests_failed,
                       failures=t.failures, verdict_source=t.verdict_source)


def _outputs(result: RunResult) -> dict[str, AgentResult]:
    return {r.agent_name: r for r in (
        result.requirement_analysis, result.project_analysis, result.implementation_plan,
        result.coding_result, result.final_test_result, result.verification_result,
    ) if r is not None}


def build_run_report(result: RunResult) -> RunReport:
    v = result.verification_result
    criteria = result.requirement_analysis.acceptance_criteria if result.requirement_analysis else []
    satisfied = v.requirements_satisfied if v else []
    failed = v.requirements_failed if v else []
    outputs = _outputs(result)

    agents = []
    for name, m in (result.agent_metrics or {}).items():
        if not m.get("invocations"):  # pre-registered (framework label) but never ran
            continue
        out = outputs.get(name)
        agents.append(AgentRow(
            agent=name, framework=m.get("framework", "crewai"), status=m.get("status", "unknown"),
            invocations=m.get("invocations", 0), duration_ms=m.get("duration_ms", 0.0),
            llm_calls=m.get("llm_calls", 0), input_tokens=m.get("input_tokens"), output_tokens=m.get("output_tokens"),
            estimated_cost_usd=m.get("estimated_cost_usd"), tool_calls=m.get("tool_calls", 0),
            tool_errors=m.get("tool_errors", 0), validation_retries=m.get("validation_retries", 0),
            guardrail_blocks=m.get("guardrail_blocks", 0), failures=m.get("failures", 0),
            output_valid=out.output_valid if out is not None else None, usage_note=m.get("usage_note"),
        ))

    counts: dict[str, Counter] = {}
    for g in result.guardrail_events:
        counts.setdefault(f"{g.get('rule', '?')} {g.get('rule_name', g.get('kind', ''))}", Counter())[
            g.get("decision", g.get("action", "?"))] += 1
    # Routine allowed/sanitized decisions are in the counts; list only what needs attention.
    notable = [g for g in result.guardrail_events
               if g.get("decision", g.get("action")) in ("blocked", "flagged", "indeterminate")]

    sequence = [SequenceStep(seq=c["seq"], kind=c["kind"], actor=c["actor"], target=c.get("target"),
                             detail=str(c.get("detail", ""))[:300],
                             decided_by=(c.get("data") or {}).get("source") if c["kind"] in ("decision", "review") else None)
                for c in result.coordination_log if c["kind"] in ("dispatch", "decision", "review", "message", "event", "stop")]

    provenance = result.file_provenance or {}
    code_changes = [CodeChange(**d, written_by=[f"{p.get('agent')}:{p.get('tool')}" for p in provenance.get(d["path"], [])])
                    for d in result.code_changes]

    debug = []
    if result.debug_result:
        for it in result.debug_result.iterations:
            debug.append(DebugRow(iteration=it.iteration, root_cause=it.root_cause, fix_applied=it.fix_applied,
                                  files=[f.path for f in it.files_changed],
                                  tests_passed_after=it.test_result_after.passed if it.test_result_after else None))

    spans = (result.trace or {}).get("spans", [])
    no_usage = "provider reported no usage" if result.execution_mode == "real" else "mock mode: no LLM calls"

    def measured(value, available: bool, reason: str) -> Measured:
        return Measured(value=value if available else None, unavailable_reason=None if available else reason)

    usage = UsageSummary(
        input_tokens=measured(result.input_tokens, result.usage_available, no_usage),
        output_tokens=measured(result.output_tokens, result.usage_available, no_usage),
        total_tokens=measured(result.total_tokens, result.usage_available, no_usage),
        estimated_cost_usd=measured(result.estimated_cost_usd, result.estimated_cost_usd is not None, result.cost_basis),
        cost_basis=result.cost_basis, models_used=result.models_used,
        llm_calls=sum(1 for s in spans if s.get("kind") == "llm"),
        tool_calls=sum(1 for s in spans if s.get("kind") == "tool"),
        agent_invocations=sum(1 for s in spans if s.get("kind") == "agent"),
    )

    limitations: list[str] = []
    if result.execution_mode == "mock":
        limitations.append("Mock mode: agents return scripted answers and make no code changes; "
                           "results show that the pipeline works, not that the task was solved.")
        if not result.files_changed:
            limitations.append("No code was changed, so the status is capped at 'partial' even though "
                               "the existing tests passed.")
    t = result.final_test_result
    if t is None:
        limitations.append("Tests were not run (the run stopped earlier).")
    elif t.no_tests:
        limitations.append("No tests were collected, so the change is not test-verified.")
    if v and v.llm_claimed_verified and not v.verified:
        limitations.append("The Verifier claimed success but the sandboxed tests failed; its claim was overridden.")
    if any(c.status == "unassessed" for c in [CriterionRow(criterion=c, status=_criterion_status(c, satisfied, failed))
                                               for c in criteria]):
        limitations.append("Some acceptance criteria were not explicitly assessed by the Verifier.")
    if not result.usage_available:
        limitations.append(f"Token usage unavailable ({no_usage}).")
    if result.estimated_cost_usd is None:
        limitations.append(f"Cost unavailable: {result.cost_basis}.")
    if result.sandbox_backend == "local":
        limitations.append("Local sandbox: test code ran as the host user (use SANDBOX_BACKEND=docker for isolation).")

    req = result.requirement_analysis
    plan = result.implementation_plan
    return RunReport(
        run_id=result.run_id, trace_id=result.trace_id, status=result.status.value, requirement=result.requirement,
        architecture=result.architecture, execution_mode=result.execution_mode, provider=result.provider,
        model=result.model, prompt_variant=result.prompt_variant, prompt_version=result.prompt_version,
        tool_transport=result.tool_transport, verifier_backend=result.verifier_backend,
        sandbox_backend=result.sandbox_backend, experiment=result.metadata,
        started_at=result.started_at, finished_at=result.finished_at, total_duration_ms=result.total_duration_ms,
        acceptance_criteria=[CriterionRow(criterion=c, status=_criterion_status(c, satisfied, failed)) for c in criteria],
        requirement_analysis=None if req is None else {
            "status": req.status.value, "task_summary": req.task_summary,
            "functional_requirements": req.functional_requirements, "constraints": req.constraints,
            "ambiguities": req.ambiguities, "output_valid": req.output_valid},
        implementation_plan=None if plan is None else {
            "status": plan.status.value, "objective": plan.objective, "test_strategy": plan.test_strategy,
            "steps": [s.model_dump() for s in plan.steps], "risks": plan.risks, "output_valid": plan.output_valid},
        execution_sequence=sequence,
        orchestration=_orchestration(result),
        files_changed=result.files_changed,
        code_changes=code_changes,
        initial_tests=_tests(result.initial_test_result),
        tests=_tests(t),
        test_attempts=result.test_attempts,
        debug=debug,
        verification=None if v is None else VerificationSummary(
            verified=v.verified, llm_claimed_verified=v.llm_claimed_verified,
            overridden_by_tests=bool(v.llm_claimed_verified and not v.verified), backend=v.backend, remote=v.remote,
            requirements_satisfied=v.requirements_satisfied, requirements_failed=v.requirements_failed,
            evidence=v.evidence),
        guardrails=GuardrailSummary(
            counts={k: dict(c) for k, c in counts.items()}, notable=notable,
            by_rule=guardrail_status_by_rule(result.guardrail_events),
            version=", ".join(sorted({g["version"] for g in result.guardrail_events if g.get("version")})) or None),
        agents=agents,
        usage=usage,
        integrations={"mcp_servers": result.mcp_servers, "tool_transport": result.tool_transport,
                      "a2a": v.remote if (v and v.remote) else None},
        errors=result.errors,
        limitations=limitations,
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _na(value: Any, fmt: str = "{}") -> str:
    return "n/a" if value is None else fmt.format(value)


def _tests_md(t: TestSummary | None) -> list[str]:
    if t is None:
        return ["_Not run._"]
    verdict = "no tests collected" if t.no_tests else ("passed" if t.passed else "failed")
    lines = ["| Verdict | Exit code | Found | Passed | Failed | Source |", "|---|---|---|---|---|---|",
             f"| {verdict} | {t.exit_code} | {t.tests_found} | {t.tests_passed} | {t.tests_failed} | {t.verdict_source} |"]
    if t.failures:
        lines += ["", "Failures:", ""] + [f"- {_cell(f)}" for f in t.failures]
    return lines


def _orchestration(result) -> dict[str, Any]:
    log = result.coordination_log or []
    sources = sorted({c["data"].get("source") for c in log if c["kind"] == "decision" and c["data"].get("source")})
    policy = next((c["data"].get("policy") for c in log
                   if c["kind"] == "decision" and c["data"].get("source") == "mock_policy"), None)
    label = ("LLM Manager (real CrewAI agent)" if sources == ["manager_llm"]
             else "deterministic mock policy (no LLM)" if sources and "manager_llm" not in sources
             else "fixed by the architecture" if not sources else "mixed")
    return {"decisions_by": label, "decision_sources": sources, "mock_policy": policy}


def render_markdown(r: RunReport) -> str:
    L = [
        f"# VEXA run report `{r.run_id}`", "",
        "| Field | Value |", "|---|---|",
        f"| Status | **{r.status}**{' (MOCK RUN — scripted agents)' if r.execution_mode == 'mock' else ''} |",
        f"| Requirement | {_cell(r.requirement)} |",
        f"| Architecture | {r.architecture} |",
        f"| Mode | {r.execution_mode} ({r.provider or '-'} / {r.model or '-'}) |",
        f"| Prompt variant | {r.prompt_variant} ({r.prompt_version}) |",
        f"| Tools / Verifier / Sandbox | {r.tool_transport} / {r.verifier_backend} / {r.sandbox_backend} |",
        f"| Duration | {r.total_duration_ms / 1000:.1f} s |",
        f"| Trace id | `{r.trace_id}` |",
    ]
    if r.experiment:
        L.append(f"| Experiment | {_cell(r.experiment)} |")

    L += ["", "## Acceptance criteria", ""]
    if r.acceptance_criteria:
        L += ["| Criterion | Status |", "|---|---|"] + [f"| {_cell(c.criterion)} | {c.status} |" for c in r.acceptance_criteria]
    else:
        L.append("_No acceptance criteria were produced._")

    if r.requirement_analysis:
        ra = r.requirement_analysis
        L += ["", "## Requirement analysis", "", f"{_cell(ra['task_summary'])} (output valid: {ra['output_valid']})", ""]
        L += [f"- {_cell(x)}" for x in ra["functional_requirements"]]
    if r.implementation_plan:
        p = r.implementation_plan
        L += ["", "## Implementation plan", "", f"**Objective:** {_cell(p['objective'])}", ""]
        L += [f"{s['step_number']}. [{s['action']}] {_cell(s['description'])} — {', '.join(s['files_affected']) or '-'}"
              for s in p["steps"]]

    L += ["", f"## Execution sequence ({r.architecture})", "",
          f"Control decisions by: **{r.orchestration.get('decisions_by', 'n/a')}**"]
    if r.orchestration.get("mock_policy"):
        mp = r.orchestration["mock_policy"]
        L.append(f"Mock policy: strategy `{mp['strategy']}` for categories {', '.join(mp['categories'])} "
                 f"(names files: {mp['names_files']}, mixed: {mp['mixed']})")
    L.append("")
    seq = [f"| {s.seq} | {s.kind} | {s.actor} | {s.target or ''} | {_cell(s.detail)[:160]} |"
           for s in r.execution_sequence if s.kind != "event" or r.architecture == "event_driven"]
    if seq:
        L += ["| # | Kind | From | To | Detail |", "|---|---|---|---|---|"] + seq
    else:
        L.append("_No agent was dispatched (the run stopped before orchestration started)._")

    L += ["", "## Code changes", ""]
    if not r.code_changes:
        L.append("_No files were changed in the workspace._")
    for c in r.code_changes:
        who = f" — written by {', '.join(c.written_by)}" if c.written_by else ""
        L += [f"### `{c.path}` ({c.change}, +{c.lines_added}/-{c.lines_removed}){who}", "", "```diff", c.diff.rstrip(), "```"]
        if c.truncated:
            L.append("_(diff truncated)_")

    L += ["", "## Tests", "", "**Final (sandbox):**", ""] + _tests_md(r.tests)
    if r.initial_tests and r.test_attempts > 1:
        L += ["", "**Initial:**", ""] + _tests_md(r.initial_tests)
    L += ["", f"Test runs: {r.test_attempts}"]

    if r.debug:
        L += ["", "## Debugging", "", "| Iteration | Root cause | Fix | Files | Tests pass after |", "|---|---|---|---|---|"]
        L += [f"| {d.iteration} | {_cell(d.root_cause)[:120]} | {_cell(d.fix_applied)[:120]} | {', '.join(d.files)} | "
              f"{_na(d.tests_passed_after)} |" for d in r.debug]

    L += ["", "## Verification", ""]
    if r.verification is None:
        L.append("_The Verifier did not run._")
    else:
        v = r.verification
        L += [f"- Verified: **{v.verified}** (backend: {v.backend})",
              f"- Verifier's own claim: {v.llm_claimed_verified}{' — overridden by the test result' if v.overridden_by_tests else ''}",
              f"- Evidence: {_cell(v.evidence)}"]
        if v.remote:
            L.append(f"- A2A: agent `{v.remote.get('agent')}`, task `{v.remote.get('task_id')}`, state {v.remote.get('state')}")

    L += ["", "## Guardrails", ""]
    if r.guardrails.by_rule:
        L.append("Outcome per rule: " + ", ".join(f"{k} {v}" for k, v in r.guardrails.by_rule.items())
                 + (f" (implementation {r.guardrails.version})" if r.guardrails.version else "") + ".")
        L.append("")
    if r.guardrails.counts:
        L += ["| Rule | Decisions |", "|---|---|"]
        L += [f"| {rule} | {', '.join(f'{k}: {n}' for k, n in sorted(dec.items()))} |"
              for rule, dec in r.guardrails.counts.items()]
    else:
        L.append("_No guardrail decisions were recorded._")
    if r.guardrails.notable:
        L += ["", "Blocked / flagged decisions:", ""]
        L += [f"- {g.get('rule')} **{g.get('decision')}** ({g.get('agent')}): {_cell(g.get('reason', ''))}"
              for g in r.guardrails.notable[:30]]

    L += ["", "## Agents", ""]
    if r.agents:
        L += ["| Agent | Framework | Status | Calls | Time (s) | LLM calls | Tokens in/out | Cost | Tools | "
              "Tool errors | Retries | Blocks | Output valid |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    else:
        L.append("_No agent ran._")
    for a in r.agents:
        tokens = f"{a.input_tokens}/{a.output_tokens}" if a.input_tokens is not None else "n/a"
        cost = f"${a.estimated_cost_usd:.4f}" if a.estimated_cost_usd is not None else "n/a"
        L.append(f"| {a.agent} | {a.framework} | {a.status} | {a.invocations} | {a.duration_ms / 1000:.1f} | {a.llm_calls} | "
                 f"{tokens} | {cost} | {a.tool_calls} | {a.tool_errors} | {a.validation_retries} | {a.guardrail_blocks} | "
                 f"{_na(a.output_valid)} |")

    u = r.usage

    def m(x: Measured, fmt: str = "{}") -> str:
        return fmt.format(x.value) if x.value is not None else f"n/a ({x.unavailable_reason})"

    L += ["", "## Usage", "",
          f"- Tokens in / out / total: {m(u.input_tokens)} / {m(u.output_tokens)} / {m(u.total_tokens)}",
          f"- Estimated cost: {m(u.estimated_cost_usd, '${:.4f}')}",
          f"- LLM calls: {u.llm_calls} · tool calls: {u.tool_calls} · agent invocations: {u.agent_invocations}"]
    mcp = r.integrations.get("mcp_servers") or []
    if mcp:
        L += ["", "## Integrations", ""] + [f"- MCP `{s['name']}`: {s['status']} ({len(s['tools'])} tools)" for s in mcp]
    if r.errors:
        L += ["", "## Errors", ""] + [f"- {_cell(e)}" for e in r.errors]
    if r.limitations:
        L += ["", "## Limitations", ""] + [f"- {x}" for x in r.limitations]
    return "\n".join(L) + "\n"
