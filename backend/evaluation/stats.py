"""
Experiment statistics, always recomputed from raw registry rows.

Conditions are (architecture, prompt_variant, model_condition). For each we
report counts alongside every rate, Wilson 95% intervals for proportions,
and paired architecture differences with Newcombe (hybrid score) intervals.
Token and cost figures are averaged only over runs that reported usage /
had pricing, and the number of such runs is always shown next to them.
"""

from __future__ import annotations

import json

import csv
import io
import math
import statistics
from collections import defaultdict
from typing import Any

from backend.db.registry import RunRegistry, get_registry

Z = 1.959964  # 95%


def wilson(successes: int, n: int, z: float = Z) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_diff(s1: int, n1: int, s2: int, n2: int) -> dict[str, float | None]:
    """Difference p1 - p2 with the Newcombe hybrid-score 95% interval."""
    if n1 == 0 or n2 == 0:
        return {"diff": None, "low": None, "high": None}
    p1, p2 = s1 / n1, s2 / n2
    l1, u1 = wilson(s1, n1)
    l2, u2 = wilson(s2, n2)
    d = p1 - p2
    low = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {"diff": d, "low": low, "high": high}


def _describe(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "median": None, "p90": None}
    values = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
        "p90": values[min(len(values) - 1, math.ceil(0.9 * len(values)) - 1)],
    }


def _rate(flags: list[bool]) -> dict[str, Any]:
    k, n = sum(flags), len(flags)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [lo, hi]}


def load_rows(experiment_id: str, registry: RunRegistry | None = None) -> list[dict[str, Any]]:
    """Raw per-run rows with grading and guardrail counts (one row per trial)."""
    registry = registry or get_registry()
    rows = []
    for r in registry.list_runs(experiment_id=experiment_id, limit=100_000):
        g = r.get("grading") or {}
        result = registry.get_run(r["run_id"])
        guards = result.guardrail_events if result else []
        timeouts = bool(g.get("hidden", {}).get("timed_out")) or any("time budget" in e for e in (result.errors if result else []))
        rows.append({
            **r,
            "model_condition": g.get("model_condition") or f"{r['provider']}:{r['model']}",
            "task_success": bool(g.get("task_success")),
            "hidden_pass_rate": g.get("hidden_pass_rate"),
            "regression": bool(g.get("regression")),
            "category": g.get("category"),
            "guard_blocked": sum(1 for e in guards if e.get("decision") == "blocked"),
            "guard_flagged": sum(1 for e in guards if e.get("decision") == "flagged"),
            "run_config": r.get("run_config") or (result.config if result else {}) or {},
            "timed_out": timeouts,
            "agent_metrics": result.agent_metrics if result else {},
        })
    return rows


def _condition_key(r: dict[str, Any]) -> tuple[str, str, str]:
    return r["architecture"], r["prompt_variant"] or "baseline", r["model_condition"]


# Experimental variables: differences in these are what a comparison is about.
EXPERIMENTAL = {"architecture": "architecture", "prompts.variant": "prompt variant", "model.model": "model",
                "model.provider": "provider"}
_IGNORED = {"benchmark.task_id", "benchmark.content_hash"}  # tasks differ by design (compared within a task set)


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def config_differences(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]] | None = None) -> dict[str, list]:
    """Non-experimental settings that take more than one value across the given runs (key → sorted values)."""
    pool = list(rows_a) + list(rows_b or [])
    values: dict[str, set] = defaultdict(set)
    missing = 0
    for r in pool:
        cfg = _flatten(r.get("run_config") or {})
        if not cfg:
            missing += 1
            continue
        for k, v in cfg.items():
            if k not in EXPERIMENTAL and k not in _IGNORED and not k.startswith("prompts.agents."):
                values[k].add(json.dumps(v, sort_keys=True, default=str))
        # prompt texts: compare the content version, not the variant name
    diffs = {k: sorted(v) for k, v in values.items() if len(v) > 1}
    versions = {r.get("prompt_version") for r in pool if r.get("prompt_version")}
    variants = {r.get("prompt_variant") for r in pool}
    if len(versions) > len(variants):  # same variant name, different prompt texts
        diffs["prompts.version (same variant, different texts)"] = sorted(versions)
    if missing and missing < len(pool):
        diffs["run_config"] = [f"{missing} run(s) predate configuration fingerprints"]
    elif missing and missing == len(pool) and len(pool) > 1:
        diffs["run_config"] = ["configuration unknown: runs predate fingerprints, comparability cannot be checked"]
    return diffs


def _warnings_for(diffs: dict[str, list], what: str) -> list[str]:
    return [f"{what}: '{k}' differs ({', '.join(map(str, v[:4]))})" for k, v in diffs.items()]


def summarise_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[_condition_key(r)].append(r)

    conditions = []
    for (arch, variant, model), rs in sorted(groups.items()):
        with_usage = [r for r in rs if r["usage_available"]]
        with_cost = [r for r in rs if r["estimated_cost_usd"] is not None]
        by_task: dict[str, list[bool]] = defaultdict(list)
        for r in rs:
            by_task[r["task_id"]].append(r["task_success"])
        repeated = {t: v for t, v in by_task.items() if len(v) > 1}
        agent_time: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            for agent, m in (r["agent_metrics"] or {}).items():
                agent_time[agent].append(m.get("duration_ms", 0.0))
        total_agent_time = sum(sum(v) for v in agent_time.values()) or 1.0
        inner = config_differences(rs)
        conditions.append({
            "architecture": arch, "prompt_variant": variant, "model": model, "runs": len(rs),
            "prompt_versions": sorted({r.get("prompt_version") or "unknown" for r in rs}),
            "config_fingerprints": sorted({r.get("config_fingerprint") or "none (pre-fingerprint run)" for r in rs}),
            "comparable": not inner,
            "warnings": _warnings_for(inner, "runs in this condition"),
            "task_success": _rate([r["task_success"] for r in rs]),
            "verified_claimed": _rate([bool(r["verified"]) for r in rs]),
            "verifier_false_positive": _rate([bool(r["verified"]) and not r["task_success"] for r in rs]),
            "regression": _rate([r["regression"] for r in rs]),
            "run_failed": _rate([r["status"] == "failed" for r in rs]),
            "timeouts": _rate([r["timed_out"] for r in rs]),
            "hidden_pass_rate": _describe([r["hidden_pass_rate"] for r in rs if r["hidden_pass_rate"] is not None]),
            "latency_ms": _describe([r["duration_ms"] for r in rs]),
            "debug_iterations": _describe([r["debug_iterations"] for r in rs]),
            "agent_invocations": _describe([r["agent_invocations"] for r in rs]),
            "llm_calls": _describe([r["llm_calls"] for r in rs]),
            "tool_calls": _describe([r["tool_calls"] for r in rs]),
            "total_tokens": {**_describe([r["total_tokens"] for r in with_usage]), "runs_with_usage": len(with_usage)},
            "estimated_cost_usd": {**_describe([r["estimated_cost_usd"] for r in with_cost]),
                                   "total": sum(r["estimated_cost_usd"] for r in with_cost),
                                   "runs_with_cost": len(with_cost), "label": "estimate (configured prices)"},
            "guardrails": {"blocked_total": sum(r["guard_blocked"] for r in rs),
                           "flagged_total": sum(r["guard_flagged"] for r in rs)},
            "repeatability": {
                "tasks_with_repeats": len(repeated),
                "consistent_tasks": sum(1 for v in repeated.values() if len(set(v)) == 1),
                "per_task_success_sd": _describe([statistics.pstdev([float(x) for x in v]) for v in repeated.values()]),
            },
            "agent_time_share": {a: sum(v) / total_agent_time for a, v in sorted(agent_time.items())},
        })

    comparisons = []
    by_rest: dict[tuple, dict[str, list[dict]]] = defaultdict(dict)
    for (arch, variant, model), rs in groups.items():
        by_rest[(variant, model)][arch] = rs
    for (variant, model), archs in sorted(by_rest.items()):
        names = sorted(archs)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                sa = sum(r["task_success"] for r in archs[a])
                sb = sum(r["task_success"] for r in archs[b])
                diffs = config_differences(archs[a], archs[b])
                comparisons.append({"prompt_variant": variant, "model": model, "a": a, "b": b,
                                    "success_diff_a_minus_b": newcombe_diff(sa, len(archs[a]), sb, len(archs[b])),
                                    "comparable": not diffs,
                                    "warnings": _warnings_for(diffs, f"{a} vs {b}")})
    prompt_comparisons = []
    by_arch_model: dict[tuple, dict[str, list[dict]]] = defaultdict(dict)
    for (arch, variant, model), rs in groups.items():
        by_arch_model[(arch, model)][variant] = rs
    for (arch, model), variants in sorted(by_arch_model.items()):
        names = sorted(variants)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                sa = sum(r["task_success"] for r in variants[a])
                sb = sum(r["task_success"] for r in variants[b])
                diffs = config_differences(variants[a], variants[b])
                prompt_comparisons.append({"architecture": arch, "model": model, "a": a, "b": b,
                                           "success_diff_a_minus_b": newcombe_diff(sa, len(variants[a]),
                                                                                   sb, len(variants[b])),
                                           "comparable": not diffs,
                                           "warnings": _warnings_for(diffs, f"{a} vs {b}")})
    warnings = sorted({w for c in conditions for w in c["warnings"]}
                      | {w for c in comparisons + prompt_comparisons for w in c["warnings"]})
    return {"conditions": conditions, "architecture_comparisons": comparisons,
            "prompt_comparisons": prompt_comparisons, "total_runs": len(rows),
            "comparable": not warnings, "warnings": warnings,
            "aggregation_note": "Aggregates are computed on demand from the stored raw runs; raw rows are never "
                                "modified."}


def summarise_experiment(experiment_id: str, registry: RunRegistry | None = None) -> dict[str, Any]:
    registry = registry or get_registry()
    return {"experiment": registry.get_experiment(experiment_id),
            **summarise_rows(load_rows(experiment_id, registry))}


RAW_COLUMNS = [
    "run_id", "experiment_id", "task_id", "category", "repeat_index", "architecture", "prompt_variant",
    "prompt_version", "model_condition", "execution_mode", "status", "task_success", "hidden_pass_rate",
    "regression", "verified", "tests_passed", "debug_iterations", "test_attempts", "duration_ms",
    "agent_invocations", "llm_calls", "tool_calls", "usage_available", "input_tokens", "output_tokens",
    "total_tokens", "estimated_cost_usd", "cost_basis", "guard_blocked", "guard_flagged", "timed_out",
    "trace_id", "started_at",
]


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=RAW_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _tokens_cell(tok: dict[str, Any]) -> str:
    """Mean tokens over runs that reported usage; n/a (never 0) when none did."""
    if not tok["runs_with_usage"]:
        return "n/a (0 runs with usage)"
    return f"{tok['mean']:.0f} ({tok['runs_with_usage']} runs)"


def summary_markdown(summary: dict[str, Any]) -> str:
    def pct(x):
        return "n/a" if x is None else f"{100 * x:.1f}%"

    lines = ["| Architecture | Prompt | Model | Runs | Task success (95% CI) | Hidden pass | Regression |"
             " Latency mean (s) | Debug iters | Tokens (runs) | Est. cost total |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in summary["conditions"]:
        ts = c["task_success"]
        lo, hi = ts["ci95"]
        tok = c["total_tokens"]
        lines.append(
            f"| {c['architecture']} | {c['prompt_variant']} | {c['model']} | {c['runs']} | "
            f"{ts['k']}/{ts['n']} = {pct(ts['rate'])} [{pct(lo)}, {pct(hi)}] | "
            f"{pct(c['hidden_pass_rate']['mean'])} | {pct(c['regression']['rate'])} | "
            f"{(c['latency_ms']['mean'] or 0) / 1000:.1f} | {c['debug_iterations']['mean'] or 0:.2f} | "
            f"{_tokens_cell(tok)} | "
            f"{'$%.4f' % c['estimated_cost_usd']['total'] if c['estimated_cost_usd']['runs_with_cost'] else 'n/a'} |")
    return "\n".join(lines) + "\n"


def experiment_report_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Experiment-level report: configuration, environment, results, comparisons, per-run index."""
    exp = summary.get("experiment") or {}
    cfg = exp.get("config") or {}

    def pct(x):
        return "n/a" if x is None else f"{100 * x:.1f}%"

    lines = [
        f"# VEXA experiment report: {exp.get('name')}", "",
        f"- Experiment id: `{exp.get('experiment_id')}`",
        f"- Status: **{exp.get('status')}** ({exp.get('completed_trials')}/{exp.get('total_trials')} trials,"
        f" {exp.get('failed_trials') or 0} failed runs){' · ' + exp['error'] if exp.get('error') else ''}",
        f"- Mode: {cfg.get('execution_mode')} · tasks: {cfg.get('tasks')} · repeats: {cfg.get('repeats')}"
        f" · seed: {cfg.get('seed')}",
        f"- Architectures: {cfg.get('architectures')} · prompt variants: {cfg.get('prompt_variants')}",
        f"- Tools: {cfg.get('tool_transport')} · verifier: {cfg.get('verifier_backend')}",
        f"- Environment: {exp.get('environment', {}).get('packages')} · config hash"
        f" `{exp.get('environment', {}).get('config_hash')}`",
        "", "## Results by condition", "", summary_markdown(summary),
    ]
    for title, key in (("Architecture comparisons", "architecture_comparisons"),
                       ("Prompt-strategy comparisons", "prompt_comparisons")):
        comps = summary.get(key) or []
        if comps:
            lines += [f"## {title} (task success difference, Newcombe 95% CI)", ""]
            for c in comps:
                d = c["success_diff_a_minus_b"]
                lines.append(f"- {c['a']} − {c['b']}: {pct(d['diff'])} [{pct(d['low'])}, {pct(d['high'])}]")
            lines.append("")
    lines += ["## Runs", "", "| Run | Task | Architecture | Prompt | Status | Task success | Hidden pass | Duration (s) |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| `{r['run_id'][:8]}` | {r['task_id']} | {r['architecture']} | {r['prompt_variant']} | {r['status']} |"
                     f" {r['task_success']} | {pct(r['hidden_pass_rate'])} | {r['duration_ms'] / 1000:.1f} |")
    lines += ["", "Per-run reports: `GET /agent-runs/<run_id>/report?format=md`. "
              "Unavailable measurements are shown as n/a, never as zero."]
    return "\n".join(lines) + "\n"
