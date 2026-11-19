"""
Per-agent evaluation criteria, computed from persisted records only.

Each criterion is evaluated on observations taken from stored runs (``runs.result_json``,
``runs.grading`` written by the independent hidden-test grader, ``coordination_events`` and the
benchmark task definitions with their reference solutions). Nothing is scored by an LLM and no
score is stored: everything is recomputed on request.

Real and mock runs are reported separately. Mock agents return scripted answers, so a mock score
measures the pipeline, never the agent; the UI labels it accordingly.

A criterion that cannot be measured with the current data is returned with status
``not_evaluated`` and the missing data or instrumentation.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.evaluation.stats import wilson

MIN_SAMPLE = 5  # below this a score is shown but flagged as insufficient data


# ---------------------------------------------------------------- inputs

@dataclass
class RunRow:
    run_id: str
    mode: str
    status: str
    architecture: str
    started_at: str | None
    task_id: str | None
    grading: dict[str, Any] | None
    result: dict[str, Any]
    coordination: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskTruth:
    id: str
    acceptance_criteria: list[str]
    solution_files: set[str]
    repo_files: set[str]


def load_task_truth(tasks: list[Any]) -> dict[str, TaskTruth]:
    out = {}
    for t in tasks:
        sol = {p.relative_to(t.solution_dir).as_posix() for p in Path(t.solution_dir).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        repo = {p.relative_to(t.repo_dir).as_posix() for p in Path(t.repo_dir).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        out[t.id] = TaskTruth(t.id, list(t.acceptance_criteria), sol, repo)
    return out


# ---------------------------------------------------------------- helpers

_WORD = re.compile(r"[a-z0-9_]+|==|!=|<=|>=|[<>%*/+-]")


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


def criterion_covered(truth: str, extracted: list[str], threshold: float = 0.5) -> bool:
    """Heuristic: a ground-truth acceptance criterion is covered if an extracted criterion shares at
    least `threshold` of its tokens (identifiers, numbers, operators)."""
    t = _tokens(truth)
    if not t:
        return False
    return any(len(t & _tokens(e)) / len(t) >= threshold for e in extracted)


def _norm(path: str) -> str:
    return path.strip().lstrip("./").replace("\\", "/")


def _get(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# Debugger-probe runs skip the Coder, so they say nothing about it.
PROBE_EXCLUDED = {"Coder"}


def _is_probe(r: RunRow) -> bool:
    return bool((r.result.get("metadata") or {}).get("probe"))


def _benchmark(rows: list[RunRow]) -> list[RunRow]:
    return [r for r in rows if r.task_id and isinstance(r.grading, dict) and "task_success" in r.grading]


# ---------------------------------------------------------------- criteria

@dataclass
class Criterion:
    id: str
    agent: str
    name: str
    definition: str
    method: str
    formula: str
    data_source: str
    kind: str  # deterministic | heuristic | not_measurable
    observe: Callable[[list[RunRow], dict[str, TaskTruth]], list[tuple[RunRow, float]]] | None = None
    value: str = "rate"  # rate (observations 0/1) | mean (numeric)
    higher_is_better: bool = True
    missing: str | None = None


def _validity(result_key: str) -> Callable:
    def obs(rows, _truth):
        out = []
        for r in rows:
            v = _get(r.result, result_key, "output_valid")
            if isinstance(v, bool):
                out.append((r, 1.0 if v else 0.0))
        return out
    return obs


def _ra_coverage(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        extracted = _get(r.result, "requirement_analysis", "acceptance_criteria")
        if not t or not t.acceptance_criteria or not isinstance(extracted, list):
            continue
        covered = sum(criterion_covered(c, [str(e) for e in extracted]) for c in t.acceptance_criteria)
        out.append((r, covered / len(t.acceptance_criteria)))
    return out


def _pa_recall(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        rel = _get(r.result, "project_analysis", "relevant_files")
        if not t or not t.solution_files or not isinstance(rel, list):
            continue
        got = {_norm(x) for x in rel}
        out.append((r, len(t.solution_files & got) / len(t.solution_files)))
    return out


def _pa_irrelevant(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        rel = _get(r.result, "project_analysis", "relevant_files")
        if not t or not isinstance(rel, list) or not rel:
            continue
        got = {_norm(x) for x in rel}
        useful = t.solution_files | {f for f in t.repo_files if f.startswith("tests/")}
        out.append((r, len(got - useful) / len(got)))
    return out


def _pa_reference_accuracy(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        rel = _get(r.result, "project_analysis", "relevant_files")
        if not t or not isinstance(rel, list) or not rel:
            continue
        got = {_norm(x) for x in rel}
        out.append((r, len(got & (t.repo_files | t.solution_files)) / len(got)))
    return out


def _plan_files(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        plan = _get(r.result, "implementation_plan")
        if not t or not t.solution_files or not isinstance(plan, dict):
            continue
        planned = {_norm(x) for x in (plan.get("files_to_modify") or []) + (plan.get("files_to_create") or [])}
        for s in plan.get("steps") or []:
            planned |= {_norm(x) for x in (s.get("files_affected") or [])}
        out.append((r, len(t.solution_files & planned) / len(t.solution_files)))
    return out


def _grading_flag(key: str, invert: bool = False):
    def obs(rows, _truth):
        out = []
        for r in _benchmark(rows):
            v = r.grading.get(key)
            if isinstance(v, bool):
                out.append((r, float(v != invert)))
        return out
    return obs


def _hidden_rate(rows, _truth):
    return [(r, float(r.grading["hidden_pass_rate"])) for r in _benchmark(rows) if isinstance(r.grading.get("hidden_pass_rate"), (int, float))]


def _unnecessary_changes(rows, truth):
    out = []
    for r in _benchmark(rows):
        t = truth.get(r.task_id)
        changed = r.result.get("files_changed")
        if not t or not isinstance(changed, list) or not changed:
            continue
        extra = [f for f in changed if _norm(f) not in t.solution_files and not _norm(f).startswith("tests/")]
        out.append((r, len(extra) / len(changed)))
    return out


def _tester_agreement(rows, _truth):
    """Sandbox verdict of the run vs the independent grader's visible suite."""
    out = []
    for r in _benchmark(rows):
        ft = r.result.get("final_test_result")
        vis = r.grading.get("visible") or {}
        if not isinstance(ft, dict) or vis.get("exit_code") is None or ft.get("no_tests"):
            continue
        out.append((r, float(bool(ft.get("passed")) == (vis.get("exit_code") == 0))))
    return out


def _tester_fp(rows, _truth):
    out = []
    for r in _benchmark(rows):
        ft = r.result.get("final_test_result")
        vis = r.grading.get("visible") or {}
        if isinstance(ft, dict) and ft.get("passed") and vis.get("exit_code") is not None:
            out.append((r, float(vis.get("exit_code") != 0)))
    return out


def _tester_fn(rows, _truth):
    out = []
    for r in _benchmark(rows):
        ft = r.result.get("final_test_result")
        vis = r.grading.get("visible") or {}
        if isinstance(ft, dict) and ft.get("passed") is False and not ft.get("no_tests") and vis.get("exit_code") is not None:
            out.append((r, float(vis.get("exit_code") == 0)))
    return out


def _debug_runs(rows):
    return [r for r in rows if (r.result.get("debug_iterations") or 0) > 0]


def _debug_fix(rows, _truth):
    out = []
    for r in _debug_runs(rows):
        ft = r.result.get("final_test_result")
        if isinstance(ft, dict) and not ft.get("no_tests"):
            out.append((r, float(bool(ft.get("passed")))))
    return out


def _debug_iterations(rows, _truth):
    return [(r, float(r.result.get("debug_iterations") or 0)) for r in _debug_runs(rows)]


def _debug_regression(rows, _truth):
    return [(r, float(bool(r.grading.get("regression")))) for r in _benchmark(_debug_runs(rows)) if isinstance(r.grading.get("regression"), bool)]


def _verdict(r) -> dict | None:
    """The Verifier's result, only if it actually returned a verdict.

    ``llm_claimed_verified`` is set when the runtime applied sandbox ground truth to an
    answer. A Verifier that crashed (provider error, A2A failure) has no verdict: it neither
    accepted nor rejected the work, so it is counted by ``_verifier_errors``, not as a rejection.
    """
    v = r.result.get("verification_result")
    if (isinstance(v, dict) and isinstance(v.get("verified"), bool) and v.get("llm_claimed_verified") is not None
            and v.get("output_valid") is not False):  # an unparseable answer is not a verdict either
        return v
    return None


def _verifier_errors(rows, _truth):
    """Share of Verifier invocations that ended without a verdict."""
    return [(r, float(_verdict(r) is None)) for r in rows if isinstance(r.result.get("verification_result"), dict)]


def _verifier_false_accept(rows, _truth):
    return [(r, float(not r.grading["task_success"])) for r in _benchmark(rows)
            if (v := _verdict(r)) is not None and v["verified"] is True]


def _verifier_false_reject(rows, _truth):
    return [(r, float(v["verified"] is False)) for r in _benchmark(rows)
            if r.grading["task_success"] and (v := _verdict(r)) is not None]


def _verifier_accuracy(rows, _truth):
    return [(r, float(v["verified"] == r.grading["task_success"])) for r in _benchmark(rows)
            if (v := _verdict(r)) is not None]


def _verifier_unsupported(rows, _truth):
    """The model claimed success but the backend's evidence (sandbox tests, real changes) overrode it."""
    out = []
    for r in rows:
        v = r.result.get("verification_result")
        if isinstance(v, dict) and v.get("llm_claimed_verified") is True:
            out.append((r, float(v.get("verified") is not True)))
    return out


def _verifier_coverage(rows, _truth):
    out = []
    for r in rows:
        crit = _get(r.result, "requirement_analysis", "acceptance_criteria")
        v = _verdict(r)
        if not isinstance(crit, list) or not crit or v is None:
            continue
        judged = [str(x) for x in (v.get("requirements_satisfied") or []) + (v.get("requirements_failed") or [])]
        out.append((r, sum(criterion_covered(str(c), judged) for c in crit) / len(crit)))
    return out


def _manager_rework(rows, _truth):
    out = []
    for r in rows:
        for c in r.coordination:
            if c.get("kind") == "review" and c.get("actor", "").lower() == "manager":
                out.append((r, float((c.get("data") or {}).get("verdict") not in (None, "accept"))))
    return out


def _manager_selection(rows, _truth):
    out = []
    for r in rows:
        for c in r.coordination:
            data = c.get("data") or {}
            if c.get("kind") == "decision" and c.get("actor", "").lower() == "manager" and isinstance(data.get("accepted"), bool):
                out.append((r, float(data["accepted"])))
    return out


def _manager_final(rows, _truth):
    """Hierarchical benchmark runs: the manager finishing with a successful run status agrees with hidden-test grading."""
    out = []
    for r in _benchmark([x for x in rows if x.architecture == "hierarchical"]):
        if r.status in ("success", "partial", "failed"):
            out.append((r, float((r.status == "success") == bool(r.grading["task_success"]))))
    return out


BENCH = "benchmark runs (runs.task_id) graded by the independent hidden-test grader (runs.grading)"
VALIDITY = ("Structured output validity", "Share of the agent's answers that passed schema validation (after the bounded re-prompting).",
            "Read the agent's output_valid flag recorded on its structured result.", "valid answers / answers")

CRITERIA: list[Criterion] = [
    # RequirementAnalyst
    Criterion("ra.criteria_coverage", "RequirementAnalyst", "Acceptance-criteria coverage",
              "How many of the benchmark task's ground-truth acceptance criteria appear in the extracted acceptance criteria.",
              "Lexical token-overlap match (≥50% of a ground-truth criterion's identifiers, numbers and operators found in one extracted criterion).",
              "mean over runs of (covered ground-truth criteria / ground-truth criteria)",
              f"task.json acceptance_criteria vs result.requirement_analysis.acceptance_criteria; {BENCH}", "heuristic", _ra_coverage, "mean"),
    Criterion("ra.validity", "RequirementAnalyst", *VALIDITY, "result.requirement_analysis.output_valid", "deterministic", _validity("requirement_analysis")),
    Criterion("ra.ambiguity", "RequirementAnalyst", "Ambiguity identification",
              "Whether the ambiguities the agent lists are the real ambiguities of the requirement.", "—", "—", "—", "not_measurable",
              missing="No labelled ambiguities exist for the benchmark tasks. Add an `ambiguities` list to each task.json (or a human rubric) to measure precision/recall."),
    Criterion("ra.assumptions", "RequirementAnalyst", "Unsupported assumption rate",
              "Requirements the agent added that are not supported by the request.", "—", "—", "—", "not_measurable",
              missing="Needs per-criterion labels (supported / unsupported) from a reviewer or an evaluated LLM judge; neither is recorded."),
    # ProjectAnalyst
    Criterion("pa.file_recall", "ProjectAnalyst", "Relevant file identification (recall)",
              "Share of the files the reference solution changes that the analyst marked as relevant.",
              "Set intersection of paths.", "mean of |relevant_files ∩ solution files| / |solution files|",
              f"benchmarks/tasks/*/solution vs result.project_analysis.relevant_files; {BENCH}", "deterministic", _pa_recall, "mean"),
    Criterion("pa.irrelevant", "ProjectAnalyst", "Irrelevant context rate",
              "Share of the files marked relevant that are neither changed by the reference solution nor tests.",
              "Set difference of paths.", "mean of |relevant − (solution ∪ tests)| / |relevant|",
              f"benchmarks/tasks/*/solution and repo/tests vs result.project_analysis.relevant_files; {BENCH}", "deterministic",
              _pa_irrelevant, "mean", higher_is_better=False),
    Criterion("pa.reference_accuracy", "ProjectAnalyst", "File-reference accuracy",
              "Share of referenced files that actually exist in the task repository (or are created by the solution).",
              "Path existence check against the starting repository.", "mean of |relevant ∩ (repo ∪ solution)| / |relevant|",
              f"benchmarks/tasks/*/repo vs result.project_analysis.relevant_files; {BENCH}", "deterministic", _pa_reference_accuracy, "mean"),
    Criterion("pa.validity", "ProjectAnalyst", *VALIDITY, "result.project_analysis.output_valid", "deterministic", _validity("project_analysis")),
    # Planner
    Criterion("pl.target_files", "Planner", "Plan targets the right files",
              "Share of the files changed by the reference solution that the plan intends to create or modify.",
              "Set intersection of paths (files_to_modify, files_to_create, steps[].files_affected).",
              "mean of |planned ∩ solution| / |solution|", f"benchmarks/tasks/*/solution vs result.implementation_plan; {BENCH}",
              "deterministic", _plan_files, "mean"),
    Criterion("pl.validity", "Planner", *VALIDITY, "result.implementation_plan.output_valid", "deterministic", _validity("implementation_plan")),
    Criterion("pl.quality", "Planner", "Task decomposition quality and feasibility",
              "Whether the steps are complete, correctly ordered and implementable.", "—", "—", "—", "not_measurable",
              missing="Needs a scoring rubric applied by reviewers or a validated LLM judge; no such scores are recorded."),
    Criterion("pl.dependencies", "Planner", "Dependency identification",
              "Whether ordering constraints between steps are identified.", "—", "—", "—", "not_measurable",
              missing="Plans do not record step dependencies (ImplementationStepOutput has no depends_on field)."),
    # Coder
    Criterion("co.task_success", "Coder", "Task success (hidden tests)",
              "Share of benchmark runs where every hidden and visible test passes after the run.",
              "Independent grader runs the hidden tests in a fresh copy of the final workspace.", "task_success runs / graded runs",
              BENCH, "deterministic", _grading_flag("task_success")),
    Criterion("co.hidden_pass", "Coder", "Hidden-test pass rate",
              "Mean share of hidden tests that pass.", "Independent grader.", "mean of hidden passed / hidden collected", BENCH,
              "deterministic", _hidden_rate, "mean"),
    Criterion("co.regression", "Coder", "Regression rate",
              "Share of runs where a visible test that passed on the starting repository fails afterwards.", "Independent grader.",
              "runs with regression / graded runs", BENCH, "deterministic", _grading_flag("regression"), higher_is_better=False),
    Criterion("co.unnecessary", "Coder", "Unnecessary modifications",
              "Share of changed files that the reference solution does not touch (tests excluded).", "Set difference of paths.",
              "mean of |changed − solution − tests| / |changed|", f"result.files_changed vs benchmarks/tasks/*/solution; {BENCH}",
              "deterministic", _unnecessary_changes, "mean", higher_is_better=False),
    Criterion("co.validity", "Coder", *VALIDITY, "result.coding_result.output_valid", "deterministic", _validity("coding_result")),
    # Tester
    Criterion("te.agreement", "Tester", "Verdict agreement with independent grading",
              "Share of runs where the Tester's sandbox verdict matches the grader's run of the visible suite.",
              "Compare final_test_result.passed with grading.visible.exit_code == 0.", "agreeing runs / comparable runs",
              f"result.final_test_result vs runs.grading.visible; {BENCH}", "deterministic", _tester_agreement),
    Criterion("te.false_pass", "Tester", "False pass rate",
              "Of the runs the Tester reported as passing, the share the grader found failing.", "As above.",
              "reported pass ∧ grader fail / reported pass", f"result.final_test_result vs runs.grading.visible; {BENCH}",
              "deterministic", _tester_fp, higher_is_better=False),
    Criterion("te.false_fail", "Tester", "False failure rate",
              "Of the runs the Tester reported as failing, the share the grader found passing.", "As above.",
              "reported fail ∧ grader pass / reported fail", f"result.final_test_result vs runs.grading.visible; {BENCH}",
              "deterministic", _tester_fn, higher_is_better=False),
    Criterion("te.coverage", "Tester", "Test coverage", "Line/branch coverage of the code under test.", "—", "—", "—", "not_measurable",
              missing="The sandbox runs pytest without coverage instrumentation (no pytest-cov data is recorded)."),
    # Debugger
    Criterion("db.fix_success", "Debugger", "Fix success rate",
              "Of the runs with at least one debug iteration, the share whose final sandbox test run passes.",
              "Sandbox test verdict after the last debug iteration.", "runs with final pass / runs with debugging",
              "result.debug_iterations and result.final_test_result (all runs)", "deterministic", _debug_fix),
    Criterion("db.iterations", "Debugger", "Debugging iterations", "Mean number of debug iterations when debugging happened.",
              "Count recorded by the runtime.", "mean of debug_iterations (runs with ≥1)", "result.debug_iterations",
              "deterministic", _debug_iterations, "mean", higher_is_better=False),
    Criterion("db.regression", "Debugger", "Regression introduction rate",
              "Of benchmark runs with debugging, the share where the grader finds a regression.", "Independent grader.",
              "regressions / graded runs with debugging", BENCH, "deterministic", _debug_regression, higher_is_better=False),
    Criterion("db.root_cause", "Debugger", "Root cause identification accuracy", "Whether the stated root cause is the real one.",
              "—", "—", "—", "not_measurable",
              missing="Benchmark tasks have no labelled root cause; add one per bug-fix task to compare against debug_report.root_cause."),
    # Verifier
    Criterion("ve.accuracy", "Verifier", "Verification accuracy",
              "Of the benchmark runs where the Verifier gave a verdict, the share whose verified flag equals the grader's task_success.", "Independent grader.",
              "agreeing runs / graded runs", f"result.verification_result.verified vs runs.grading.task_success; {BENCH}",
              "deterministic", _verifier_accuracy),
    Criterion("ve.false_accept", "Verifier", "False acceptance rate",
              "Of the runs the Verifier accepted, the share that fail the hidden tests.", "Independent grader.",
              "verified ∧ ¬task_success / verified", BENCH, "deterministic", _verifier_false_accept, higher_is_better=False),
    Criterion("ve.false_reject", "Verifier", "False rejection rate",
              "Of the runs that pass the hidden tests and got a verdict, the share the Verifier rejected (a crashed Verifier is not a rejection).", "Independent grader.",
              "¬verified ∧ task_success / task_success", BENCH, "deterministic", _verifier_false_reject, higher_is_better=False),
    Criterion("ve.errors", "Verifier", "Verifier error rate",
              "Share of Verifier invocations that ended without a verdict (provider error, rejected tool call, A2A failure).",
              "A verdict exists when the runtime applied sandbox ground truth to the Verifier's answer.",
              "invocations without a verdict / invocations", "result.verification_result (all runs)",
              "deterministic", _verifier_errors, higher_is_better=False),
    Criterion("ve.unsupported", "Verifier", "Unsupported success claims",
              "Of the answers where the model claimed success, the share the runtime overrode because the evidence (sandbox tests, actual changes) did not support it.",
              "Compare llm_claimed_verified with the evidence-checked verified flag.", "claimed ∧ ¬verified / claimed",
              "result.verification_result (all runs)", "deterministic", _verifier_unsupported, higher_is_better=False),
    Criterion("ve.criteria_coverage", "Verifier", "Acceptance-criteria coverage",
              "Share of the extracted acceptance criteria that the Verifier explicitly judged (satisfied or failed), over runs with a verdict.",
              "Lexical token-overlap match against requirements_satisfied ∪ requirements_failed.",
              "mean of judged criteria / criteria", "result.requirement_analysis and result.verification_result (all runs)",
              "heuristic", _verifier_coverage, "mean"),
    # Manager
    Criterion("ma.rework", "Manager", "Rework frequency", "Share of the Manager's reviews that sent work back (verdict ≠ accept).",
              "Count review events.", "non-accept reviews / reviews", "coordination_events (kind=review, actor=Manager)",
              "deterministic", _manager_rework, higher_is_better=False),
    Criterion("ma.selection", "Manager", "Agent selection validity",
              "Share of the Manager's delegation decisions the runtime accepted (invalid picks are rejected and fed back).",
              "Read the accepted flag on decision events.", "accepted decisions / decisions", "coordination_events (kind=decision, actor=Manager)",
              "deterministic", _manager_selection),
    Criterion("ma.final_decision", "Manager", "Final decision correctness",
              "Hierarchical benchmark runs: whether finishing with a successful run agrees with the hidden-test grading.",
              "Compare run status == success with grading.task_success.", "agreeing runs / graded hierarchical runs", BENCH,
              "deterministic", _manager_final),
    Criterion("ma.delegation", "Manager", "Delegation and review quality", "Whether briefs and reviews are useful.", "—", "—", "—",
              "not_measurable", missing="Needs reviewer ratings of briefs/reviews; none are recorded."),
]


def _aggregate(obs: list[tuple[RunRow, float]], value: str) -> dict[str, Any]:
    n = len(obs)
    if n == 0:
        return {"n": 0, "score": None}
    vals = [v for _, v in obs]
    out: dict[str, Any] = {"n": n, "score": statistics.fmean(vals)}
    if value == "rate":
        k = int(round(sum(vals)))
        lo, hi = wilson(k, n)
        out.update({"successes": k, "failures": n - k, "ci95": [lo, hi]})
    else:
        out.update({"successes": None, "failures": None, "sd": statistics.stdev(vals) if n > 1 else None})
    by_day: dict[str, list[float]] = defaultdict(list)
    for r, v in obs:
        by_day[(r.started_at or "")[:10] or "unknown"].append(v)
    out["trend"] = [{"date": d, "score": statistics.fmean(v), "n": len(v)} for d, v in sorted(by_day.items())]
    out["runs"] = [r.run_id for r, _ in obs][-50:]
    return out


def evaluate(rows: list[RunRow], truth: dict[str, TaskTruth], agent: str | None = None) -> list[dict[str, Any]]:
    by_mode: dict[str, list[RunRow]] = defaultdict(list)
    for r in rows:
        by_mode[r.mode].append(r)
    out = []
    for c in CRITERIA:
        if agent and c.agent != agent:
            continue
        entry: dict[str, Any] = {
            "id": c.id, "agent": c.agent, "name": c.name, "definition": c.definition, "method": c.method, "formula": c.formula,
            "data_source": c.data_source, "kind": c.kind, "value": c.value, "higher_is_better": c.higher_is_better,
        }
        if c.observe is None:
            entry.update({"status": "not_evaluated", "missing": c.missing, "real": None, "mock": None})
        else:
            pick = (lambda rs: [r for r in rs if not _is_probe(r)]) if c.agent in PROBE_EXCLUDED else (lambda rs: rs)
            entry["real"] = _aggregate(c.observe(pick(by_mode.get("real", [])), truth), c.value)
            entry["mock"] = _aggregate(c.observe(pick(by_mode.get("mock", [])), truth), c.value)
            n = entry["real"]["n"]
            entry["status"] = "evaluated" if n >= MIN_SAMPLE else "insufficient_data" if n > 0 else "no_data"
            if n == 0:
                entry["missing"] = "No real-model run has produced the data this criterion needs yet."
        out.append(entry)
    return out
