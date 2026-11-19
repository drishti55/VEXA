"""
VEXA API — agent-wise evaluation and benchmark exploration (VEXA Studio "Evaluation" and "Benchmarks").

GET /evaluation/agents[?experiment_id=]         every criterion of every agent (backend.evaluation.agent_eval)
GET /evaluation/agents/{name}[?experiment_id=]  one agent's criteria
GET /benchmarks/overview                        datasets, cases, experiment runs by outcome, coverage
GET /benchmarks/cases                           every case with per-mode / per-architecture results
GET /benchmarks/cases/{task_id}                 the case (requirement, criteria, files) and every run on it,
                                                with expected vs actual
GET /benchmarks/compare?mode=real|mock[&model=][&prompt_variant=]
                                                architecture comparison on the same cases

All numbers are recomputed from the run registry on each request. Mock and real runs are never mixed.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.evaluation.agent_eval import (
    MIN_SAMPLE,
    RunRow,
    criterion_covered,
    evaluate,
    load_task_truth,
)
from backend.evaluation.stats import newcombe_diff, wilson

router = APIRouter(tags=["evaluation"])

ARCHITECTURES = ("sequential", "hierarchical", "event_driven", "blackboard")
FINISHED = ("success", "partial", "failed", "interrupted")


def _tasks():
    from backend.evaluation.benchmark import load_tasks

    return load_tasks()


def _load_rows(experiment_id: str | None = None) -> list[RunRow]:
    from sqlalchemy import select

    from backend.db.models import CoordinationRow, Run
    from backend.db.registry import get_registry

    with get_registry()._session() as s:
        q = select(Run)
        if experiment_id:
            q = q.where(Run.experiment_id == experiment_id)
        runs = s.execute(q).scalars().all()
        coord: dict[str, list[dict]] = defaultdict(list)
        ids = [r.run_id for r in runs]
        for i in range(0, len(ids), 500):
            for c in s.execute(select(CoordinationRow).where(CoordinationRow.run_id.in_(ids[i:i + 500]))).scalars():
                coord[c.run_id].append({"kind": c.kind, "actor": c.actor, "target": c.target, "data": c.data or {}})
        return [RunRow(run_id=r.run_id, mode=r.execution_mode, status=r.status, architecture=r.architecture,
                       started_at=r.started_at.isoformat() if r.started_at else None, task_id=r.task_id,
                       grading=r.grading if isinstance(r.grading, dict) else None, result=r.result_json or {},
                       coordination=coord.get(r.run_id, [])) for r in runs]


# ---------------------------------------------------------------- evaluation

@router.get("/evaluation/agents")
def evaluation_all(experiment_id: str | None = None) -> dict:
    rows = _load_rows(experiment_id)
    crit = evaluate(rows, load_task_truth(_tasks()))
    return {"experiment_id": experiment_id, "runs": {"real": sum(r.mode == "real" for r in rows), "mock": sum(r.mode == "mock" for r in rows)},
            "min_sample": MIN_SAMPLE, "criteria": crit,
            "note": "Mock agents are scripted: mock scores check the pipeline, not the agent."}


@router.get("/evaluation/agents/{name}")
def evaluation_agent(name: str, experiment_id: str | None = None) -> dict:
    from backend.api.agents import agent_names

    if name not in agent_names():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown agent '{name}'")
    rows = _load_rows(experiment_id)
    return {"agent": name, "experiment_id": experiment_id, "min_sample": MIN_SAMPLE,
            "criteria": evaluate(rows, load_task_truth(_tasks()), agent=name)}


# ---------------------------------------------------------------- benchmarks

def _rate(flags: list[bool]) -> dict[str, Any]:
    k, n = sum(flags), len(flags)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [lo, hi]}


def _mean(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None}


@router.get("/benchmarks/overview")
def benchmarks_overview() -> dict:
    from sqlalchemy import select

    from backend.db.models import Experiment, Run
    from backend.db.registry import get_registry

    tasks = _tasks()
    rows = _load_rows()
    with get_registry()._session() as s:
        exps = s.execute(select(Experiment)).scalars().all()
    by_exp: dict[str, int] = defaultdict(int)
    with get_registry()._session() as s:
        for eid, in s.execute(select(Run.experiment_id).where(Run.experiment_id.is_not(None))):
            by_exp[eid] += 1
    pending = skipped = 0
    unknown_plan = []
    for e in exps:
        planned = e.total_trials
        if planned is None:
            unknown_plan.append(e.experiment_id)
            continue
        missing = max(0, planned - by_exp.get(e.experiment_id, 0))
        if e.status == "running":
            pending += missing
        else:
            skipped += missing
    bench = [r for r in rows if r.task_id]
    graded = [r for r in bench if r.grading and "task_success" in r.grading]
    graded_ids = {r.run_id for r in graded}
    out_modes = {}
    for mode in ("real", "mock"):
        b = [r for r in bench if r.mode == mode]
        out_modes[mode] = {
            "runs": len(b), "by_status": {s_: sum(r.status == s_ for r in b) for s_ in FINISHED},
            "graded": sum(1 for r in b if r.run_id in graded_ids), "cases_covered": len({r.task_id for r in b if r.run_id in graded_ids}),
        }
    last = max((r.started_at for r in bench if r.started_at), default=None)
    return {
        "datasets": [{"id": "benchmarks/tasks", "cases": len(tasks), "categories": sorted({t.category for t in tasks}),
                      "grader": "hidden_tests_v1 (hidden + visible pytest suites in a fresh copy of the final workspace)"}],
        "total_cases": len(tasks),
        "experiments": {"total": len(exps), "by_status": {st: sum(e.status == st for e in exps) for st in sorted({e.status for e in exps})}},
        "experiment_runs": {"total": sum(by_exp.values()), "pending": pending, "skipped": skipped,
                            "plan_unknown_for": unknown_plan,
                            "definitions": {"pending": "planned trials of running experiments not yet executed",
                                            "skipped": "planned trials of finished/cancelled/interrupted experiments that never ran"}},
        "benchmark_runs": out_modes,
        "evaluation_coverage": {"graded_runs": len(graded), "benchmark_runs": len(bench),
                                "rate": (len(graded) / len(bench)) if bench else None,
                                "cases_with_real_results": out_modes["real"]["cases_covered"], "cases": len(tasks)},
        "last_execution": last,
        "note": "A case is a task definition; a run is one execution of a case. Experiment runs and ad-hoc runs on benchmark cases are both benchmark runs.",
    }


@router.get("/benchmarks/cases")
def benchmark_cases() -> list[dict]:
    tasks = _tasks()
    rows = [r for r in _load_rows() if r.task_id]
    out = []
    for t in tasks:
        mine = [r for r in rows if r.task_id == t.id and r.grading and "task_success" in r.grading]
        entry: dict[str, Any] = {"id": t.id, "title": t.title, "category": t.category, "difficulty": t.difficulty,
                                 "acceptance_criteria": len(t.acceptance_criteria), "results": {}}
        for mode in ("real", "mock"):
            m = [r for r in mine if r.mode == mode]
            entry["results"][mode] = {"all": _rate([bool(r.grading["task_success"]) for r in m]),
                                      "by_architecture": {a: _rate([bool(r.grading["task_success"]) for r in m if r.architecture == a]) for a in ARCHITECTURES}}
        out.append(entry)
    return out


@router.get("/benchmarks/cases/{task_id}")
def benchmark_case(task_id: str) -> dict:
    tasks = {t.id: t for t in _tasks()}
    t = tasks.get(task_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown benchmark case '{task_id}'")
    from backend.api.source import REPO_ROOT

    def files(d) -> list[str]:
        return sorted(p.relative_to(REPO_ROOT).as_posix() for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)

    runs = []
    for r in sorted((r for r in _load_rows() if r.task_id == task_id), key=lambda x: x.started_at or "", reverse=True):
        extracted = [str(x) for x in (r.result.get("requirement_analysis") or {}).get("acceptance_criteria") or []]
        v = r.result.get("verification_result") or {}
        g = r.grading or {}
        runs.append({
            "run_id": r.run_id, "mode": r.mode, "architecture": r.architecture, "status": r.status, "started_at": r.started_at,
            "model": r.result.get("model"), "prompt_variant": r.result.get("prompt_variant"),
            "grading": {"task_success": g.get("task_success"), "hidden": g.get("hidden"), "visible": g.get("visible"),
                        "hidden_pass_rate": g.get("hidden_pass_rate"), "regression": g.get("regression")} if g else None,
            "verified": v.get("verified"), "llm_claimed_verified": v.get("llm_claimed_verified"),
            "criteria": [{"expected": c, "covered_by_analysis": criterion_covered(c, extracted),
                          "verifier": ("satisfied" if criterion_covered(c, [str(x) for x in v.get("requirements_satisfied") or []]) else
                                       "failed" if criterion_covered(c, [str(x) for x in v.get("requirements_failed") or []]) else "not_judged")}
                         for c in t.acceptance_criteria],
            "extracted_criteria": extracted,
            "verifier": {"satisfied": v.get("requirements_satisfied") or [], "failed": v.get("requirements_failed") or []},
            "files_changed": r.result.get("files_changed") or [],
            "code_changes": [{"path": c.get("path"), "change": c.get("change"), "lines_added": c.get("lines_added"),
                              "lines_removed": c.get("lines_removed"), "diff": c.get("diff")} for c in r.result.get("code_changes") or []],
        })
    return {
        "id": t.id, "title": t.title, "category": t.category, "difficulty": t.difficulty, "requirement": t.requirement,
        "acceptance_criteria": t.acceptance_criteria, "ground_truth": t.ground_truth or None, "timeout_seconds": t.timeout_seconds,
        "content_hash": t.content_hash,
        "files": {"task": f"benchmarks/tasks/{t.id}/task.json", "repo": files(t.repo_dir), "hidden_tests": files(t.hidden_dir),
                  "solution": files(t.solution_dir)},
        "runs": runs,
        "note": "criteria[].covered_by_analysis is a heuristic lexical match between the ground-truth criterion and the RequirementAnalyst's extracted criteria.",
    }


@router.get("/benchmarks/compare")
def compare_architectures(mode: str = Query(default="real", pattern="^(real|mock)$"), model: str | None = None,
                          prompt_variant: str | None = None) -> dict:
    rows = [r for r in _load_rows() if r.task_id and r.mode == mode and r.grading and "task_success" in r.grading]
    if model:
        rows = [r for r in rows if r.result.get("model") == model]
    if prompt_variant:
        rows = [r for r in rows if r.result.get("prompt_variant") == prompt_variant]
    models = sorted({str(r.result.get("model")) for r in rows})
    variants = sorted({str(r.result.get("prompt_variant")) for r in rows})
    warnings = []
    if len(models) > 1:
        warnings.append(f"Runs use {len(models)} different models; filter by model for a like-for-like comparison.")
    if len(variants) > 1:
        warnings.append(f"Runs use {len(variants)} prompt variants; filter by prompt_variant for a like-for-like comparison.")

    cases = sorted({r.task_id for r in rows})
    summary = {}
    for a in ARCHITECTURES:
        m = [r for r in rows if r.architecture == a]
        cov = []
        for r in m:
            crit = (r.result.get("requirement_analysis") or {}).get("acceptance_criteria") or []
            v = r.result.get("verification_result") or {}
            judged = [str(x) for x in (v.get("requirements_satisfied") or []) + (v.get("requirements_failed") or [])]
            if crit:
                cov.append(sum(criterion_covered(str(c), judged) for c in crit) / len(crit))
        costs = [r.result.get("estimated_cost_usd") for r in m if isinstance(r.result.get("estimated_cost_usd"), (int, float))]
        tokens = [float(r.result.get("total_tokens") or 0) for r in m if r.result.get("usage_available")]
        metrics = (r.result.get("agent_metrics") or {} for r in m)
        retries = [sum((am.get("validation_retries") or 0) + (am.get("llm_retries") or 0) for am in ms.values()) for ms in metrics]
        tool_calls = [sum((am.get("tool_calls") or 0) for am in (r.result.get("agent_metrics") or {}).values()) for r in m]
        summary[a] = {
            "runs": len(m), "cases": len({r.task_id for r in m}),
            "task_success": _rate([bool(r.grading["task_success"]) for r in m]),
            "verification_pass": _rate([bool((r.result.get("verification_result") or {}).get("verified")) for r in m]),
            "test_pass": _rate([bool((r.result.get("final_test_result") or {}).get("passed")) for r in m]),
            "run_failed": _rate([r.status == "failed" for r in m]),
            "acceptance_coverage": _mean(cov),
            "duration_ms": _mean([float(r.result.get("total_duration_ms") or 0) for r in m]),
            "tokens": {**_mean(tokens), "runs_with_usage": len(tokens)},
            "tool_calls": _mean([float(x) for x in tool_calls]),
            "retries": _mean([float(x) for x in retries]),
            "cost_usd": {**_mean([float(c) for c in costs]), "runs_with_cost": len(costs),
                         "label": "estimated from configured per-token prices" if costs else "unavailable (no pricing configured)"},
            "sample": "ok" if len(m) >= MIN_SAMPLE else "insufficient" if m else "none",
        }
    base = summary["sequential"]["task_success"]
    diffs = {}
    for a in ARCHITECTURES[1:]:
        s_ = summary[a]["task_success"]
        if base["n"] and s_["n"]:
            d = newcombe_diff(s_["k"], s_["n"], base["k"], base["n"])
            diffs[f"{a}_minus_sequential"] = {**d, "interpretation": (
                "insufficient sample" if min(s_["n"], base["n"]) < MIN_SAMPLE else
                "no evidence of a difference (95% CI includes 0)" if d.get("low") is not None and d["low"] <= 0 <= d["high"] else
                "difference unlikely to be due to chance alone at 95% (still check comparability)")}
    matrix = [{"case": c, **{a: _rate([bool(r.grading["task_success"]) for r in rows if r.task_id == c and r.architecture == a]) for a in ARCHITECTURES}} for c in cases]
    return {"mode": mode, "models": models, "prompt_variants": variants, "filters": {"model": model, "prompt_variant": prompt_variant},
            "warnings": warnings, "architectures": summary, "differences": diffs, "case_matrix": matrix,
            "note": ("Mock agents are scripted: these numbers check the pipeline, not the architectures." if mode == "mock" else
                     "Rates carry 95% Wilson intervals; differences use Newcombe intervals. No significance is claimed below "
                     f"{MIN_SAMPLE} runs per architecture.")}


# ---------------------------------------------------------------- dashboard, models, failures, search

@router.get("/dashboard/summary")
def dashboard_summary() -> dict:
    rows = _load_rows()
    out: dict[str, Any] = {}
    for mode in ("real", "mock"):
        m = [r for r in rows if r.mode == mode]
        durations = [float(r.result.get("total_duration_ms") or 0) for r in m if r.status in FINISHED]
        tokens = [float(r.result.get("total_tokens") or 0) for r in m if r.result.get("usage_available")]
        out[mode] = {
            "runs": len(m), "by_status": {s_: sum(r.status == s_ for r in m) for s_ in (*FINISHED, "running")},
            "avg_duration_ms": statistics.fmean(durations) if durations else None,
            "tokens_total": sum(tokens), "runs_with_usage": len(tokens),
            "by_architecture": {a: {"runs": len(x := [r for r in m if r.architecture == a]),
                                    "success": _rate([r.status == "success" for r in x]),
                                    "avg_duration_ms": statistics.fmean([float(r.result.get("total_duration_ms") or 0) for r in x]) if x else None,
                                    "avg_tokens": statistics.fmean([float(r.result.get("total_tokens") or 0) for r in x if r.result.get("usage_available")])
                                    if any(r.result.get("usage_available") for r in x) else None}
                                for a in ARCHITECTURES},
        }
    out["benchmark_cases"] = len(_tasks())
    out["experiment_runs"] = sum(1 for r in rows if r.task_id)
    out["note"] = "Run success = the run's own status (sandbox tests + verification); benchmark success uses the hidden-test grader."
    return out


@router.get("/evaluation/models")
def model_comparison() -> dict:
    """Real runs only: per model and agent, from the per-agent metrics table."""
    from sqlalchemy import select

    from backend.db.models import AgentRun, Run
    from backend.db.registry import get_registry

    with get_registry()._session() as s:
        rows = s.execute(select(AgentRun, Run.model, Run.provider, Run.estimated_cost_usd)
                         .join(Run, Run.run_id == AgentRun.run_id).where(Run.execution_mode == "real")).all()
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for r in rows:
        if r.AgentRun.invocations:
            groups[(r.model or "unknown", r.AgentRun.agent)].append(r.AgentRun)
    out = []
    for (model, agent), ar in sorted(groups.items()):
        inv = sum(a.invocations for a in ar)
        tok = [a.input_tokens + a.output_tokens for a in ar if a.input_tokens or a.output_tokens]
        out.append({"model": model, "agent": agent, "executions": len(ar),
                    "success": _rate([a.failures == 0 for a in ar]), "error_rate": sum(a.failures for a in ar) / inv if inv else None,
                    "avg_duration_ms": statistics.fmean([a.duration_ms / a.invocations for a in ar]),
                    "avg_tokens": statistics.fmean(tok) if tok else None, "tokens_total": sum(tok),
                    "llm_calls": sum(a.llm_calls for a in ar), "validation_retries": sum(a.validation_retries for a in ar)})
    return {"rows": out, "models": sorted({r["model"] for r in out}),
            "note": "Real runs only. Executions of one agent with one model; success = no failed invocation in the run."}


_NORMALISE = [
    (re.compile(r"https?://\S+"), "<url>"), (re.compile(r"`[^`]*`|'[^']*'|\"[^\"]*\""), "<str>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|\b(?:org|req|run)_[a-z0-9]+\b|\b[0-9a-f]{12,}\b", re.I), "<id>"),
    (re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|m)?\b"), "<n>"), (re.compile(r"\s+"), " "),
]
_CATEGORIES = [
    ("rate limit", ("rate limit", "429", "tokens per day", "tpm", "rpm")), ("model access / credentials", ("does not exist", "api key", "authentication", "unauthorized", "401", "403")),
    ("A2A / remote verifier", ("a2a",)), ("time budget (G7)", ("time budget",)), ("token budget (G7)", ("token budget",)), ("output validation (G8)", ("validation", "schema", "json")),
    ("tool error", ("tool",)), ("provider / network", ("connection", "timeout", "timed out", "503", "502", "500")), ("cancelled", ("cancel",)),
]


def _signature(msg: str) -> str:
    s = msg.strip()
    for rx, rep in _NORMALISE:
        s = rx.sub(rep, s)
    return s[:160]


@router.get("/evaluation/failures")
def failure_clusters(mode: str = Query(default="real", pattern="^(real|mock)$")) -> dict:
    """Group run errors and agent failure events by a normalised message signature (ids, numbers, quoted text removed)."""
    rows = [r for r in _load_rows() if r.mode == mode]
    clusters: dict[str, dict[str, Any]] = {}
    for r in rows:
        msgs = [("run", e) for e in r.result.get("errors") or []]
        msgs += [(e.get("agent") or "runtime", e.get("detail") or "") for e in r.result.get("events") or []
                 if e.get("event") == "failed" or str(e.get("event", "")).endswith("_failed")]
        seen = set()
        for source, msg in msgs:
            if not msg:
                continue
            sig = _signature(msg)
            if (sig, r.run_id) in seen:
                continue
            seen.add((sig, r.run_id))
            low = msg.lower()
            c = clusters.setdefault(sig, {"signature": sig, "category": next((n for n, keys in _CATEGORIES if any(k in low for k in keys)), "other"),
                                         "occurrences": 0, "runs": [], "sources": Counter(), "architectures": Counter(), "example": msg[:600]})
            c["occurrences"] += 1
            c["sources"][source] += 1
            c["architectures"][r.architecture] += 1
            if r.run_id not in c["runs"]:
                c["runs"].append(r.run_id)
    out = sorted(clusters.values(), key=lambda c: -c["occurrences"])
    for c in out:
        c["sources"], c["architectures"], c["run_count"], c["runs"] = dict(c["sources"]), dict(c["architectures"]), len(c["runs"]), c["runs"][:20]
    by_cat = Counter()
    for c in out:
        by_cat[c["category"]] += c["occurrences"]
    return {"mode": mode, "runs": len(rows), "failed_runs": sum(r.status == "failed" for r in rows), "clusters": out,
            "by_category": dict(by_cat.most_common()),
            "method": "Messages are normalised (URLs, quoted values, ids and numbers replaced) and grouped by identical signature; categories are keyword heuristics."}


@router.get("/search")
def global_search(q: str = Query(min_length=2, max_length=200), limit: int = Query(default=40, ge=1, le=200)) -> dict:
    """Search runs (requirement, id, errors), benchmark cases, agents, guardrail rules and VEXA source file paths."""
    from backend.api.agents import agent_names
    from backend.api.source import source_tree
    from backend.guardrails import RULES

    needle = q.lower()
    hits: list[dict[str, Any]] = []
    for r in sorted(_load_rows(), key=lambda x: x.started_at or "", reverse=True):
        req = str(r.result.get("requirement") or "")
        errs = " ".join(r.result.get("errors") or [])
        if needle in r.run_id or needle in req.lower() or needle in errs.lower():
            hits.append({"type": "run", "id": r.run_id, "title": req[:120] or r.run_id,
                         "detail": f"{r.status} · {r.architecture} · {r.mode}" + (" · matched error" if needle in errs.lower() else "")})
    run_hits, hits = hits, []
    for t in _tasks():
        if needle in f"{t.id} {t.title} {t.requirement} {' '.join(t.acceptance_criteria)}".lower():
            hits.append({"type": "case", "id": t.id, "title": t.title, "detail": f"{t.category} · {t.difficulty}"})
    for a in agent_names():
        if needle in a.lower():
            hits.append({"type": "agent", "id": a, "title": a, "detail": "agent"})
    for kind, (gid, name) in RULES.items():
        if needle in f"{gid} {name} {kind}".lower():
            hits.append({"type": "guardrail", "id": gid, "title": f"{gid} {name}", "detail": kind})
    for f in source_tree()["files"]:
        if needle in f["path"].lower():
            hits.append({"type": "source", "id": f["path"], "title": f["path"].split("/")[-1], "detail": f["path"]})
    hits += run_hits  # specific entities first, then the (often many) runs
    return {"query": q, "total": len(hits), "results": hits[:limit]}
