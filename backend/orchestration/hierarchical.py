"""
Hierarchical architecture — manager-led decomposition, delegation, review and revision.

    ┌──────────── Manager ◄──────────────── results ─────────────┐
    │  choose a strategy · split the plan into work packages     │
    │  review every result (accept / revise) · decide when done  │
    └──delegate(brief, package)──► RequirementAnalyst | ProjectAnalyst | Planner
                                   | Coder | Tester | Debugger | Verifier ────┘

What makes this different from Sequential (observable in the coordination log):
- the Manager chooses the *route*. Only safety dependencies are enforced
  (see ``precondition_error``), not the sequential order:
    * repair route — reproduce first: Tester runs on the unchanged code; a
      reproduced failure goes straight to the Debugger (no Planner/Coder);
    * build route  — ProjectAnalyst is optional (skipped when the requirement
      already names the files), then Planner;
- the plan is decomposed into *work packages*; each package is delegated to the
  Coder separately with its own brief, reviewed, and (when more packages follow)
  checked by an intermediate Tester run before the next package starts;
- every result is *reviewed*; deficient work (invalid output, a package with no
  file changes, an empty plan, a failed verification) is sent back for revision;
- after a failed verification the Manager can order rework by the Coder;
- the Manager, not a fixed order, decides when to stop (only after verification).

Specialists, tools, schemas, the sandbox verdict and the debug budget are the
same as in every other architecture. Revisions use a separate, bounded budget.

Real mode: the Manager is a CrewAI agent returning a schema-validated
ManagerDecision (next agent, brief, optional work package). Mock mode:
``rule_based_decision`` applies the same strategy deterministically (no LLM);
its repair-task detection is a documented keyword heuristic, used only there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.agents.contracts import (
    AgentStatus,
    AgentTestResult,
    CodingResult,
    DebugIteration,
    FileChange,
    ImplementationPlan,
    ProjectAnalysis,
    RequirementAnalysis,
    VerificationResult,
)
from backend.orchestration.base import Architecture, RunHandle

MANAGER = "Manager"
MAX_CONSECUTIVE_REJECTIONS = 3
DEFAULT_REVISION_BUDGET = 2
DEFAULT_PACKAGE_SIZE = 2  # plan steps per Coder work package
CODE_ACTIONS = {"write", "patch", "delete", "create", "modify", "edit"}

_FILE_REF = re.compile(r"\b[\w./-]+\.(py|js|ts|tsx|jsx|go|rs|java|rb|md|toml|json|ya?ml)\b")

# ---------------------------------------------------------------------------
# Mock-mode manager policy: an explicit table, keyed by the task's structured
# category (benchmark task.json "category", or the run request's task_category).
# Deterministic and reproducible; it never imitates an LLM. Override per server
# with VEXA_MANAGER_MOCK_POLICY='{"refactoring": "plan_first"}'.
# ---------------------------------------------------------------------------

TASK_CATEGORIES = ("feature", "bug_fix", "refactoring", "testing", "performance", "security", "configuration",
                   "error_handling", "api", "database", "unspecified")
STRATEGIES = ("reproduce_first", "baseline_then_plan", "plan_first")
DEFAULT_MOCK_POLICY: dict[str, str] = {
    "bug_fix": "reproduce_first", "error_handling": "reproduce_first",
    "refactoring": "baseline_then_plan", "testing": "baseline_then_plan",
    "feature": "plan_first", "performance": "plan_first", "security": "plan_first", "configuration": "plan_first",
    "api": "plan_first", "database": "plan_first", "unspecified": "plan_first",
}
_PRECEDENCE = {"reproduce_first": 0, "baseline_then_plan": 1, "plan_first": 2}


def parse_categories(value: Any) -> list[str]:
    """'bug_fix,feature' / ['bug_fix'] / None → known categories (unknown → 'unspecified')."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").replace("+", ",").split(",")
    cats = [c.strip().lower() for c in items if str(c).strip()]
    return [c if c in TASK_CATEGORIES else "unspecified" for c in cats] or ["unspecified"]


def mock_policy_table(override: str | dict | None = None) -> dict[str, str]:
    import json
    table = dict(DEFAULT_MOCK_POLICY)
    if override:
        extra = json.loads(override) if isinstance(override, str) else dict(override)
        bad = {k: v for k, v in extra.items() if k not in TASK_CATEGORIES or v not in STRATEGIES}
        if bad:
            raise ValueError(f"invalid manager mock policy entries: {bad}")
        table.update(extra)
    return table


def choose_strategy(categories: list[str], requirement: str, table: dict[str, str]) -> dict[str, Any]:
    """The mock Manager's route decision and the input features it used (recorded in the trace)."""
    per = {c: table[c] for c in categories}
    strategy = min(per.values(), key=_PRECEDENCE.__getitem__)
    return {"source": "mock_policy", "strategy": strategy, "categories": categories, "per_category": per,
            "mixed": len(set(per.values())) > 1, "names_files": names_files(requirement)}


def names_files(text: str) -> bool:
    """Structured feature: does the requirement already name the files to touch?"""
    return bool(_FILE_REF.search(text or ""))


def make_packages(plan: ImplementationPlan | None, size: int = DEFAULT_PACKAGE_SIZE) -> list[list[int]]:
    """Group the plan's code-changing steps into work packages (step numbers)."""
    if plan is None or not plan.steps:
        return []
    code = [s.step_number for s in plan.steps if (s.action or "").lower() in CODE_ACTIONS]
    if not code:  # nothing explicitly code-changing: one package with the whole plan
        return [[s.step_number for s in plan.steps]]
    return [code[i:i + max(1, size)] for i in range(0, len(code), max(1, size))]


def package_plan(plan: ImplementationPlan, package: list[int], index: int, total: int) -> ImplementationPlan:
    """The slice of the plan the Coder receives for one work package."""
    steps = [s for s in plan.steps if s.step_number in package]
    files = sorted({f for s in steps for f in s.files_affected})
    return plan.model_copy(update={
        "objective": f"{plan.objective} — work package {index}/{total}: steps {', '.join(map(str, package))}",
        "steps": steps,
        "files_to_modify": [f for f in plan.files_to_modify if f in files] or files,
        "files_to_create": [f for f in plan.files_to_create if f in files],
    })


@dataclass
class _Work:
    """What the Manager holds: specialist outputs plus change ordering."""

    req: RequirementAnalysis | None = None
    proj: ProjectAnalysis | None = None
    plan: ImplementationPlan | None = None
    coding: CodingResult | None = None
    test: AgentTestResult | None = None
    verification: VerificationResult | None = None
    pending_debug: DebugIteration | None = None
    verified_after_change: bool = False
    change_seq: int = 0  # increments on every code change / patch
    test_seq: int = -1   # change_seq the latest test ran against
    revisions_left: int = DEFAULT_REVISION_BUDGET
    last: tuple[str, Any] | None = None  # (agent, result) awaiting review
    history: list[str] = field(default_factory=list)
    route: str | None = None             # repair | build (chosen by the manager)
    project_skipped: bool = False
    packages: list[list[int]] = field(default_factory=list)
    packages_done: list[int] = field(default_factory=list)  # indices into packages
    last_package: int | None = None      # index of the package the Coder just worked on
    package_size: int = DEFAULT_PACKAGE_SIZE
    categories: list[str] = field(default_factory=lambda: ["unspecified"])
    policy_table: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MOCK_POLICY))
    policy: dict[str, Any] | None = None  # mock policy decision (None in real mode)

    @property
    def test_is_fresh(self) -> bool:
        return self.test is not None and self.test_seq == self.change_seq

    @property
    def next_package(self) -> int | None:
        return next((i for i in range(len(self.packages)) if i not in self.packages_done), None)

    def package_index(self, package: list[int] | None) -> int | None:
        if not package:
            return None
        try:
            return self.packages.index(sorted(package))
        except ValueError:
            return None

    @property
    def baseline(self) -> bool:
        """The latest test ran on the unchanged code (a reproduction / baseline)."""
        return self.test is not None and self.change_seq == 0


# ---------------------------------------------------------------------------
# Review of the latest result
# ---------------------------------------------------------------------------


def review_issues(agent: str, result: Any) -> list[str]:
    """Problems the manager finds in a specialist's result (empty = acceptable)."""
    issues: list[str] = []
    if result is None:
        return ["no result"]
    if getattr(result, "output_valid", True) is False:
        issues.append("output failed schema validation: " + "; ".join(result.validation_errors[:2]))
    if getattr(result, "status", None) == AgentStatus.failed and agent not in ("Tester", "Verifier"):
        issues.append("agent reported failure: " + "; ".join(getattr(result, "errors", [])[:2]))
    if agent == "Planner" and not getattr(result, "steps", None):
        issues.append("the plan has no steps")
    if agent == "Coder" and not getattr(result, "files_changed", None):
        issues.append("no file changes were reported for this work package")
    if agent == "Verifier" and not result.verified:
        failed = result.requirements_failed or ["requirements not confirmed"]
        issues.append("verification failed: " + "; ".join(failed[:3]))
    return issues


def summarise(w: _Work, h: RunHandle) -> dict[str, Any]:
    t = w.test
    last = None
    if w.last is not None:
        agent, res = w.last
        last = {"agent": agent, "status": getattr(getattr(res, "status", None), "value", None),
                "summary": str(getattr(res, "summary", ""))[:300], "issues": review_issues(agent, res)}
    return {
        "requirement_analysis": None if w.req is None else {
            "status": w.req.status.value, "acceptance_criteria": w.req.acceptance_criteria[:8]},
        "project_analysis": None if w.proj is None else w.proj.status.value,
        "implementation_plan": None if w.plan is None else {"status": w.plan.status.value, "steps": len(w.plan.steps)},
        "code_changes": None if w.coding is None else [f.path for f in w.coding.files_changed],
        "latest_test": None if t is None else {
            "passed": t.passed, "no_tests": t.no_tests, "failures": t.failures[:5],
            "newer_than_last_change": w.test_is_fresh,
        },
        "verification": None if w.verification is None else {
            "verified": w.verification.verified, "requirements_failed": w.verification.requirements_failed[:5],
            "on_latest_change": w.verified_after_change},
        "last_result": last,
        "route": w.route,
        "project_analysis_skipped": w.project_skipped,
        "plan_steps": None if w.plan is None else [
            {"step": s.step_number, "action": s.action, "files": s.files_affected[:4],
             "description": s.description[:120]} for s in w.plan.steps[:12]],
        "work_packages": None if not w.packages else {
            "packages": w.packages, "done": [w.packages[i] for i in w.packages_done],
            "next": None if w.next_package is None else w.packages[w.next_package]},
        "latest_test_is_baseline": w.baseline,
        "debug_budget_left": h.debug_budget_left,
        "revision_budget_left": w.revisions_left,
        "history": w.history[-12:],
    }


def precondition_error(choice: str, w: _Work, h: RunHandle, package: list[int] | None = None) -> str | None:
    """Why *choice* cannot run now (None = allowed).

    Only safety dependencies are enforced — an agent cannot work without the
    input it consumes, nothing is tested twice without a change, and the work
    cannot finish unverified. The order of the remaining work is the Manager's.
    """
    ok_req = w.req is not None and w.req.status != AgentStatus.failed
    t = w.test
    if choice == "RequirementAnalyst":
        return None if w.req is None else "requirements were already analysed"
    if not ok_req:
        return "needs a successful requirement analysis first"
    if choice == "ProjectAnalyst":
        return None if w.proj is None else "project already analysed"
    if choice == "Planner":
        if w.plan is not None and w.revisions_left <= 0:
            return "re-planning needs revision budget"
        return None
    if choice == "Coder":
        if w.plan is None:
            return "needs an implementation plan (a reproduced failure can go to the Debugger instead)"
        if package:
            known = {s.step_number for s in w.plan.steps}
            if not set(package) <= known:
                return f"work package {package} names steps that are not in the plan"
        target = w.package_index(package)
        rework = (target is not None and target in w.packages_done) or (target is None and w.coding is not None)
        if rework and w.revisions_left <= 0:
            return "revising code needs revision budget"
        return None
    if choice == "Tester":
        return None if not w.test_is_fresh else "the latest change is already tested"
    if choice == "Debugger":
        ok = (t is not None and w.test_is_fresh and not t.passed and not t.no_tests and h.debug_budget_left > 0)
        return None if ok else "needs a fresh failing test and debug budget"
    if choice == "Verifier":
        if not w.test_is_fresh:
            return "needs a test result newer than the last change"
        return None if not w.verified_after_change else "already verified"
    if choice == "FINISH":
        return None if w.verified_after_change else "the latest result has not been verified"
    return f"unknown specialist '{choice}'"


def rule_based_decision(w: _Work, h: RunHandle) -> tuple[str, str, str, str, list[int]]:
    """
    Deterministic manager used in mock mode. Returns (review, next_agent, brief, reason, package).

    Same strategy as the LLM manager's instructions: reproduce reported defects
    before changing code, skip project analysis when the requirement names the
    files, implement the plan package by package with intermediate tests,
    revise deficient work while revision budget remains, rework after a failed
    verification.
    """
    review = "none"
    if w.last is not None:
        agent, res = w.last
        issues = review_issues(agent, res)
        if agent == "Tester" and w.baseline:
            issues = []  # a failing baseline is the reproduction we asked for, not a deficiency
        # With no revision budget left the manager has to accept the result as it is.
        review = "revise" if issues and w.revisions_left > 0 else "accept"
        if issues and w.revisions_left > 0:
            if agent == "Planner":
                return review, "Planner", f"Revise the plan: {issues[0]}. Give ordered steps with files.", issues[0], []
            if agent == "Coder":
                pkg = w.packages[w.last_package] if w.last_package is not None else []
                return (review, "Coder", f"Revise work package {pkg}: {issues[0]}. Implement each step with tools.",
                        issues[0], pkg)
            if agent == "Verifier" and w.test is not None and w.test.passed and w.plan is not None:
                failed = "; ".join(w.verification.requirements_failed[:3]) if w.verification else ""
                return review, "Coder", f"Rework: the Verifier reported unmet criteria ({failed}). Fix them.", issues[0], []
    if w.req is None:
        return review, "RequirementAnalyst", "Extract testable acceptance criteria.", "start by analysing the requirement", []

    if w.route is None:
        w.policy = choose_strategy(w.categories, h.ctx.requirement, w.policy_table)
        strategy = w.policy["strategy"]
        if strategy == "reproduce_first":
            w.route = "repair"
            return (review, "Tester", "Run the suite on the unchanged code and report exactly which tests fail.",
                    f"policy {strategy} for {'+'.join(w.categories)}: reproduce the defect before changing code", [])
        w.route = "build"
        if strategy == "baseline_then_plan":
            return (review, "Tester", "Run the suite on the unchanged code to record the baseline.",
                    f"policy {strategy} for {'+'.join(w.categories)}: record a test baseline before changing code", [])
    t = w.test

    if w.route == "repair" and w.plan is None:
        if t is not None and w.test_is_fresh and not t.passed and not t.no_tests and h.debug_budget_left > 0:
            return (review, "Debugger", "Fix the root cause of: " + "; ".join(t.failures[:2]),
                    "failure reproduced; repair it directly", [])
        if not w.test_is_fresh:
            return review, "Tester", "Re-run the suite to confirm the repair.", "test the repair", []
        if w.baseline and (t.passed or t.no_tests):
            w.route = "build"  # could not reproduce: fall back to planning a change
        elif w.policy and w.policy.get("mixed") and (t.passed or t.no_tests):
            w.route = "build"  # mixed task: defect repaired, now plan the remaining change
        elif not w.verified_after_change:
            return review, "Verifier", "Check every acceptance criterion against the code.", "verify the repair", []
        else:
            return review, "FINISH", "", "repair verified", []

    if w.proj is None and not w.project_skipped:
        if (w.policy or {}).get("names_files"):
            w.project_skipped = True
        else:
            return review, "ProjectAnalyst", "Focus on files relevant to the acceptance criteria.", "understand the project", []
    if w.plan is None:
        return review, "Planner", "Plan the smallest change that meets every acceptance criterion.", "plan the change", []
    if not w.packages:
        w.packages = make_packages(w.plan, w.package_size)
    nxt = w.next_package
    if nxt is not None and (w.coding is None or w.test_is_fresh and (t.passed or t.no_tests or h.debug_budget_left == 0)):
        pkg = w.packages[nxt]
        return (review, "Coder", f"Implement work package {nxt + 1}/{len(w.packages)} (plan steps {pkg}) only.",
                f"delegate work package {nxt + 1} of {len(w.packages)}", pkg)
    if not w.test_is_fresh:
        what = "intermediate check after work package" if nxt is not None else "test the latest change"
        return review, "Tester", "Run the full suite and report each failure precisely.", what, []
    if not t.passed and not t.no_tests and h.debug_budget_left > 0 and not w.verified_after_change:
        return review, "Debugger", "Fix the root cause of: " + "; ".join(t.failures[:2]), "tests fail and budget remains", []
    if not w.verified_after_change:
        return review, "Verifier", "Check every acceptance criterion against the code.", "verify the tested result", []
    return review, "FINISH", "", "verified (or revision budget spent)", []


def _merge_coding(previous: CodingResult | None, new: CodingResult) -> CodingResult:
    """The run-level coding result: every package's changes (latest entry per path wins)."""
    if previous is None:
        return new
    by_path: dict[str, FileChange] = {f.path: f for f in previous.files_changed}
    by_path.update({f.path: f for f in new.files_changed})
    notes = "\n".join(n for n in (previous.implementation_notes, new.implementation_notes) if n)
    return new.model_copy(update={"files_changed": list(by_path.values()), "implementation_notes": notes})


_PROVIDER_FAILURE = ("AI Provider Error", "AI Execution Error", "invalid tool call")


def provider_failure_signature(agent: str, detail: str) -> tuple[str, str] | None:
    """Comparable form of a provider-side failure (numbers such as token counts removed)."""
    if not any(t in detail for t in _PROVIDER_FAILURE):
        return None
    return agent, re.sub(r"\d+(\.\d+)?", "#", detail)[:240]


class HierarchicalArchitecture(Architecture):
    name = "hierarchical"
    description = ("A Manager agent picks the route (reproduce-first or plan-first), splits the plan into "
                   "work packages, reviews each result and orders revisions.")

    def execute(self, h: RunHandle) -> None:
        rt, ctx = h.runtime, h.ctx
        w = _Work(revisions_left=getattr(rt._settings, "manager_revision_budget", DEFAULT_REVISION_BUDGET),
                  package_size=getattr(rt._settings, "manager_package_size", DEFAULT_PACKAGE_SIZE),
                  categories=parse_categories((h.result.metadata or {}).get("task_category")),
                  policy_table=mock_policy_table(getattr(rt._settings, "manager_mock_policy", None)))
        policy_logged = False
        feedback = ""
        rejections = 0
        last_failure: tuple[str, str] | None = None

        for cycle in range(1, h.max_cycles + 1):
            summary = summarise(w, h)
            decision = rt.manager_decide(ctx, summary, feedback)
            if decision is None:
                review, choice, brief, reason, package = rule_based_decision(w, h)
                source = "rule_policy"
                if w.policy and not policy_logged:
                    policy_logged = True
                    h.coordinate("decision", MANAGER, None, f"mock policy: {w.policy['strategy']}",
                                 cycle=cycle, source="mock_policy", accepted=True, policy=w.policy,
                                 category_source="run metadata" if (h.result.metadata or {}).get("task_category")
                                 else "not provided (unspecified)")
            else:
                review, choice, brief, reason = (decision.review_of_last_result, decision.next_agent,
                                                 decision.brief, decision.reason or decision.review_notes)
                package = sorted(set(decision.work_package)) if choice == "Coder" else []
                source = "manager_llm"

            if w.last is not None and review != "none":
                agent, _ = w.last
                issues = summary["last_result"]["issues"] if summary["last_result"] else []
                if review == "revise":
                    detail = f"revise: {reason}"
                else:
                    detail = "accepted" + (f" despite: {'; '.join(issues)} (revision budget spent)"
                                           if issues and w.revisions_left <= 0 else "")
                h.coordinate("review", MANAGER, agent, detail, verdict=review, issues=issues, source=source)

            error = precondition_error(choice, w, h, package)
            if error:
                rejections += 1
                feedback = f"Your previous choice '{choice}' was rejected: {error}. Choose again."
                h.coordinate("decision", MANAGER, choice, f"rejected: {error}", cycle=cycle, source=source,
                             accepted=False)
                if rejections >= MAX_CONSECUTIVE_REJECTIONS:
                    h.coordinate("stop", MANAGER, None, f"{rejections} consecutive invalid delegations")
                    h.result.errors.append(f"Manager made {rejections} consecutive invalid delegations")
                    break
                continue
            rejections, feedback = 0, ""
            if choice == "Coder" and not package and w.packages:
                package = w.packages[w.next_package] if w.next_package is not None else []
            if choice == "Coder" and package and w.package_index(package) is None:
                w.packages.append(package)  # the Manager defined its own work package
            target = w.package_index(package) if choice == "Coder" else None
            revision = (choice == "Planner" and w.plan is not None) or (choice == "Coder" and (
                (target is not None and target in w.packages_done) or (target is None and w.coding is not None)))
            h.coordinate("decision", MANAGER, choice, reason, cycle=cycle, source=source, accepted=True,
                         revision=revision, work_package=package or None, route=w.route, state=summary)
            w.history.append(choice + (f" {package}" if package else "") + (" (revision)" if revision else ""))
            if choice == "FINISH":
                h.coordinate("stop", MANAGER, None, "manager finished the work")
                break
            if revision:
                w.revisions_left -= 1
            if brief:
                h.coordinate("message", MANAGER, choice, f"brief: {brief[:200]}", protocol="delegation")
            h.coordinate("dispatch", MANAGER, choice, **({"work_package": package} if package else {}))
            seen_events = len(ctx.events)
            with rt.briefed(brief):
                self._delegate(choice, w, h, package)
            # Re-dispatching after the same provider failure (request too large, invalid tool call, ...)
            # repeats it until the time budget runs out: stop after the second identical failure.
            failure = next((e.detail for e in reversed(ctx.events[seen_events:])
                            if e.agent == choice and e.event == "failed"), None)
            sig = provider_failure_signature(choice, failure) if failure else None
            if sig is not None and sig == last_failure:
                h.coordinate("stop", MANAGER, None, f"{choice} failed twice with the same provider error")
                h.result.errors.append(f"Stopped: {choice} failed twice in a row with the same provider error "
                                       f"(retrying would repeat it): {failure[:300]}")
                break
            last_failure = sig
            if choice == "RequirementAnalyst" and w.req.status == AgentStatus.failed:
                raise RuntimeError("Requirement analysis failed: " + "; ".join(w.req.errors))
        else:
            h.coordinate("stop", MANAGER, None, f"cycle budget ({h.max_cycles}) exhausted")
            h.result.errors.append(f"Hierarchical manager stopped after {h.max_cycles} cycles")

        if h.result.verification_result is None:
            h.result.errors.append("Hierarchical run ended without a verification result")

    @staticmethod
    def _delegate(choice: str, w: _Work, h: RunHandle, package: list[int] | None = None) -> None:
        rt, ctx, kit, res = h.runtime, h.ctx, h.kit, h.result
        if choice == "RequirementAnalyst":
            w.req = res.requirement_analysis = rt.analyze_requirements(ctx, ctx.requirement)
            w.last = (choice, w.req)
        elif choice == "ProjectAnalyst":
            w.proj = res.project_analysis = rt.analyze_project(ctx, kit, w.req)
            w.last = (choice, w.proj)
        elif choice == "Planner":
            proj = w.proj or ProjectAnalysis(
                status=AgentStatus.skipped, workspace_id=ctx.workspace_id,
                summary="Project analysis skipped by the Manager: the requirement names the files to change.")
            w.plan = res.implementation_plan = rt.plan(ctx, kit, w.req, proj)
            w.packages, w.packages_done = make_packages(w.plan, w.package_size), []
            w.last = (choice, w.plan)
        elif choice == "Coder":
            target = w.package_index(package)
            plan = w.plan if target is None else package_plan(w.plan, w.packages[target], target + 1, len(w.packages))
            proj = w.proj or ProjectAnalysis(status=AgentStatus.skipped, workspace_id=ctx.workspace_id,
                                             summary="Project analysis skipped by the Manager.")
            coding = rt.code(ctx, kit, plan, proj, w.req)
            if target is None:
                w.packages_done = list(range(len(w.packages)))  # the whole plan was delegated at once
            elif target not in w.packages_done:
                w.packages_done.append(target)
            w.last_package = target
            w.coding = _merge_coding(w.coding, coding)
            res.coding_result = w.coding  # every package's changes
            h.record_coding(coding)
            w.change_seq += 1
            w.verified_after_change = False
            w.last = (choice, coding)  # review the package just delivered
        elif choice == "Tester":
            w.test = rt.test(ctx, kit)
            w.test_seq = w.change_seq
            h.record_test(w.test)
            if w.pending_debug is not None:
                w.pending_debug.test_result_after = w.test
                h.record_debug_iteration(w.pending_debug)
                w.pending_debug = None
            w.last = (choice, w.test)
        elif choice == "Debugger":
            iteration = h.max_debug_iterations - h.debug_budget_left + 1
            coding = w.coding or CodingResult(
                status=AgentStatus.skipped,
                summary="No code was changed yet: the failure was reproduced on the existing code.")
            record, applied = rt.debug(ctx, kit, coding, w.test, iteration, h.max_debug_iterations, w.req, w.plan)
            if applied:
                w.pending_debug = record
                w.change_seq += 1
                w.verified_after_change = False
            else:  # nothing changed; the iteration still counts against the budget
                record.test_result_after = w.test
                h.record_debug_iteration(record)
            w.last = (choice, record)
        elif choice == "Verifier":
            w.verification = rt.verify(ctx, kit, w.req, res.files_changed, w.test)
            h.record_verification(w.verification)
            w.verified_after_change = True
            w.last = (choice, w.verification)
