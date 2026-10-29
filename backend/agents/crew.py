"""
VEXA M3 — Sequential Software Engineering Crew

The baseline multi-agent workflow:

    RequirementAnalyst
          |
    ProjectAnalyst
          |
    Planner
          |
    Coder
          |
    Tester ─(fail)─> Debugger ─> Tester  (up to MAX_DEBUG_ITER)
          |
    Verifier
          |
    RunResult

This module contains:
- _parse_json_output(): Safely extract JSON from LLM text responses
- parse_requirement_analysis(), parse_project_analysis(), etc.: Contract parsers
- SoftwareEngineeringCrew: The main orchestrator class
  - run_task(workspace_id, requirement) → RunResult

Design:
- Each agent is created fresh per run (avoids state leakage)
- The debug loop is explicit Python, not CrewAI sequential chaining
  (gives us precise control over retry logic)
- Mock LLM injection is supported for deterministic testing
- All workspace access goes through ToolService (M2 security preserved)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, PrivateAttr, create_model

try:
    from crewai.tools import BaseTool
except ImportError:
    BaseTool = object


from backend.agents.config import AgentSettings, LLMFactory, get_agent_settings, infer_provider
from backend.agents.context import RunContext
from backend.agents.contracts import (
    AgentStatus,
    CodingResult,
    DebugIteration,
    ExecutionMode,
    FileChange,
    ImplementationPlan,
    ImplementationStep,
    ProjectAnalysis,
    RequirementAnalysis,
    RunResult,
    AgentTestResult,
    VerificationResult,
)
from backend.agents.prompt_variants import get_prompt_set
from backend.agents.schemas import (
    CodingOutput,
    DebugOutput,
    ImplementationPlanOutput,
    ManagerDecision,
    ProjectAnalysisOutput,
    RequirementAnalysisOutput,
    TesterOutput,
    VerifierOutput,
    extract_json_object,
    make_guardrail,
    validate_output,
)
from backend.agents.tools import WorkspaceToolKit
from backend.core.logging import get_logger
from backend.observability.redaction import redact_text
from backend.guardrails import (
    blocking,
    check_requirement,
    detect_injection,
    enforce_tool_call,
    enforce_tool_output,
    needs_review,
)
from backend.observability.callbacks import (
    ensure_listener,
    flush_events,
    register_crewai_objects,
    unregister_crewai_objects,
)
from backend.observability.redaction import install_log_redaction, redact, register_secret
from backend.observability.tracing import RunObserver
from backend.tools.service import ToolService
from backend.tools.snapshot import diff_snapshots, snapshot

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# JSON response parsing utilities
# ---------------------------------------------------------------------------


def _parse_json_output(text: str) -> dict[str, Any]:
    """Best-effort JSON object extraction (unvalidated). Returns {} on failure."""
    return extract_json_object(text) or {}


def _str(d: dict, key: str, default: str = "") -> str:
    return str(d.get(key, default))


def _list(d: dict, key: str) -> list:
    v = d.get(key, [])
    return v if isinstance(v, list) else []


def _int(d: dict, key: str, default: int = 0) -> int:
    try:
        return int(d.get(key, default))
    except (TypeError, ValueError):
        return default


def _bool(d: dict, key: str, default: bool = False) -> bool:
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")


def _invalid(errors: list[str]) -> dict[str, Any]:
    """Common fields for a result whose LLM output failed schema validation."""
    return {
        "status": AgentStatus.partial,
        "output_valid": False,
        "validation_errors": errors,
        "errors": ["LLM output failed schema validation: " + "; ".join(errors[:5])],
    }


# ---------------------------------------------------------------------------
# Per-agent result parsers (LLM output → validated schema → typed contract)
#
# A valid output yields status=success. An invalid one is never silently
# accepted: the result is marked output_valid=False / status=partial and keeps
# only best-effort values so the run can be inspected.
# ---------------------------------------------------------------------------


def parse_requirement_analysis(raw: str, requirement: str, duration_ms: float) -> RequirementAnalysis:
    out, errs = validate_output(raw, RequirementAnalysisOutput)
    if out is not None:
        return RequirementAnalysis(
            status=AgentStatus.success, summary=out.task_summary, duration_ms=duration_ms,
            original_requirement=requirement, **out.model_dump(),
        )
    d = _parse_json_output(raw)
    return RequirementAnalysis(
        summary=_str(d, "task_summary", raw[:200] if raw else "parse error"),
        duration_ms=duration_ms,
        original_requirement=requirement,
        task_summary=_str(d, "task_summary"),
        functional_requirements=_list(d, "functional_requirements"),
        constraints=_list(d, "constraints"),
        acceptance_criteria=_list(d, "acceptance_criteria"),
        ambiguities=_list(d, "ambiguities"),
        affected_areas=_list(d, "affected_areas"),
        **_invalid(errs),
    )


def parse_project_analysis(raw: str, workspace_id: str, duration_ms: float) -> ProjectAnalysis:
    out, errs = validate_output(raw, ProjectAnalysisOutput)
    if out is not None:
        return ProjectAnalysis(
            status=AgentStatus.success, summary=out.project_context[:200], duration_ms=duration_ms,
            workspace_id=workspace_id, **out.model_dump(),
        )
    d = _parse_json_output(raw)
    return ProjectAnalysis(
        summary=_str(d, "project_context", raw[:200] if raw else "parse error"),
        duration_ms=duration_ms,
        workspace_id=workspace_id,
        total_files=_int(d, "total_files"),
        languages=d.get("languages", {}) if isinstance(d.get("languages"), dict) else {},
        important_files=_list(d, "important_files"),
        relevant_files=_list(d, "relevant_files"),
        relevant_file_contents=d.get("relevant_file_contents", {}) if isinstance(d.get("relevant_file_contents"), dict) else {},
        existing_tests=_list(d, "existing_tests"),
        git_status=_str(d, "git_status"),
        project_context=_str(d, "project_context"),
        **_invalid(errs),
    )


def parse_implementation_plan(raw: str, duration_ms: float) -> ImplementationPlan:
    out, errs = validate_output(raw, ImplementationPlanOutput)
    if out is not None:
        data = out.model_dump()
        data["steps"] = [ImplementationStep(**st) for st in data["steps"]]
        return ImplementationPlan(status=AgentStatus.success, summary=out.objective, duration_ms=duration_ms, **data)
    d = _parse_json_output(raw)
    steps = [
        ImplementationStep(
            step_number=_int(st, "step_number", i + 1),
            description=_str(st, "description"),
            files_affected=_list(st, "files_affected"),
            action=_str(st, "action", "patch"),
        )
        for i, st in enumerate(_list(d, "steps")) if isinstance(st, dict)
    ]
    return ImplementationPlan(
        summary=_str(d, "objective", raw[:200] if raw else "parse error"),
        duration_ms=duration_ms,
        objective=_str(d, "objective"),
        steps=steps,
        files_to_modify=_list(d, "files_to_modify"),
        files_to_create=_list(d, "files_to_create"),
        test_strategy=_str(d, "test_strategy"),
        risks=_list(d, "risks"),
        **_invalid(errs),
    )


def _file_changes(items: list) -> list[FileChange]:
    return [
        FileChange(path=_str(c, "path"), action=_str(c, "action", "patched"), description=_str(c, "description"))
        for c in items if isinstance(c, dict)
    ]


def parse_coding_result(raw: str, duration_ms: float) -> CodingResult:
    out, errs = validate_output(raw, CodingOutput)
    if out is not None:
        changes = [FileChange(**c.model_dump()) for c in out.files_changed]
        return CodingResult(
            # No files changed is a legitimate but noteworthy outcome.
            status=AgentStatus.success if changes else AgentStatus.partial,
            summary=out.implementation_notes or f"{len(changes)} file(s) changed",
            duration_ms=duration_ms,
            files_changed=changes,
            implementation_notes=out.implementation_notes,
        )
    d = _parse_json_output(raw)
    changes = _file_changes(_list(d, "files_changed"))
    return CodingResult(
        summary=_str(d, "implementation_notes", f"{len(changes)} file(s) changed"),
        duration_ms=duration_ms,
        files_changed=changes,
        implementation_notes=_str(d, "implementation_notes"),
        **_invalid(errs),
    )


def parse_test_result(raw: str, duration_ms: float) -> AgentTestResult:
    """
    Legacy parser for an LLM-reported test result.

    Not used by the pipeline any more: verdicts come from the sandbox
    (see SoftwareEngineeringCrew._run_tester). Kept for tooling that still
    parses stored tester transcripts.
    """
    d = _parse_json_output(raw)
    passed = _bool(d, "passed") or (_bool(d, "success") if "success" in d else False)
    if "exit_code" in d:
        try:
            exit_code = int(d["exit_code"])
            # pytest exit code 0 is success. Exit code 5 means "no tests collected",
            # which is expected for HTML/JS/CSS projects that don't have python tests.
            if exit_code == 0 or exit_code == 5:
                passed = True
        except (TypeError, ValueError):
            exit_code = None
    else:
        exit_code = None

    return AgentTestResult(
        status=AgentStatus.success if passed else AgentStatus.failed,
        summary=f"Tests {'passed' if passed else 'failed'} (exit_code={exit_code})",
        duration_ms=duration_ms,
        passed=passed,
        exit_code=exit_code,
        tests_found=_int(d, "tests_found"),
        tests_passed=_int(d, "tests_passed"),
        tests_failed=_int(d, "tests_failed"),
        failures=_list(d, "failures"),
        stdout=_str(d, "stdout"),
        stderr=_str(d, "stderr"),
        timed_out=_bool(d, "timed_out"),
        errors=[] if d else ["Could not parse JSON from LLM response"],
    )


_PYTEST_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")
_PYTEST_FAILED_LINE_RE = re.compile(r"^(FAILED|ERROR) (.+)$", re.MULTILINE)


def summarise_pytest_output(stdout: str) -> dict[str, Any]:
    """Deterministically extract counts and failing test ids from pytest output."""
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    tail = "\n".join(stdout.strip().splitlines()[-5:]) if stdout else ""
    for n, kind in _PYTEST_COUNT_RE.findall(tail):
        key = "error" if kind.startswith("error") else kind
        if key in counts:
            counts[key] += int(n)
    failures = [m[1].strip() for m in _PYTEST_FAILED_LINE_RE.findall(stdout or "")]
    return {
        "tests_passed": counts["passed"],
        "tests_failed": counts["failed"] + counts["error"],
        "tests_found": counts["passed"] + counts["failed"] + counts["error"] + counts["skipped"],
        "failures": failures,
    }


def parse_debug_result(raw: str, iteration: int, duration_ms: float) -> tuple[str, str, list[FileChange]]:
    """
    Parse one Debugger iteration output.
    Returns (root_cause, fix_applied, files_changed).
    """
    out, errs = validate_output(raw, DebugOutput)
    if out is not None:
        return out.root_cause, out.fix_applied, [FileChange(**c.model_dump()) for c in out.files_changed]
    d = _parse_json_output(raw)
    root_cause = _str(d, "root_cause", "Unknown root cause")
    if errs:
        root_cause += f" [invalid debugger output: {'; '.join(errs[:3])}]"
    return root_cause, _str(d, "fix_applied", "No fix description"), _file_changes(_list(d, "files_changed"))


def parse_verification_result(raw: str, duration_ms: float) -> VerificationResult:
    out, errs = validate_output(raw, VerifierOutput)
    if out is not None:
        return VerificationResult(
            status=AgentStatus.success if out.verified else AgentStatus.failed,
            summary=("Requirements verified and satisfied." if out.verified
                     else "Verification failed — requirements not fully met."),
            duration_ms=duration_ms,
            **out.model_dump(),
        )
    d = _parse_json_output(raw)
    fields = _invalid(errs)
    fields["status"] = AgentStatus.failed  # an unparseable verdict is never a pass
    return VerificationResult(
        summary="Verification output was invalid.",
        duration_ms=duration_ms,
        verified=False,
        requirements_satisfied=_list(d, "requirements_satisfied"),
        requirements_failed=_list(d, "requirements_failed"),
        files_changed=_list(d, "files_changed"),
        remaining_risks=_list(d, "remaining_risks"),
        evidence=_str(d, "evidence"),
        **fields,
    )


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

# Scripted, schema-valid responses keyed by agent id. Mock mode never builds an
# LLM and never touches the network; tools and the sandboxed test run are real.
MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "RequirementAnalyst": {
        "task_summary": "Mock requirement analysis",
        "functional_requirements": ["(mock) requirement understood"],
        "constraints": ["Do not break existing behaviour"],
        "acceptance_criteria": ["Existing test suite passes"],
        "ambiguities": [],
        "affected_areas": [],
    },
    "ProjectAnalyst": {
        "total_files": 0, "languages": {}, "important_files": [], "relevant_files": [],
        "relevant_file_contents": {}, "existing_tests": [], "git_status": "",
        "project_context": "Mock project analysis",
    },
    "Planner": {
        "objective": "Mock plan",
        "steps": [{"step_number": 1, "description": "Mock step (no changes)", "files_affected": [], "action": "verify"}],
        "files_to_modify": [], "files_to_create": [],
        "test_strategy": "Run the existing test suite", "risks": [],
    },
    "Coder": {"files_changed": [], "implementation_notes": "Mock mode: no files were modified"},
    "Tester": {"failures": []},
    "Debugger": {
        "root_cause": "Mock mode cannot diagnose failures", "root_cause_category": "unknown",
        "fix_applied": "None (mock mode)", "files_changed": [],
    },
    "Verifier": {
        "verified": True, "requirements_satisfied": ["Existing test suite passes"],
        "requirements_failed": [], "tests_passed": True, "files_changed": [],
        "remaining_risks": ["Mock run: no real implementation was produced"],
        "evidence": "Mock verifier; tests_passed is overridden by the sandbox result",
    },
}


# Mock agents still exercise the real tool path (guardrails, tracing, MCP when
# selected) with these scripted, read-only calls. Their results are not used
# to build the scripted answers, and the spans are tagged origin=scripted.
MOCK_TOOL_SCRIPT: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "ProjectAnalyst": [("inspect_project", {}), ("list_files", {"path": "."})],
    "Planner": [("search_code", {"query": "def "})],
    "Coder": [("list_files", {"path": "."}), ("python_api_docs", {"symbol": "pathlib.Path"})],
    "Debugger": [("search_code", {"query": "assert"})],
    "Verifier": [("git_diff", {}), ("list_files", {"path": "."})],
}


class _MockAgent:
    """Stand-in for a CrewAI Agent in mock mode (no LLM is constructed)."""

    def __init__(self, agent_id: str, role: str, tools: list) -> None:
        self.agent_id = agent_id
        self.role = role
        self.tools = tools


class _MockTask:
    def __init__(self, description: str, agent: Any) -> None:
        self.description = description
        self.agent = agent


# ---------------------------------------------------------------------------
# SoftwareEngineeringCrew
# ---------------------------------------------------------------------------


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "(none provided)"


def apply_verification_ground_truth(
    result: VerificationResult, final_test: AgentTestResult | None,
) -> VerificationResult:
    """
    Replace LLM claims about tests with the sandbox result.

    ``verified`` can only stay true if the tests really passed, or if there are
    no tests at all (in which case the run can be at most 'partial').
    """
    result.llm_claimed_verified = result.verified
    tests_passed = bool(final_test and final_test.passed)
    no_tests = bool(final_test and final_test.no_tests)
    result.tests_passed = tests_passed
    if result.verified and not tests_passed and not no_tests:
        result.verified = False
        result.status = AgentStatus.failed
        result.errors.append("Verifier claimed success but the sandboxed test run failed; overridden.")
        result.summary = "Verification failed — tests do not pass."
    return result


def determine_run_status(
    verification: VerificationResult | None, final_test: AgentTestResult | None,
) -> AgentStatus:
    """success = verified AND tests pass; partial = one of them; failed otherwise."""
    verified = bool(verification and verification.verified)
    tests_passed = bool(final_test and final_test.passed)
    no_tests = bool(final_test and final_test.no_tests)
    if verified and tests_passed:
        return AgentStatus.success
    if tests_passed or (verified and no_tests):
        return AgentStatus.partial
    return AgentStatus.failed


def config_fingerprint(config: dict[str, Any], exclude: tuple[str, ...] = ()) -> str:
    """Stable 16-hex hash of a run configuration (optionally ignoring the experimental variables)."""
    import hashlib
    body = {k: v for k, v in config.items() if k not in exclude}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def guardrail_config_version() -> str:
    """Hash of the guard rules, tool policy and argument schemas in force."""
    import hashlib

    from backend.guardrails import RULES, TOOL_ARG_SCHEMAS, TOOL_POLICY
    body = {"rules": RULES, "policy": {k: sorted(v) for k, v in TOOL_POLICY.items()},
            "schemas": {k: v.model_json_schema() for k, v in TOOL_ARG_SCHEMAS.items()}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:12]


def estimate_cost(
    usage_available: bool,
    input_tokens: int,
    output_tokens: int,
    input_price_per_1m: float | None,
    output_price_per_1m: float | None,
    *,
    model: str,
    used_fallback: bool,
) -> tuple[float | None, str]:
    """
    Return (cost_usd, basis). Cost is None — never 0.0 — when it cannot be known.
    """
    if not usage_available:
        return None, "unavailable: provider returned no usage"
    if input_price_per_1m is None or output_price_per_1m is None:
        return None, "unavailable: no pricing configured (VEXA_LLM_INPUT/OUTPUT_COST_PER_1M)"
    if used_fallback:
        return None, "unavailable: fallback model used; per-model token split unknown"
    cost = (input_tokens / 1_000_000) * input_price_per_1m + (output_tokens / 1_000_000) * output_price_per_1m
    return cost, f"estimate: configured price for {model}"


class SoftwareEngineeringCrew:
    """
    The VEXA baseline sequential multi-agent software engineering workflow.

    Orchestrates seven agents:
        RequirementAnalyst → ProjectAnalyst → Planner → Coder →
        Tester → (Debugger → Tester)* → Verifier

    The debug loop is explicit Python rather than CrewAI sequential chaining
    so we have precise control over retry counting and context threading.

    Parameters
    ----------
    tool_service : ToolService
        The M2 ToolService. All workspace access goes through this.
    settings : AgentSettings | None
        Agent/LLM settings. If None, reads from environment.
    llm : Any
        Pre-built LLM object (real mode only).
    responder : Callable[[str, str], str] | None
        Mock mode only: ``responder(agent_id, task_description) -> raw text``.
        Defaults to the scripted MOCK_RESPONSES. Tests use this to script
        specific agent behaviour without any LLM.
    """

    def __init__(
        self,
        tool_service: ToolService | None = None,
        settings: AgentSettings | None = None,
        llm: Any = None,
        responder: Callable[[str, str], str] | None = None,
    ) -> None:
        self._svc = tool_service or ToolService()
        self._settings = settings or get_agent_settings()
        self._responder = responder
        self._credential_handle: str | None = None
        self._brief: str | None = None  # hierarchical: manager's brief for the next delegated task
        self._p = get_prompt_set(self._settings.prompt_variant)
        self._prompt_pin_error: str | None = None
        pin = self._settings.prompt_version_pin
        if pin and pin != self._p.version:  # rerun of a historical configuration
            from backend.db.registry import get_registry
            archived = get_registry().get_archived_prompt(pin)
            if archived is None:
                self._prompt_pin_error = (f"prompt version {pin} is not in the prompt archive; the historical "
                                          "configuration cannot be reproduced exactly")
            else:
                from backend.agents.prompt_variants import PromptSet
                self._p = PromptSet.from_archive(archived["variant"], archived["texts"])
        self._llm = llm  # If None, built lazily when first needed
        self._mode = ExecutionMode.mock

    def _get_llm(self) -> Any:
        if self._llm is None:
            self._llm = LLMFactory.build(self._settings)
        return self._llm

    # ------------------------------------------------------------------
    # Agent factory helpers
    # ------------------------------------------------------------------

    def _make_agent(self, role: str, goal: str, backstory: str, tools: list, agent_id: str = "") -> Any:
        """Build a CrewAI Agent with the standard VEXA configuration (mock: a stub, no LLM)."""
        if self._mode == ExecutionMode.mock:
            return _MockAgent(agent_id, role, tools)
        from crewai import Agent
        return Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            llm=self._get_llm(),
            tools=tools,
            max_iter=self._settings.agent_max_iter,
            verbose=self._settings.agent_verbose,
            allow_delegation=False,
        )

    def _make_task(
        self,
        description: str,
        agent: Any,
        expected_output: str = "JSON object",
        schema: type[BaseModel] | None = None,
    ) -> Any:
        """
        Build a single-agent CrewAI Task.

        When *schema* is given (real mode) the task gets a CrewAI guardrail that
        validates the answer against it and re-prompts the agent on failure.
        """
        if self._brief:
            description += f"\n\nBRIEF FROM YOUR ENGINEERING MANAGER:\n{self._brief}\n"
        if self._mode == ExecutionMode.mock:
            return _MockTask(description, agent)
        from crewai import Task

        # Guardrail against open-source models hallucinating a "JSON" tool call
        if "JSON" in expected_output.upper() or "JSON" in description.upper():
            description += (
                "\n\nCRITICAL: DO NOT use a tool call to output your JSON response! "
                "There is no tool named 'JSON'. You MUST output the raw JSON text directly "
                "as your final answer."
            )
            
        task_kwargs: dict[str, Any] = {}
        if schema is not None:
            task_kwargs["guardrail"] = make_guardrail(schema)
            task_kwargs["guardrail_max_retries"] = self._settings.output_validation_retries
        return Task(
            description=description,
            expected_output=expected_output,
            agent=agent,
            **task_kwargs,
        )

    def _run_single_agent_crew(self, ctx: RunContext, agent: Any, task: Any) -> str:
        """Run a single-agent Crew and return the string output. Accumulate usage."""
        from backend.guardrails import RunBudgetExceeded, check_token_budget
        try:  # G7: also between agent turns that are not dispatches (e.g. Manager decisions)
            check_token_budget(ctx.observer, getattr(ctx, "max_run_tokens", None))
        except RunBudgetExceeded as exc:
            ctx.guard("run_token_budget", ctx.current_agent, "blocked", str(exc), action="stop")
            raise
        if ctx.execution_mode == ExecutionMode.mock.value:
            if self._settings.mock_step_delay_seconds:
                time.sleep(self._settings.mock_step_delay_seconds)
            agent_id = getattr(agent, "agent_id", "")
            self._run_scripted_tools(ctx, agent)
            if self._responder is not None:
                return self._responder(agent_id, getattr(task, "description", ""))
            if agent_id not in MOCK_RESPONSES:
                raise RuntimeError(f"No mock response for agent '{agent_id}'")
            return json.dumps(MOCK_RESPONSES[agent_id])

        from crewai import Crew, Process
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=self._settings.agent_verbose,
        )

        if ctx.observer:
            register_crewai_objects(ctx.observer, ctx.current_agent, agent, task)
        try:
            result = crew.kickoff()
        except Exception as e:
            flush_events()
            unregister_crewai_objects(agent, task)
            err_str = str(e)
            if "litellm.NotFoundError" in err_str or "does not exist" in err_str:
                raise Exception(
                    "The selected LLM model does not exist or your API key lacks access. "
                    "Please check your Model String and API Key in the configuration."
                ) from None
            elif "guardrail validation" in err_str:
                raise Exception(
                    "Agent output failed schema validation after "
                    f"{self._settings.output_validation_retries} retries: {err_str[-500:]}"
                ) from None
            elif "Failed to parse tool call arguments as JSON" in err_str or "tool_use_failed" in err_str:
                m = re.search(r'"message"\s*:\s*"([^"]{0,300})', err_str)
                raise Exception(
                    "The model produced an invalid tool call (rejected by the provider): "
                    + redact_text(m.group(1) if m else err_str[-300:])
                ) from None
            else:
                # If it's another API error, clean it up slightly if it's huge
                if len(err_str) > 300 and "{" in err_str:
                    try:
                        parsed = json.loads(err_str[err_str.find("{"):])
                        msg = parsed.get("error", {}).get("message")
                    except (ValueError, AttributeError):
                        msg = None
                    if msg:
                        raise Exception(f"AI Provider Error: {msg}") from None
                raise Exception(f"AI Execution Error: {err_str}") from None
        
        flush_events()
        unregister_crewai_objects(agent, task)

        # Token usage is NOT read from crew.usage_metrics: CrewAI reports the shared LLM
        # instance's cumulative total there, so summing it per crew double counts.
        # Run totals come from per-call LLM events instead (RunObserver.usage_totals).

        # CrewAI 1.x returns a CrewOutput object; extract raw text
        if hasattr(result, "raw"):
            return str(result.raw)
        return str(result)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_task(
        self,
        workspace_id: str,
        requirement: str,
        execution_mode: str = "mock",
        ctx: RunContext | None = None,
        architecture: str = "sequential",
        metadata: dict[str, Any] | None = None,
        guardrail_confirmed: bool = False,
    ) -> RunResult:
        """
        Execute one run under the chosen orchestration architecture.

        guardrail_confirmed: a human confirmed a requirement that G1 flagged for review.

        Parameters
        ----------
        workspace_id : str
            ID of the M2 workspace to operate on.
        requirement : str
            Natural-language software task description.
        execution_mode : str
            'mock' (default) for deterministic mock execution or 'real' for live LLM.
        ctx : RunContext | None
            Optional pre-initialized execution context for external observability.
        architecture : str
            Name of a registered architecture (see backend.orchestration).

        Returns
        -------
        RunResult
            Complete structured result of the run.
        """
        # Unknown modes are rejected: they must never silently reach a real LLM.
        mode = ExecutionMode(execution_mode)
        execution_mode = mode.value
        self._mode = mode
        from backend.orchestration import get_architecture
        arch = get_architecture(architecture)  # ValueError for unknown names

        if ctx is None:
            run_id = str(uuid.uuid4())
            ctx = RunContext(workspace_id=workspace_id, requirement=requirement, run_id=run_id,
                             architecture=arch.name)
        else:
            run_id = ctx.run_id
        ctx.execution_mode = execution_mode
        ctx.architecture = arch.name
        t_total_start = time.perf_counter()

        logger.info("run_started | run_id=%s workspace=%s mode=%s", run_id, workspace_id, execution_mode)

        install_log_redaction()
        for secret in (self._settings.llm_api_key, self._settings.llm_fallback_api_key, self._settings.adk_api_key):
            register_secret(secret)

        if mode == ExecutionMode.real:
            ctx.provider = infer_provider(self._settings.llm_model, self._settings.llm_provider)
            ctx.model = self._settings.llm_model
        else:
            ctx.provider, ctx.model = "mock", "scripted"
        ctx.observer = RunObserver(run_id, {
            "architecture": arch.name, "execution_mode": execution_mode,
            "provider": ctx.provider, "model": ctx.model, "workspace_id": workspace_id,
        })
        ctx.observer.guard_sink = ctx.guard
        ctx.state.on_access = lambda a: ctx.observer.state_event(a.kind, a.key, a.agent, a.version)
        if self._settings.verifier_backend == "adk_a2a":
            ctx.observer.set_framework("Verifier", "google-adk")
        ctx.observer.set_framework("Tester", "vexa-sandbox+crewai")

        result = RunResult(
            run_id=run_id,
            workspace_id=workspace_id,
            requirement=requirement,
            architecture=arch.name,
            execution_mode=execution_mode,
            provider=ctx.provider,
            model=ctx.model,
            sandbox_backend=self._svc.sandbox_backend,
            prompt_variant=self._p.name,
            prompt_version=self._p.version,
            tool_transport=self._settings.tool_transport,
            verifier_backend=self._settings.verifier_backend,
            metadata=dict(metadata or {}),
            prompt_versions=self._p.agent_versions,
        )
        result.config = self.run_config(arch.name, mode, result.metadata)
        result.config_fingerprint = config_fingerprint(result.config)
        try:  # keep the exact prompt texts so this configuration can be rerun later
            from backend.db.registry import get_registry
            get_registry().archive_prompt_set(self._p)
        except Exception as exc:  # persistence problems must not stop the run
            logger.warning("prompt_archive_failed | %s", exc)

        kit: WorkspaceToolKit | None = None
        before: dict[str, str | None] | None = None
        repo_dir = None
        try:
            # Every pre-run step is inside this block: a configuration error
            # still yields a stored, reportable (failed) RunResult.
            if self._prompt_pin_error:
                raise ValueError(self._prompt_pin_error)
            if not self._svc.workspace_exists(workspace_id):
                raise ValueError(f"Workspace '{workspace_id}' does not exist")
            repo_dir = self._svc._manager.require(workspace_id)
            before = snapshot(repo_dir)
            ctx.workspace_snapshot = (repo_dir, before)  # ground truth for "what changed"

            from backend.orchestration.base import RunHandle
            ctx.max_tool_calls_per_agent = self._settings.max_tool_calls_per_agent
            ctx.max_run_seconds = self._settings.max_run_seconds
            ctx.max_run_tokens = self._settings.max_run_tokens
            findings = check_requirement(requirement)  # G1
            hard, review = blocking(findings), needs_review(findings)
            for f in hard:
                ctx.guard("requirement_screen", "user", "blocked", f"{f.rule}: {f.match}", severity="block")
            if hard:
                raise ValueError("Requirement rejected by guardrails: " + ", ".join(f.rule for f in hard))
            for f in review:
                if guardrail_confirmed:
                    ctx.guard("requirement_screen", "user", "flagged", f"{f.rule}: {f.match}", action="proceed",
                              severity="review", confirmed_by="user")
                else:
                    ctx.guard("requirement_screen", "user", "indeterminate", f"{f.rule}: {f.match}",
                              action="stop", severity="review")
            if review and not guardrail_confirmed:
                raise ValueError("Requirement needs human confirmation (guardrail review): "
                                 + ", ".join(f.rule for f in review))
            if not findings:
                ctx.guard("requirement_screen", "user", "allowed", "no blocking or review pattern found")

            ctx.injection_classifier = self._injection_classifier(mode)
            if mode == ExecutionMode.real:
                ensure_listener()
                if self._llm is None:
                    self._llm = LLMFactory.build(self._settings)
            ctx.state.write("requirement", requirement, author="user")
            kit = WorkspaceToolKit(self._svc, workspace_id, ctx=ctx)
            self._start_mcp_servers(ctx, kit, result)
            handle = RunHandle(
                runtime=self,
                ctx=ctx,
                result=result,
                kit=kit,
                max_debug_iterations=self._settings.debug_max_iter,
            )
            arch.execute(handle)
            result.status = determine_run_status(result.verification_result, result.final_test_result)
            for path in self._actual_changes(ctx):  # agents may change files without reporting them
                handle._file_changed(path)
            if mode == ExecutionMode.mock and not result.files_changed and result.status == AgentStatus.success:
                # Scripted agents changed nothing: passing pre-existing tests is not an implementation.
                result.status = AgentStatus.partial  # explained in the report's limitations

        except Exception as exc:
            logger.exception("run_failed | run_id=%s error=%s", run_id, exc)
            result.errors.append(str(exc))
            result.status = AgentStatus.failed

        finally:
            for bridge in (kit.mcp.values() if kit is not None else ()):
                bridge.close()
            if self._credential_handle:
                from backend.a2a_bridge.embedded import release_credentials
                release_credentials(self._credential_handle)
                self._credential_handle = None
            if before is not None and repo_dir is not None:
                try:
                    result.code_changes = [d.model_dump() for d in diff_snapshots(before, snapshot(repo_dir))]
                except Exception as exc:  # diagnostics must not mask the run result
                    result.errors.append(f"Could not compute code diff: {exc}")
            ctx.finish()
            elapsed_ms = (time.perf_counter() - t_total_start) * 1000
            result.total_duration_ms = elapsed_ms
            result.finished_at = datetime.now(UTC)

            # Map usage and cost metrics (each LLM call counted once, from CrewAI LLM events)
            usage = ctx.observer.usage_totals()
            ctx.usage_available = usage["usage_available"]
            ctx.input_tokens = usage["input_tokens"] or 0
            ctx.output_tokens = usage["output_tokens"] or 0
            ctx.total_tokens = usage["total_tokens"] or 0
            result.usage_available = ctx.usage_available
            result.input_tokens = ctx.input_tokens
            result.output_tokens = ctx.output_tokens
            result.total_tokens = ctx.total_tokens
            state = getattr(self._llm, "vexa_state", None) if mode == ExecutionMode.real else None
            used_fallback = bool(state and state.get("using_fallback"))
            result.models_used = [m for m in (
                ctx.model if mode == ExecutionMode.real else None,
                self._settings.llm_fallback_model if used_fallback else None,
            ) if m]
            cost, basis = estimate_cost(
                ctx.usage_available, ctx.input_tokens, ctx.output_tokens,
                self._settings.llm_input_cost_per_1m, self._settings.llm_output_cost_per_1m,
                model=ctx.model or "", used_fallback=used_fallback,
            )
            result.estimated_cost_usd = cost
            result.cost_basis = basis
            ctx.estimated_cost_usd = cost

            result.test_attempts = ctx.test_attempts
            result.current_agent = ctx.current_agent
            result.events = [e.model_dump(mode="json") for e in ctx.events]
            result.coordination_log = [c.model_dump(mode="json") for c in ctx.coordination]
            result.guardrail_events = list(ctx.guardrail_events)
            result.state = ctx.state.to_dict()
            ctx.observer.close(result.status.value, "; ".join(result.errors) or None)
            trace = ctx.observer.export()
            result.trace_id = trace["trace_id"]
            result.trace = {"spans": trace["spans"], "callback_events": trace["callback_events"]}
            result.agent_metrics = self._price_agents(trace["agent_metrics"], used_fallback)
            result.file_provenance = trace["file_provenance"]
            # Final pass: nothing secret-shaped leaves the run (agent errors, outputs, events).
            redacted = RunResult.model_validate(redact(result.model_dump()))
            for field_name in RunResult.model_fields:
                setattr(result, field_name, getattr(redacted, field_name))

            logger.info(
                "run_completed | run_id=%s status=%s duration_ms=%.1f",
                run_id, result.status.value, elapsed_ms
            )

        return result

    def _price_agents(self, metrics: dict[str, dict[str, Any]], used_fallback: bool) -> dict[str, dict[str, Any]]:
        """Per-agent cost estimate, only where usage and prices are both known."""
        pin, pout = self._settings.llm_input_cost_per_1m, self._settings.llm_output_cost_per_1m
        for m in metrics.values():
            if m.get("usage_available") and pin is not None and pout is not None and not used_fallback:
                m["estimated_cost_usd"] = (m["input_tokens"] * pin + m["output_tokens"] * pout) / 1_000_000
            else:
                m["estimated_cost_usd"] = None
        return metrics

    # ------------------------------------------------------------------
    # Public agent steps (used by every architecture)
    #
    # Each step runs one agent and publishes its output to the run's
    # SharedState with provenance (which state entries it was derived from).
    # ------------------------------------------------------------------

    def _publish(self, ctx: RunContext, key: str, value: Any, author: str, inputs: tuple[str, ...]) -> None:
        derived = [e.entry_id for k in inputs if (e := ctx.state.latest(k)) is not None]
        ctx.state.write(key, value, author=author, derived_from=derived)
        if hasattr(value, "output_valid"):  # G8: final schema check of every agent output
            if value.output_valid:
                ctx.guard("output_schema", author, "allowed", f"{type(value).__name__} validated")
            else:
                ctx.guard("output_schema", author, "blocked",
                          "; ".join(value.validation_errors[:3]) or "invalid output",
                          action="record", downstream="result marked partial/failed")

    def analyze_requirements(self, ctx: RunContext, requirement: str) -> RequirementAnalysis:
        r = self._run_requirement_analyst(ctx, requirement)
        self._publish(ctx, "requirement_analysis", r, "RequirementAnalyst", ("requirement",))
        return r

    def analyze_project(self, ctx: RunContext, kit: WorkspaceToolKit, req: RequirementAnalysis) -> ProjectAnalysis:
        r = self._run_project_analyst(ctx, kit, req)
        for path, snippet in r.relevant_file_contents.items():  # G6: repo content forwarded to later prompts
            for f in detect_injection(snippet):
                ctx.guard("repo_content", "ProjectAnalyst", "flagged", f"{f.rule} in {path}: {f.match}")
        self._publish(ctx, "project_analysis", r, "ProjectAnalyst", ("requirement_analysis",))
        return r

    def plan(self, ctx: RunContext, kit: WorkspaceToolKit, req: RequirementAnalysis,
             proj: ProjectAnalysis) -> ImplementationPlan:
        r = self._run_planner(ctx, kit, req, proj)
        self._publish(ctx, "implementation_plan", r, "Planner", ("requirement_analysis", "project_analysis"))
        return r

    def code(self, ctx: RunContext, kit: WorkspaceToolKit, plan: ImplementationPlan, proj: ProjectAnalysis,
             req: RequirementAnalysis | None = None) -> CodingResult:
        r = self._run_coder(ctx, kit, plan, proj, req)
        self._publish(ctx, "code_changes", r, "Coder", ("implementation_plan", "project_analysis"))
        return r

    def test(self, ctx: RunContext, kit: WorkspaceToolKit) -> AgentTestResult:
        r = self._run_tester(ctx, kit, ctx.workspace_id)
        self._publish(ctx, "test_result", r, "Tester", ("code_changes", "debug_report"))
        return r

    def debug(self, ctx: RunContext, kit: WorkspaceToolKit, coding: CodingResult, test: AgentTestResult,
              iteration: int, max_iterations: int, req: RequirementAnalysis | None = None,
              plan: ImplementationPlan | None = None) -> tuple[DebugIteration, bool]:
        record, applied = self._run_debugger(ctx, kit, coding, test, iteration, max_iterations, req, plan)
        self._publish(ctx, "debug_report", record, "Debugger", ("test_result", "code_changes"))
        return record, applied

    @staticmethod
    def _check_acceptance(ctx: RunContext, req: RequirementAnalysis | None, v: VerificationResult) -> None:
        """G8: a positive verdict must account for every acceptance criterion (recorded, not rewritten)."""
        from backend.agents.reporting import _criterion_status
        criteria = list(req.acceptance_criteria) if req else []
        if not criteria:
            ctx.guard("acceptance_check", "Verifier", "indeterminate", "no acceptance criteria to check against")
            return
        unassessed = [c for c in criteria
                      if _criterion_status(c, v.requirements_satisfied, v.requirements_failed) == "unassessed"]
        if v.verified and unassessed:
            ctx.guard("acceptance_check", "Verifier", "flagged",
                      f"verified, but {len(unassessed)}/{len(criteria)} criteria were not assessed: "
                      + "; ".join(unassessed[:3]))
        else:
            ctx.guard("acceptance_check", "Verifier", "allowed",
                      f"{len(criteria) - len(unassessed)}/{len(criteria)} criteria assessed (verified={v.verified})")

    def run_config(self, architecture: str, mode: ExecutionMode, metadata: dict[str, Any]) -> dict[str, Any]:
        """Every setting that can change an outcome — the basis of the configuration fingerprint."""
        from backend.core.config import get_settings
        st = self._settings
        real = mode == ExecutionMode.real
        cfg: dict[str, Any] = {
            "schema": "vexa.run-config/v1",
            "architecture": architecture,
            "execution_mode": mode.value,
            "model": {"provider": infer_provider(st.llm_model, st.llm_provider), "model": st.llm_model,
                      "temperature": st.llm_temperature, "fallback_model": st.llm_fallback_model or None,
                      "adk_model": (st.adk_model or st.llm_model) if st.verifier_backend == "adk_a2a" else None}
            if real else {"model": "mock:scripted"},
            "prompts": {"variant": self._p.name, "version": self._p.version, "agents": self._p.agent_versions},
            "tools": {"transport": st.tool_transport,
                      "docs_search": bool(real and st.docs_search_api_key),
                      "code_intel": st.tool_transport == "mcp"},
            "verifier_backend": st.verifier_backend,
            "sandbox_backend": self._svc.sandbox_backend,
            "budgets": {"agent_max_iter": st.agent_max_iter, "debug_max_iter": st.debug_max_iter,
                        "max_run_tokens": st.max_run_tokens,
                        "output_validation_retries": st.output_validation_retries,
                        "max_tool_calls_per_agent": st.max_tool_calls_per_agent,
                        "max_run_seconds": st.max_run_seconds,
                        "manager_revision_budget": st.manager_revision_budget},
            "guardrails": {"version": guardrail_config_version(),
                           "injection_classifier": (st.injection_classifier_model
                                                    if self._injection_classifier(mode) is not None else "off")},
            "benchmark": {"task_id": metadata.get("task_id"), "content_hash": metadata.get("task_content_hash")},
            "vexa_version": get_settings().app_version,
        }
        if architecture == "hierarchical" and not real:
            from backend.orchestration.hierarchical import mock_policy_table
            cfg["hierarchical_mock_policy"] = mock_policy_table(st.manager_mock_policy)
        return cfg

    def _injection_classifier(self, mode: ExecutionMode):
        """G6 model layer: only in real mode, and only when its provider key exists (never in mock/tests)."""
        choice = self._settings.injection_classifier
        if choice == "off" or mode != ExecutionMode.real:
            return None
        from backend.agents.config import _PROVIDER_KEY_ENV, infer_provider
        model = self._settings.injection_classifier_model
        env = _PROVIDER_KEY_ENV.get(infer_provider(model, None), "")
        if choice == "auto" and not os.environ.get(env):
            return None
        from backend.guardrails import InjectionClassifier
        return InjectionClassifier(model=model)

    @staticmethod
    def _actual_changes(ctx: RunContext) -> list[str]:
        """Paths that really differ from the workspace at run start (from snapshots, not agent claims)."""
        snap = getattr(ctx, "workspace_snapshot", None)
        if not snap:
            return []
        repo_dir, before = snap
        try:
            return [d.path for d in diff_snapshots(before, snapshot(repo_dir))]
        except Exception:
            return []

    def verify(self, ctx: RunContext, kit: WorkspaceToolKit, req: RequirementAnalysis,
               files_changed: list[str], test: AgentTestResult | None) -> VerificationResult:
        files_changed = sorted(set(files_changed) | set(self._actual_changes(ctx)))
        r = self._run_verifier(ctx, kit, req, files_changed, test)
        self._check_acceptance(ctx, req, r)
        self._publish(ctx, "verification", r, "Verifier", ("requirement_analysis", "test_result"))
        return r

    # ------------------------------------------------------------------
    # Individual agent runners
    # ------------------------------------------------------------------

    def _run_requirement_analyst(self, ctx: RunContext, requirement: str) -> RequirementAnalysis:
        ctx.agent_started("RequirementAnalyst")
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=RequirementAnalyst", ctx.run_id)
        try:
            agent = self._make_agent(
                agent_id="RequirementAnalyst",
                role=self._p.REQUIREMENT_ANALYST_ROLE,
                goal=self._p.REQUIREMENT_ANALYST_GOAL,
                backstory=self._p.REQUIREMENT_ANALYST_BACKSTORY,
                tools=[],  # No tools — pure LLM reasoning
            )
            task = self._make_task(
                description=self._p.REQUIREMENT_ANALYST_TASK.format(requirement=requirement),
                agent=agent,
                expected_output="JSON object with task_summary, functional_requirements, constraints, acceptance_criteria, ambiguities, affected_areas",
                schema=RequirementAnalysisOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            result = parse_requirement_analysis(raw, requirement, duration_ms)
            ctx.agent_completed("RequirementAnalyst", duration_ms)
            logger.info("agent_completed | run=%s agent=RequirementAnalyst duration_ms=%.1f", ctx.run_id, duration_ms)
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("RequirementAnalyst", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=RequirementAnalyst error=%s", ctx.run_id, e)
            return RequirementAnalysis(
                status=AgentStatus.failed,
                summary=f"Agent error: {e}",
                duration_ms=duration_ms,
                original_requirement=requirement,
                errors=[str(e)],
            )

    def _run_project_analyst(self, ctx: RunContext, kit: WorkspaceToolKit, req: RequirementAnalysis) -> ProjectAnalysis:
        ctx.agent_started("ProjectAnalyst")
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=ProjectAnalyst", ctx.run_id)
        
        # Pre-fetch the file tree to save the agent a tool call
        tree = self._svc.list_files(ctx.workspace_id, ".", True)
        if tree.success:
            paths = [f["path"] for f in tree.data if not f.get("is_dir")]
            file_tree_str = "\n".join(f"- {p}" for p in paths) if paths else "Workspace is empty."
        else:
            file_tree_str = f"Could not retrieve file tree: {tree.message}"

        try:
            tools = self._make_crewai_tools(kit, kit.for_project_analyst())
            agent = self._make_agent(
                agent_id="ProjectAnalyst",
                role=self._p.PROJECT_ANALYST_ROLE,
                goal=self._p.PROJECT_ANALYST_GOAL,
                backstory=self._p.PROJECT_ANALYST_BACKSTORY,
                tools=tools,
            )
            task = self._make_task(
                description=self._p.PROJECT_ANALYST_TASK.format(
                    requirement_analysis=req.model_dump_json(indent=2),
                    file_tree=file_tree_str
                ),
                agent=agent,
                expected_output="JSON object with project analysis",
                schema=ProjectAnalysisOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            result = parse_project_analysis(raw, ctx.workspace_id, duration_ms)
            ctx.agent_completed("ProjectAnalyst", duration_ms)
            logger.info("agent_completed | run=%s agent=ProjectAnalyst files=%d", ctx.run_id, result.total_files)
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("ProjectAnalyst", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=ProjectAnalyst error=%s", ctx.run_id, e)
            return ProjectAnalysis(
                status=AgentStatus.failed,
                summary=f"Agent error: {e}",
                duration_ms=duration_ms,
                workspace_id=ctx.workspace_id,
                errors=[str(e)],
            )

    def _run_planner(self, ctx: RunContext, kit: WorkspaceToolKit, req: RequirementAnalysis, proj: ProjectAnalysis) -> ImplementationPlan:
        ctx.agent_started("Planner")
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=Planner", ctx.run_id)
        try:
            tools = self._make_crewai_tools(kit, kit.for_planner())
            agent = self._make_agent(
                agent_id="Planner",
                role=self._p.PLANNER_ROLE,
                goal=self._p.PLANNER_GOAL,
                backstory=self._p.PLANNER_BACKSTORY,
                tools=tools,
            )
            task = self._make_task(
                description=self._p.PLANNER_TASK.format(
                    requirement_analysis=req.model_dump_json(indent=2),
                    project_analysis=proj.model_dump_json(indent=2),
                ),
                agent=agent,
                expected_output="JSON implementation plan",
                schema=ImplementationPlanOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            result = parse_implementation_plan(raw, duration_ms)
            ctx.agent_completed("Planner", duration_ms)
            logger.info("agent_completed | run=%s agent=Planner steps=%d", ctx.run_id, len(result.steps))
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("Planner", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=Planner error=%s", ctx.run_id, e)
            return ImplementationPlan(
                status=AgentStatus.failed,
                summary=f"Agent error: {e}",
                duration_ms=duration_ms,
                errors=[str(e)],
            )

    def _run_coder(
        self, ctx: RunContext, kit: WorkspaceToolKit, plan: ImplementationPlan, proj: ProjectAnalysis,
        req: RequirementAnalysis | None = None,
    ) -> CodingResult:
        ctx.agent_started("Coder")
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=Coder", ctx.run_id)
        try:
            tools = self._make_crewai_tools(kit, kit.for_coder())
            agent = self._make_agent(
                agent_id="Coder",
                role=self._p.CODER_ROLE,
                goal=self._p.CODER_GOAL,
                backstory=self._p.CODER_BACKSTORY,
                tools=tools,
            )
            task = self._make_task(
                description=self._p.CODER_TASK.format(
                    implementation_plan=plan.model_dump_json(indent=2),
                    project_analysis=proj.model_dump_json(indent=2),
                    acceptance_criteria=_bullets(req.acceptance_criteria if req else []),
                ),
                agent=agent,
                expected_output="JSON coding result with files_changed",
                schema=CodingOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            result = parse_coding_result(raw, duration_ms)
            ctx.agent_completed("Coder", duration_ms)
            logger.info("agent_completed | run=%s agent=Coder files_changed=%d", ctx.run_id, len(result.files_changed))
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("Coder", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=Coder error=%s", ctx.run_id, e)
            return CodingResult(
                status=AgentStatus.failed,
                summary=f"Agent error: {e}",
                duration_ms=duration_ms,
                errors=[str(e)],
            )

    @staticmethod
    def _run_tests_over_mcp(bridge: Any) -> SimpleNamespace:
        """run_tests through the workspace MCP server (same sandbox, same pytest arguments)."""
        ok, text = bridge.call("run_tests", {"test_path": ".", "detailed_report": True})
        try:
            body = json.loads(text)
        except ValueError:
            body = {"ok": False, "error": text[:300]}
        exit_code = body.get("exit_code") if ok else None
        message = (f"exit_code={exit_code}" if exit_code is not None
                   else f"MCP run_tests failed: {body.get('error', text[:300])}")
        return SimpleNamespace(exit_code=exit_code, timed_out=bool(body.get("timed_out")),
                               stdout=body.get("stdout") or "", stderr=body.get("stderr") or "",
                               message=message, error=None if exit_code is not None else message)

    def _run_tester(self, ctx: RunContext, kit: WorkspaceToolKit, workspace_id: str) -> AgentTestResult:
        """
        Run the test suite in the sandbox and build a ground-truth result.

        The verdict comes from the pytest exit code. The Tester agent is only
        consulted when tests fail, to turn raw output into a failure list the
        Debugger can act on.
        """
        ctx.agent_started("Tester")
        ctx.test_attempted()
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=Tester attempt=%d", ctx.run_id, ctx.test_attempts)

        workspace_mcp = kit.mcp.get("vexa-workspace")
        transport = "mcp" if workspace_mcp else "direct"
        denial = enforce_tool_call(ctx, "run_tests", {"test_path": "."})  # G2 applies to the orchestrator too
        span = ctx.observer.tool_started("Tester", "run_tests", {"test_path": "."}, origin="orchestrator") \
            if ctx.observer else None
        if denial:
            exec_result = SimpleNamespace(exit_code=None, timed_out=False, stdout="", stderr="",
                                          message=denial, error=denial)
        elif workspace_mcp:
            exec_result = self._run_tests_over_mcp(workspace_mcp)
        else:
            exec_result = self._svc.run_tests(workspace_id, test_path=".", extra_args=["-q", "--tb=short", "-rA"])
        ctx.tool_invoked("Tester", "run_tests", f"exit_code={exec_result.exit_code} timed_out={exec_result.timed_out}")
        if span:
            ctx.observer.tool_finished(
                span, exec_result.exit_code is not None and not exec_result.timed_out,
                exec_result.message, exit_code=exec_result.exit_code, timed_out=exec_result.timed_out,
                sandbox=self._svc.sandbox_backend, transport=transport,
            )
        summary = summarise_pytest_output(exec_result.stdout)
        no_tests = exec_result.exit_code == 5
        passed = exec_result.exit_code == 0 and not exec_result.timed_out
        failures = summary["failures"]
        errors: list[str] = []
        if exec_result.exit_code is None:
            errors.append(exec_result.error or exec_result.message)

        if not passed and not no_tests:
            try:
                agent = self._make_agent(
                    agent_id="Tester",
                    role=self._p.TESTER_ROLE,
                    goal=self._p.TESTER_GOAL,
                    backstory=self._p.TESTER_BACKSTORY,
                    tools=[],
                )
                task = self._make_task(
                    description=self._p.TESTER_TASK.format(
                        exit_code=exec_result.exit_code,
                        test_output=(exec_result.stdout[-6000:] + "\n" + exec_result.stderr[-2000:]).strip(),
                    ),
                    agent=agent,
                    expected_output="JSON object with failures",
                    schema=TesterOutput,
                )
                raw = self._run_single_agent_crew(ctx, agent, task)
                analysed = _list(_parse_json_output(raw), "failures")
                if analysed:
                    failures = [str(f) for f in analysed]
            except Exception as e:
                errors.append(f"Failure analysis unavailable: {e}")
                ctx.record("Tester", "analysis_failed", str(e))

        duration_ms = (time.perf_counter() - t) * 1000
        if no_tests:
            status, label = AgentStatus.partial, "No tests collected"
        elif passed:
            status, label = AgentStatus.success, "Tests passed"
        else:
            status, label = AgentStatus.failed, "Tests failed"
        result = AgentTestResult(
            status=status,
            summary=f"{label} (exit_code={exec_result.exit_code})",
            duration_ms=duration_ms,
            passed=passed,
            no_tests=no_tests,
            exit_code=exec_result.exit_code,
            tests_found=summary["tests_found"],
            tests_passed=summary["tests_passed"],
            tests_failed=summary["tests_failed"],
            failures=failures,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            timed_out=exec_result.timed_out,
            errors=errors,
        )
        if ctx.observer:
            ctx.observer.annotate_agent("Tester", attempt=ctx.test_attempts, tests_found=result.tests_found,
                                        tests_passed=result.tests_passed, tests_failed=result.tests_failed,
                                        verdict="no_tests" if no_tests else ("passed" if passed else "failed"))
        ctx.agent_completed("Tester", duration_ms)
        logger.info(
            "agent_completed | run=%s agent=Tester passed=%s exit_code=%s",
            ctx.run_id, result.passed, result.exit_code,
        )
        return result

    def _run_debugger(
        self,
        ctx: RunContext,
        kit: WorkspaceToolKit,
        coding: CodingResult,
        current_test: AgentTestResult,
        iteration: int,
        max_iterations: int,
        req: RequirementAnalysis | None = None,
        plan: ImplementationPlan | None = None,
    ) -> tuple[DebugIteration, bool]:
        """
        One Debugger iteration. Returns (record, fix_attempted).

        The caller (the architecture) decides whether and when to re-test;
        ``test_result_after`` is filled in by the caller.
        """
        ctx.debug_iterated()
        ctx.agent_started("Debugger")
        if ctx.observer:
            ctx.observer.annotate_agent("Debugger", debug_iteration=iteration, max_iterations=max_iterations)
        t = time.perf_counter()
        logger.info("agent_started | run=%s agent=Debugger iteration=%d", ctx.run_id, iteration)
        try:
            tools = self._make_crewai_tools(kit, kit.for_debugger())
            agent = self._make_agent(
                agent_id="Debugger",
                role=self._p.DEBUGGER_ROLE,
                goal=self._p.DEBUGGER_GOAL,
                backstory=self._p.DEBUGGER_BACKSTORY,
                tools=tools,
            )
            failure_summary = "\n".join(current_test.failures) if current_test.failures else current_test.stdout[-2000:]
            task = self._make_task(
                description=self._p.DEBUGGER_TASK.format(
                    test_failure_output=failure_summary,
                    coding_result=coding.model_dump_json(indent=2),
                    acceptance_criteria=_bullets(req.acceptance_criteria if req else []),
                    plan_objective=(plan.objective if plan else "") or "(not available)",
                    iteration=iteration,
                    max_iterations=max_iterations,
                ),
                agent=agent,
                expected_output="JSON debug result with root_cause, fix_applied, files_changed",
                schema=DebugOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            root_cause, fix_applied, files_changed = parse_debug_result(raw, iteration, duration_ms)
            ctx.agent_completed("Debugger", duration_ms)
            logger.info("agent_completed | run=%s agent=Debugger iteration=%d root_cause=%s",
                        ctx.run_id, iteration, root_cause[:100])
            return DebugIteration(
                iteration=iteration, root_cause=root_cause, fix_applied=fix_applied, files_changed=files_changed,
            ), True
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("Debugger", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=Debugger iteration=%d error=%s", ctx.run_id, iteration, e)
            return DebugIteration(
                iteration=iteration, root_cause=f"Debug agent error: {e}", fix_applied="None — agent crashed",
            ), False

    def _run_verifier(
        self,
        ctx: RunContext,
        kit: WorkspaceToolKit,
        req: RequirementAnalysis,
        files_changed: list[str],
        final_test: AgentTestResult | None,
    ) -> VerificationResult:
        if self._settings.verifier_backend == "adk_a2a":
            return self._run_remote_verifier(ctx, req, files_changed, final_test)
        ctx.agent_started("Verifier")
        t = time.perf_counter()
        logger.info("verification_started | run=%s", ctx.run_id)
        try:
            tools = self._make_crewai_tools(kit, kit.for_verifier())
            agent = self._make_agent(
                agent_id="Verifier",
                role=self._p.VERIFIER_ROLE,
                goal=self._p.VERIFIER_GOAL,
                backstory=self._p.VERIFIER_BACKSTORY,
                tools=tools,
            )
            task = self._make_task(
                description=self._p.VERIFIER_TASK.format(
                    original_requirement=req.original_requirement,
                    acceptance_criteria="\n".join(f"- {c}" for c in req.acceptance_criteria),
                    files_changed=", ".join(files_changed) if files_changed else "none",
                    test_result=final_test.model_dump_json(indent=2) if final_test else "{}",
                ),
                agent=agent,
                expected_output="JSON verification result",
                schema=VerifierOutput,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            duration_ms = (time.perf_counter() - t) * 1000
            result = apply_verification_ground_truth(parse_verification_result(raw, duration_ms), final_test)
            ctx.agent_completed("Verifier", duration_ms)
            logger.info(
                "run_verified | run=%s verified=%s", ctx.run_id, result.verified
            )
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            ctx.agent_failed("Verifier", str(e), duration_ms)
            logger.error("agent_failed | run=%s agent=Verifier error=%s", ctx.run_id, e)
            return VerificationResult(
                status=AgentStatus.failed,
                summary=f"Agent error: {e}",
                duration_ms=duration_ms,
                verified=False,
                errors=[str(e)],
            )

    @contextmanager
    def briefed(self, brief: str | None):
        """Attach a manager brief to the tasks created inside this block (hierarchical only)."""
        self._brief = brief or None
        try:
            yield
        finally:
            self._brief = None

    def manager_decide(self, ctx: RunContext, state_summary: dict[str, Any], feedback: str = "") -> ManagerDecision | None:
        """
        Hierarchical architecture: ask the Manager agent who works next.

        Returns None in mock mode (the architecture then applies its documented
        rule-based policy). In real mode the decision is a schema-validated
        CrewAI answer; errors propagate to the architecture.
        """
        if self._mode == ExecutionMode.mock:
            return None
        ctx.agent_started("Manager")
        t = time.perf_counter()
        try:
            agent = self._make_agent(agent_id="Manager", role=self._p.MANAGER_ROLE, goal=self._p.MANAGER_GOAL,
                                     backstory=self._p.MANAGER_BACKSTORY, tools=[])
            task = self._make_task(
                description=self._p.MANAGER_TASK.format(state_summary=json.dumps(state_summary, indent=2),
                                                feedback=feedback or ""),
                agent=agent, expected_output="JSON object with next_agent and reason", schema=ManagerDecision,
            )
            raw = self._run_single_agent_crew(ctx, agent, task)
            decision, errors = validate_output(raw, ManagerDecision)
            if decision is None:
                raise RuntimeError("Invalid manager decision: " + "; ".join(errors))
            ctx.agent_completed("Manager", (time.perf_counter() - t) * 1000)
            return decision
        except Exception as e:
            ctx.agent_failed("Manager", str(e), (time.perf_counter() - t) * 1000)
            raise

    def _run_remote_verifier(
        self,
        ctx: RunContext,
        req: RequirementAnalysis,
        files_changed: list[str],
        final_test: AgentTestResult | None,
    ) -> VerificationResult:
        """
        Delegate verification to the Google ADK Verifier over A2A.

        The CrewAI runtime is the A2A client; the ADK agent is a separate
        service. Its answer is validated against the same VerifierOutput schema
        and the sandbox ground truth is applied exactly as for the CrewAI Verifier.
        """
        from backend.a2a_bridge.client import A2AAgentClient

        if self._settings.a2a_embedded:
            from backend.a2a_bridge.embedded import ensure_embedded_verifier, register_credentials
            embedded = ensure_embedded_verifier(self._settings.a2a_embedded_port)
            url, token = embedded.url, embedded.token
            if self._mode == ExecutionMode.real and self._credential_handle is None:
                self._credential_handle = register_credentials(
                    self._settings.adk_model or self._settings.llm_model,
                    self._settings.adk_api_key or self._settings.llm_api_key)
        else:
            url, token = self._settings.a2a_verifier_url, self._settings.a2a_token
        ctx.agent_started("Verifier")
        t = time.perf_counter()
        payload = {
            "workspace_id": ctx.workspace_id,
            "run_id": ctx.run_id,
            "original_requirement": req.original_requirement,
            "acceptance_criteria": req.acceptance_criteria,
            "files_changed": files_changed,
            "test_result": final_test.model_dump(mode="json", exclude={"stdout", "stderr"}) if final_test else {},
            "prompt_variant": self._p.name,
            "execution_mode": self._mode.value,
            "credential_handle": self._credential_handle,
            "trace_id": ctx.observer.trace_id if ctx.observer else None,
        }
        ctx.coordinate("message", "crewai:runtime", "adk:vexa_verifier", "A2A message/send (verification request)",
                       protocol="a2a", url=url)
        span = ctx.observer.tool_started("Verifier", "a2a:message/send", {"url": url}, origin="orchestrator") \
            if ctx.observer else None
        try:
            register_secret(token)
            headers = {"traceparent": ctx.observer.traceparent(span)} if (ctx.observer and span) else {}
            exchange = A2AAgentClient(url, token, self._settings.a2a_timeout_seconds,
                                      extra_headers=headers).send_json(payload)
        except Exception as e:
            duration_ms = (time.perf_counter() - t) * 1000
            if span:
                ctx.observer.tool_finished(span, False, str(e), transport="a2a")
            ctx.coordinate("message", "adk:vexa_verifier", "crewai:runtime", f"A2A failure: {e}", protocol="a2a")
            ctx.agent_failed("Verifier", f"A2A verifier unavailable: {e}", duration_ms)
            return VerificationResult(status=AgentStatus.failed, summary=f"Remote verifier error: {e}",
                                      duration_ms=duration_ms, verified=False, errors=[str(e)], backend="adk_a2a")
        duration_ms = (time.perf_counter() - t) * 1000
        meta = {"url": url, "task_id": exchange.task_id, "context_id": exchange.context_id,
                "state": exchange.state, "states_seen": exchange.states_seen, "agent": exchange.agent_name,
                "skills": exchange.agent_skills, "protocol_version": exchange.protocol_version}
        from backend.adk_agents.verifier import split_telemetry
        verdict_text, telemetry = split_telemetry(exchange.text)
        meta["telemetry_reported"] = telemetry is not None
        if telemetry is not None:
            self._merge_remote_telemetry(ctx, span, telemetry)
        if span:
            ctx.observer.tool_finished(span, True, exchange.state, transport="a2a", task_id=exchange.task_id,
                                       remote_agent=exchange.agent_name)
        ctx.coordinate("message", "adk:vexa_verifier", "crewai:runtime", f"A2A task {exchange.state}",
                       protocol="a2a", task_id=exchange.task_id, context_id=exchange.context_id)
        result = apply_verification_ground_truth(parse_verification_result(verdict_text, duration_ms), final_test)
        result.backend, result.remote = "adk_a2a", meta
        ctx.agent_completed("Verifier", duration_ms)
        return result

    @staticmethod
    def _merge_remote_telemetry(ctx: RunContext, span: str | None, telemetry: dict[str, Any]) -> None:
        """Guard decisions and calls made inside the ADK verifier become part of this run."""
        for ev in telemetry.get("guardrail_events", []):
            ev = dict(ev)
            kind, decision = ev.pop("kind", "tool_authorization"), ev.pop("decision", "indeterminate")
            reason, action = ev.pop("reason", ""), ev.pop("action", None)
            ev.pop("agent", None)
            if decision not in ("allowed", "blocked", "sanitized", "flagged", "indeterminate"):
                decision = "indeterminate"
            ctx.guard(kind, "Verifier", decision, reason, action=action, enforced_by="adk:vexa_verifier", **ev)
        if ctx.observer:
            ctx.observer.record_remote("Verifier", span, telemetry, origin="adk:vexa_verifier")

    # ------------------------------------------------------------------
    # CrewAI tool wrapping
    # ------------------------------------------------------------------

    @staticmethod
    def _run_scripted_tools(ctx: RunContext, agent: Any) -> None:
        tools = {getattr(t, "name", ""): t for t in getattr(agent, "tools", []) or []}
        ctx.tool_origin = "scripted"
        try:
            for name, args in MOCK_TOOL_SCRIPT.get(getattr(agent, "agent_id", ""), []):
                if name in tools:
                    tools[name]._run(**args)
        finally:
            ctx.tool_origin = "agent"

    def _make_crewai_tools(self, kit: WorkspaceToolKit, adapters: list) -> list:
        """
        CrewAI tools for one agent: the role's allowlisted workspace tools, either
        as MCP tools (transport=mcp) or direct adapters, plus search_docs over MCP
        for roles listed in docs_search_roles when that server is running.
        """
        if BaseTool is object:
            return []
        allowed = {a.name for a in adapters}
        agent_id = getattr(kit.ctx, "current_agent", "")
        workspace = kit.mcp.get("vexa-workspace")
        tools = workspace.crewai_tools(allowed, kit.ctx) if workspace else [_AdaptedTool(a) for a in adapters]
        docs = kit.mcp.get("vexa-docs-search")
        roles = {r.strip() for r in self._settings.docs_search_roles.split(",") if r.strip()}
        if docs and agent_id in roles:
            tools += docs.crewai_tools(None, kit.ctx)
        intel = kit.mcp.get("vexa-code-intel")
        if intel:
            from backend.guardrails import TOOL_POLICY
            tools += intel.crewai_tools(set(TOOL_POLICY.get(agent_id, ())), kit.ctx)
        return tools

    def _start_mcp_servers(self, ctx: RunContext, kit: WorkspaceToolKit, result: RunResult) -> None:
        from backend.mcp_client.bridge import (
            MCPServerBridge,
            code_intel_server_spec,
            docs_search_server_spec,
            workspace_server_spec,
        )

        ctx.mcp_servers = result.mcp_servers  # shared list: the live run view shows servers as they start
        ctx.tool_transport = self._settings.tool_transport
        if self._settings.tool_transport == "mcp":
            bridge = MCPServerBridge(workspace_server_spec(self._svc._manager.root, ctx.workspace_id)).start()
            kit.mcp["vexa-workspace"] = bridge
            result.mcp_servers.append({"name": "vexa-workspace", "status": "connected",
                                       "tools": [t.name for t in bridge.tools]})
            ctx.coordinate("message", "crewai:runtime", "mcp:vexa-workspace",
                           f"MCP initialize + tools/list → {len(bridge.tools)} tools", protocol="mcp")
            try:  # second MCP server: local, keyless; a failure is recorded, never faked
                intel = MCPServerBridge(code_intel_server_spec(self._svc._manager.root, ctx.workspace_id)).start()
            except Exception as exc:
                result.mcp_servers.append({"name": "vexa-code-intel", "status": f"failed: {exc}", "tools": []})
                ctx.record("runtime", "mcp_server_failed", f"vexa-code-intel: {exc}")
            else:
                kit.mcp["vexa-code-intel"] = intel
                result.mcp_servers.append({"name": "vexa-code-intel", "status": "connected",
                                           "tools": [t.name for t in intel.tools]})
                ctx.coordinate("message", "crewai:runtime", "mcp:vexa-code-intel",
                               f"MCP initialize + tools/list → {len(intel.tools)} tools", protocol="mcp")
        else:
            result.mcp_servers.append({"name": "vexa-code-intel", "status": "not used: tool_transport=direct",
                                       "tools": []})
        if self._mode == ExecutionMode.mock:
            result.mcp_servers.append({"name": "vexa-docs-search", "status": "not used in mock mode", "tools": []})
            return
        key = self._settings.docs_search_api_key
        if not key:
            result.mcp_servers.append({"name": "vexa-docs-search", "status": "disabled: TAVILY_API_KEY not set",
                                       "tools": []})
            return
        register_secret(key)
        try:
            docs = MCPServerBridge(docs_search_server_spec(key)).start()
        except Exception as exc:  # optional external tool: record, do not fake
            result.mcp_servers.append({"name": "vexa-docs-search", "status": f"failed: {exc}", "tools": []})
            ctx.record("runtime", "mcp_server_failed", f"vexa-docs-search: {exc}")
            return
        kit.mcp["vexa-docs-search"] = docs
        result.mcp_servers.append({"name": "vexa-docs-search", "status": "connected",
                                   "tools": [t.name for t in docs.tools]})


import inspect

def _generate_args_schema(func: Any, tool_name: str) -> type[BaseModel]:
    sig = inspect.signature(func)
    fields = {}
    for name, param in sig.parameters.items():
        if name in ("self", "args", "kwargs"):
            continue
        annotation = param.annotation if param.annotation != inspect.Parameter.empty else str
        default = param.default if param.default != inspect.Parameter.empty else ...
        fields[name] = (annotation, default)
    
    # If a tool has no parameters, Pydantic creates an empty schema.
    # Groq needs at least some properties or no 'required' block.
    # We add a dummy property to avoid empty schema issues on strict LLMs if needed,
    # but normally create_model handles it correctly when properly typed.
    if not fields:
        fields["dummy"] = (str, "ignored")
        
    return create_model(f"{tool_name}_schema", **fields)

class _AdaptedTool(BaseTool):
    """
    Wraps a VEXA tool adapter as a callable that CrewAI can use.
    """
    name: str = ""
    description: str = ""
    _adapter: Any = PrivateAttr()

    def __init__(self, adapter: Any, **data: Any) -> None:
        schema = _generate_args_schema(adapter.run, adapter.name)
        super().__init__(
            name=adapter.name, 
            description=adapter.description, 
            args_schema=schema, 
            **data
        )
        self._adapter = adapter

    def _invoke(self, *args: Any, **kwargs: Any) -> str:
        kwargs.pop("dummy", None)
        ctx = getattr(self._adapter, "ctx", None)
        denial = enforce_tool_call(ctx, self._adapter.name, kwargs)
        if denial:
            return json.dumps({"ok": False, "operation": self._adapter.name, "error": denial})
        observer = getattr(ctx, "observer", None)
        span = observer.tool_started(ctx.current_agent, self._adapter.name, kwargs,
                                     origin=getattr(ctx, "tool_origin", "agent")) if observer else None
        try:
            out = self._adapter.run(*args, **kwargs)
        except Exception as exc:
            if span:
                observer.tool_finished(span, False, f"{type(exc).__name__}: {exc}")
            raise
        if span:
            parsed = extract_json_object(out) or {}
            ok = bool(parsed.get("ok", True))
            observer.tool_finished(span, ok, parsed.get("error") or parsed.get("message") or "")
        return enforce_tool_output(ctx, self._adapter.name, out)

    def run(self, *args: Any, **kwargs: Any) -> str:
        return self._invoke(*args, **kwargs)

    def _run(self, *args: Any, **kwargs: Any) -> str:
        return self._invoke(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        return self._invoke(*args, **kwargs)
