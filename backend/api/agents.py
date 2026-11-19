"""
VEXA API — agent anatomy (VEXA Studio "Agents").

GET /agents                       every agent of the runtime with a short summary
GET /agents/{name}                full profile: overview, internal architecture (each stage linked to
                                  its source), tools and permissions, guardrail checkpoints, history
GET /agents/{name}/prompt         the agent's prompt texts for a prompt variant

Nothing here is hand-written metadata about agent *behaviour*: roles and goals come from the prompt
set, inputs from the runtime step signatures and the blackboard's declared reads, outputs from the
Pydantic schemas, permissions from guardrails.TOOL_POLICY, tool definitions from the MCP server
modules (parsed with ast, no server is started) and history from the run registry. Execution
history is reported separately for mock (scripted) and real runs.
"""

from __future__ import annotations

import ast
import inspect
import statistics
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.api.source import REPO_ROOT, find_line, source_ref

router = APIRouter(prefix="/agents", tags=["agents"])

# The wiring of each agent in the runtime (names of real functions/classes; resolved and linked below).
_WIRING: dict[str, dict[str, Any]] = {
    "RequirementAnalyst": {"prompt": "REQUIREMENT_ANALYST", "step": "analyze_requirements", "runner": "_run_requirement_analyst",
                           "parser": "parse_requirement_analysis", "contract": "RequirementAnalysis", "writes": "requirement_analysis"},
    "ProjectAnalyst": {"prompt": "PROJECT_ANALYST", "step": "analyze_project", "runner": "_run_project_analyst",
                       "parser": "parse_project_analysis", "contract": "ProjectAnalysis", "writes": "project_analysis"},
    "Planner": {"prompt": "PLANNER", "step": "plan", "runner": "_run_planner",
                "parser": "parse_implementation_plan", "contract": "ImplementationPlan", "writes": "implementation_plan"},
    "Coder": {"prompt": "CODER", "step": "code", "runner": "_run_coder",
              "parser": "parse_coding_result", "contract": "CodingResult", "writes": "code_changes"},
    "Tester": {"prompt": "TESTER", "step": "test", "runner": "_run_tester",
               "parser": "parse_test_result", "contract": "AgentTestResult", "writes": "test_result"},
    "Debugger": {"prompt": "DEBUGGER", "step": "debug", "runner": "_run_debugger",
                 "parser": "parse_debug_result", "contract": "DebugIteration", "writes": "debug_report"},
    "Verifier": {"prompt": "VERIFIER", "step": "verify", "runner": "_run_verifier",
                 "parser": "parse_verification_result", "contract": "VerificationResult", "writes": "verification",
                 "remote": "_run_remote_verifier"},
    "Manager": {"prompt": "MANAGER", "step": "manager_decide", "runner": "manager_decide",
                "parser": None, "contract": "ManagerDecision", "writes": None, "architectures": ["hierarchical"]},
}

_WRITE_TOOLS = {"write_file", "patch_file"}
_MCP_MODULES = {
    "vexa-workspace": "backend/mcp_servers/workspace_server.py",
    "vexa-code-intel": "backend/mcp_servers/code_intel_server.py",
    "vexa-docs-search": "backend/mcp_servers/docs_search_server.py",
}


def _crew_attr(name: str) -> Any:
    from backend.agents import crew

    return getattr(crew.SoftwareEngineeringCrew, name, None) or getattr(crew, name, None)


def _contract(name: str) -> Any:
    from backend.agents import contracts, schemas

    return getattr(contracts, name, None) or getattr(schemas, name, None)


# ---------------------------------------------------------------- tool catalog (static, from code)

@lru_cache(maxsize=1)
def tool_catalog() -> dict[str, dict[str, Any]]:
    """Every agent tool: MCP definition (parsed from the server modules) + direct tool class + G9 schema."""
    from backend.agents import tools as direct_tools
    from backend.guardrails import TOOL_ARG_SCHEMAS

    catalog: dict[str, dict[str, Any]] = {}
    for server, rel in _MCP_MODULES.items():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            deco = next((d for d in node.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"), None)
            if deco is None:
                continue
            annotations = next((ast.unparse(k.value) for k in deco.keywords if k.arg == "annotations"), "")
            params = []
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
            for a, d in zip(node.args.args, defaults):
                params.append({"name": a.arg, "type": ast.unparse(a.annotation) if a.annotation else None,
                               "default": ast.unparse(d) if d is not None else None, "required": d is None})
            catalog[node.name] = {
                "name": node.name, "mcp_server": server, "description": (ast.get_docstring(node) or "").strip(),
                "parameters": params, "read_only": "read_only" in annotations or "readOnlyHint=True" in annotations,
                "source": {"path": rel, "line": node.lineno},
            }
    for _, cls in inspect.getmembers(direct_tools, inspect.isclass):
        tname = getattr(cls, "name", None)
        if isinstance(tname, str) and cls.__module__ == direct_tools.__name__:
            entry = catalog.setdefault(tname, {"name": tname, "mcp_server": None, "parameters": [], "read_only": None})
            entry["direct_description"] = getattr(cls, "description", "")
            entry["direct_source"] = source_ref(cls)
            if not entry.get("description"):
                entry["description"] = getattr(cls, "description", "")
    for tname, schema in TOOL_ARG_SCHEMAS.items():
        entry = catalog.setdefault(tname, {"name": tname, "mcp_server": None, "parameters": [], "read_only": None, "description": ""})
        entry["argument_schema"] = schema.model_json_schema()
        entry["argument_schema_source"] = source_ref(schema)
    return catalog


# ---------------------------------------------------------------- static anatomy

def _signature(fn: Any) -> list[dict[str, Any]]:
    if fn is None:
        return []
    out = []
    for p in inspect.signature(fn).parameters.values():
        if p.name in ("self", "ctx", "kit"):
            continue
        ann = p.annotation
        out.append({"name": p.name, "type": getattr(ann, "__name__", None) or (str(ann) if ann is not inspect._empty else None)})
    return out


def _blackboard_reads() -> dict[str, list[str]]:
    from backend.orchestration.blackboard import DEFAULT_KNOWLEDGE_SOURCES

    return {ks.name: list(ks.reads) for ks in DEFAULT_KNOWLEDGE_SOURCES}


def _guardrail_checkpoints(name: str, tools: list[str], has_schema: bool) -> list[dict[str, str]]:
    """Which G-rules can fire for this agent, derived from its permissions and output schema."""
    from backend.guardrails import RULES, STAGES

    rules: list[str] = ["run_time_budget", "run_token_budget"]
    if tools:
        rules += ["tool_authorization", "tool_budget", "tool_arguments", "secret_egress", "credential_file",
                  "tool_result", "tool_output"]
    if _WRITE_TOOLS & set(tools):
        rules += ["secret_write", "risky_code"]
    if "search_docs" in tools:
        rules += ["tainted_egress"]
    if has_schema:
        rules.append("output_schema")
    if name == "Verifier":
        rules.append("acceptance_check")
    if name == "ProjectAnalyst" or "read_file" in tools:
        rules.append("repo_content")
    seen, out = set(), []
    for r in rules:
        if r in RULES and r not in seen:
            seen.add(r)
            gid, label = RULES[r]
            out.append({"rule": r, "id": gid, "name": label, "stage": STAGES.get(r, "")})
    return out


def _anatomy(name: str) -> list[dict[str, Any]]:
    w = _WIRING[name]
    p = w["prompt"]
    stages: list[dict[str, Any]] = [
        {"stage": "Dispatch by the architecture", "detail": "The orchestration architecture decides when this agent runs and passes it the public step's arguments.",
         "source": source_ref(_crew_attr(w["step"]))},
        {"stage": "Agent initialisation", "detail": "A CrewAI Agent is built with the role, goal and backstory of the active prompt variant and the tools its policy allows.",
         "source": source_ref(_crew_attr("_make_agent"))},
        {"stage": "Prompt construction", "detail": f"{p}_TASK is formatted with the inputs; the variant transform (react / few_shot / minimal_persona) is applied first.",
         "source": find_line("backend/agents/prompts.py", rf"^{p}_TASK\s*=")},
        {"stage": "Task creation", "detail": "A single-agent CrewAI Task; in real mode it carries the output-schema guardrail (G8) with bounded re-prompting. A manager brief is appended in hierarchical runs.",
         "source": source_ref(_crew_attr("_make_task"))},
        {"stage": "Agent runner", "detail": "Records start/completion, runs the crew and converts errors into a failed structured result.",
         "source": source_ref(_crew_attr(w["runner"]))},
        {"stage": "LLM interaction", "detail": "Runs the single-agent crew; token budget (G7) is checked first, usage is accumulated per agent.",
         "source": source_ref(_crew_attr("_run_single_agent_crew"))},
    ]
    if name not in ("RequirementAnalyst", "Manager"):
        stages.append({"stage": "Tool selection and execution", "detail": "Tools are offered over MCP or in-process; every call passes the guardrail gate (G2 policy, G3 budget, G9 arguments, G4 egress) before it runs and G10/G6 after.",
                       "source": source_ref(_import("backend.guardrails", "enforce_tool_call"))})
    if w.get("remote"):
        stages.append({"stage": "Remote verification over A2A", "detail": "With the ADK verifier backend the verification runs in a Google ADK agent behind an A2A server; telemetry is merged back into the trace.",
                       "source": source_ref(_crew_attr(w["remote"]))})
    if w["parser"]:
        stages.append({"stage": "Output parsing", "detail": "The raw answer is extracted as JSON and mapped onto the structured contract; invalid output is recorded, never silently defaulted.",
                       "source": source_ref(_crew_attr(w["parser"]))})
    stages.append({"stage": "Pydantic validation", "detail": "The answer is validated against the agent's output schema; validation errors are fed back to the model up to VEXA_OUTPUT_VALIDATION_RETRIES times.",
                   "source": source_ref(_import("backend.agents.schemas", "make_guardrail"))})
    if w["writes"]:
        stages.append({"stage": "State update", "detail": f"The result is published to shared state as '{w['writes']}' with author and provenance (derived_from).",
                       "source": source_ref(_crew_attr("_publish"))})
    stages.append({"stage": "Final result", "detail": f"Structured result: {w['contract']}.", "source": source_ref(_contract(w["contract"]))})
    return stages


def _import(module: str, attr: str) -> Any:
    import importlib

    return getattr(importlib.import_module(module), attr, None)


def _static_profile(name: str) -> dict[str, Any]:
    from backend.agents.prompt_variants import get_prompt_set
    from backend.agents.schemas import AGENT_OUTPUT_SCHEMAS, ManagerDecision
    from backend.guardrails import TOOL_POLICY

    w = _WIRING[name]
    prompts = get_prompt_set("baseline")
    tools = sorted(t for t in TOOL_POLICY.get(name, frozenset()) if not t.startswith("a2a:"))
    a2a = sorted(t for t in TOOL_POLICY.get(name, frozenset()) if t.startswith("a2a:"))
    schema_cls = AGENT_OUTPUT_SCHEMAS.get(name) or (ManagerDecision if name == "Manager" else None)
    reads = _blackboard_reads().get(name)
    catalog = tool_catalog()
    producers = {v["writes"]: k for k, v in _WIRING.items() if v["writes"]}
    return {
        "name": name,
        "role": getattr(prompts, f"{w['prompt']}_ROLE", None),
        "goal": getattr(prompts, f"{w['prompt']}_GOAL", None),
        "architectures": w.get("architectures", ["sequential", "hierarchical", "event_driven", "blackboard"]),
        "framework": "Google ADK over A2A (default) or CrewAI — set per run (verifier_backend)" if name == "Verifier" else "CrewAI",
        "prompt_reference": {"key": w["prompt"], "parts": ["ROLE", "GOAL", "BACKSTORY", "TASK"],
                             "source": find_line("backend/agents/prompts.py", rf"^{w['prompt']}_ROLE\s*="),
                             "variants_source": source_ref(_import("backend.agents.prompt_variants", "get_prompt_set"))},
        "inputs": {"step": w["step"], "parameters": _signature(_crew_attr(w["step"])),
                   "blackboard_reads": reads, "produced_by": {k: producers.get(k) for k in (reads or [])}},
        "output": {"state_key": w["writes"], "contract": w["contract"], "contract_source": source_ref(_contract(w["contract"])),
                   "llm_schema": schema_cls.__name__ if schema_cls else None,
                   "llm_schema_json": schema_cls.model_json_schema() if schema_cls else None,
                   "llm_schema_source": source_ref(schema_cls) if schema_cls else None},
        "permissions": {"tools": tools, "a2a": a2a, "policy_source": find_line("backend/guardrails.py", r"^TOOL_POLICY"),
                        "can_write_files": bool(_WRITE_TOOLS & set(tools)), "can_run_tests": "run_tests" in tools,
                        "network": "search_docs" in tools},
        "tools": [catalog.get(t, {"name": t, "description": "", "parameters": []}) for t in tools],
        "guardrails": _guardrail_checkpoints(name, tools, schema_cls is not None),
        "anatomy": _anatomy(name),
    }


# ---------------------------------------------------------------- history (persisted records only)

def _history(name: str | None = None) -> dict[str, dict[str, Any]]:
    from sqlalchemy import select

    from backend.db.models import AgentRun, Run, Span
    from backend.db.registry import get_registry

    reg = get_registry()
    out: dict[str, dict[str, Any]] = {}
    with reg._session() as s:
        q = select(AgentRun, Run.execution_mode, Run.status, Run.started_at, Run.architecture, Run.model, Run.run_id).join(Run, Run.run_id == AgentRun.run_id)
        if name:
            q = q.where(AgentRun.agent == name)
        rows = s.execute(q).all()
        span_q = select(Span.agent, Span.status, Span.attributes, Span.run_id).where(Span.kind == "tool")
        if name:
            span_q = span_q.where(Span.agent == name)
        spans = s.execute(span_q).all()
        run_ids = {r.run_id for r in rows}
        guards = s.execute(select(Run.run_id, Run.execution_mode, Run.result_json).where(Run.run_id.in_(run_ids))).all() if run_ids else []

    mode_of = {r.run_id: r.execution_mode for r in rows}
    per: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for r in rows:
        per[(r.AgentRun.agent, r.execution_mode)].append(r)

    for (agent, mode), items in per.items():
        not_invoked = sum(1 for i in items if not i.AgentRun.invocations)
        items = [i for i in items if i.AgentRun.invocations]  # a row can exist for an agent that never ran
        if not items:
            out.setdefault(agent, {})[mode] = {"executions": 0, "not_invoked": not_invoked, "invocations": 0, "successful": 0,
                                               "failed": 0, "partial": 0, "recent": [], "tools": {}, "guardrails": {}}
            continue
        ar = [i.AgentRun for i in items]
        inv = sum(a.invocations for a in ar)
        ok = sum(1 for a in ar if a.invocations and a.failures == 0)
        failed = sum(1 for a in ar if a.invocations and a.failures >= a.invocations)
        partial = sum(1 for a in ar if a.invocations and 0 < a.failures < a.invocations)
        durations = [a.duration_ms / a.invocations for a in ar if a.invocations]
        with_tokens = [a for a in ar if (a.input_tokens or a.output_tokens)]
        models = Counter(i.model for i in items if i.model and i.AgentRun.llm_calls)
        entry = {
            "executions": len(ar), "not_invoked": not_invoked, "invocations": inv, "successful": ok, "failed": failed, "partial": partial,
            "definitions": {"successful": "no failed invocation in the run", "failed": "every invocation in the run failed",
                            "partial": "some but not all invocations failed"},
            "avg_duration_ms": statistics.fmean(durations) if durations else None,
            "median_duration_ms": statistics.median(durations) if durations else None,
            "avg_tokens": statistics.fmean([a.input_tokens + a.output_tokens for a in with_tokens]) if with_tokens else None,
            "runs_with_token_usage": len(with_tokens),
            "llm_calls": sum(a.llm_calls for a in ar), "llm_failures": sum(a.llm_failures for a in ar),
            "tool_calls": sum(a.tool_calls for a in ar), "tool_errors": sum(a.tool_errors for a in ar),
            "validation_retries": sum(a.validation_retries for a in ar),
            "error_rate": (sum(a.failures for a in ar) / inv) if inv else None,
            "models": dict(models),
            "recent": [
                {"run_id": i.run_id, "started_at": i.started_at.isoformat() if i.started_at else None, "run_status": i.status,
                 "architecture": i.architecture, "invocations": i.AgentRun.invocations, "failures": i.AgentRun.failures,
                 "duration_ms": i.AgentRun.duration_ms, "tokens": i.AgentRun.input_tokens + i.AgentRun.output_tokens,
                 "tool_calls": i.AgentRun.tool_calls, "validation_retries": i.AgentRun.validation_retries}
                for i in sorted(items, key=lambda x: x.started_at or 0, reverse=True)[:20]
            ],
            "tools": {}, "guardrails": {},
        }
        out.setdefault(agent, {})[mode] = entry

    tools: dict[tuple[str, str], Counter] = defaultdict(Counter)
    tool_err: dict[tuple[str, str], Counter] = defaultdict(Counter)
    transports: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for sp in spans:
        attrs = sp.attributes or {}
        mode = mode_of.get(sp.run_id)
        if not sp.agent or not mode:
            continue
        t = attrs.get("vexa.tool", "?")
        tools[(sp.agent, mode)][t] += 1
        transports[(sp.agent, mode)][attrs.get("vexa.transport", "direct")] += 1
        if str(sp.status).lower() not in ("ok", "unset"):
            tool_err[(sp.agent, mode)][t] += 1

    blocked: dict[tuple[str, str], Counter] = defaultdict(Counter)
    decisions: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for g in guards:
        for ev in (g.result_json or {}).get("guardrail_events", []) or []:
            agent = ev.get("agent")
            if not agent or (name and agent != name):
                continue
            decisions[(agent, g.execution_mode)][f"{ev.get('rule')} {ev.get('decision')}"] += 1
            if ev.get("decision") == "blocked" and ev.get("tool"):
                blocked[(agent, g.execution_mode)][ev["tool"]] += 1

    for (agent, mode), c in tools.items():
        if agent in out and mode in out[agent]:
            out[agent][mode]["tools"] = {t: {"calls": n, "errors": tool_err[(agent, mode)][t], "blocked": blocked[(agent, mode)][t]}
                                         for t, n in c.most_common()}
            out[agent][mode]["transports"] = dict(transports[(agent, mode)])
    for (agent, mode), c in decisions.items():
        if agent in out and mode in out[agent]:
            out[agent][mode]["guardrails"] = dict(c.most_common())
    return out


# ---------------------------------------------------------------- endpoints

def _check(name: str) -> None:
    if name not in _WIRING:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown agent '{name}'. Agents: {list(_WIRING)}")


@router.get("")
def list_agents() -> list[dict]:
    from backend.guardrails import TOOL_POLICY

    hist = _history()
    out = []
    for name, w in _WIRING.items():
        h = hist.get(name, {})
        prof = _static_profile(name)
        out.append({
            "name": name, "role": prof["role"], "framework": prof["framework"], "architectures": prof["architectures"],
            "tool_count": len(TOOL_POLICY.get(name, ())), "can_write_files": prof["permissions"]["can_write_files"],
            "executions": {m: {"executions": v["executions"], "successful": v["successful"], "failed": v["failed"]} for m, v in h.items()},
        })
    return out


@router.get("/{name}")
def get_agent(name: str) -> dict:
    from backend.agents.config import provider_status

    _check(name)
    prof = _static_profile(name)
    p = provider_status()
    prof["configured_model"] = {"model": p["model"], "provider": p["provider"],
                                "adk_model": p["adk_model"] if name == "Verifier" else None,
                                "note": "server default; a run may override the model"}
    prof["history"] = _history(name).get(name, {})
    return prof


@router.get("/{name}/prompt")
def get_agent_prompt(name: str, variant: str = Query(default="baseline")) -> dict:
    from backend.agents.prompt_variants import PROMPT_VARIANTS, get_prompt_set

    _check(name)
    if variant not in PROMPT_VARIANTS:
        raise HTTPException(status_code=422, detail=f"variant must be one of {list(PROMPT_VARIANTS)}")
    ps = get_prompt_set(variant)
    key = _WIRING[name]["prompt"]
    return {"agent": name, "variant": variant, "variants": list(PROMPT_VARIANTS), "prompt_set_version": ps.version,
            "agent_prompt_version": ps.agent_versions.get(key),
            "parts": {part: getattr(ps, f"{key}_{part}", None) for part in ("ROLE", "GOAL", "BACKSTORY", "TASK")}}


def agent_names() -> list[str]:
    return list(_WIRING)



@router.get("/{name}/prompt-history")
def prompt_history(name: str) -> dict:
    """Versions of this agent's prompt seen in recorded runs (prompt_archive) plus the current code's version."""
    from sqlalchemy import func, select

    from backend.agents.prompt_variants import PROMPT_VARIANTS, get_prompt_set
    from backend.db.models import PromptArchive, Run
    from backend.db.registry import get_registry

    _check(name)
    key = _WIRING[name]["prompt"]
    with get_registry()._session() as s:
        archive = s.execute(select(PromptArchive).order_by(PromptArchive.first_seen)).scalars().all()
        usage = dict(s.execute(select(Run.prompt_version, func.count()).group_by(Run.prompt_version)).all())
    versions = []
    for a in archive:
        parts = {p: a.texts.get(f"{key}_{p}") for p in ("ROLE", "GOAL", "BACKSTORY", "TASK")}
        versions.append({"prompt_set_version": a.version, "variant": a.variant, "agent_version": (a.agent_versions or {}).get(key),
                         "first_seen": a.first_seen.isoformat() if a.first_seen else None, "runs": usage.get(a.version, 0), "parts": parts})
    current = []
    for v in PROMPT_VARIANTS:
        ps = get_prompt_set(v)
        current.append({"variant": v, "prompt_set_version": ps.version, "agent_version": ps.agent_versions.get(key),
                        "archived": any(x["prompt_set_version"] == ps.version for x in versions)})
    distinct = len({x["agent_version"] for x in versions if x["agent_version"]})
    return {"agent": name, "archived_versions": versions, "current_code": current, "distinct_agent_versions_recorded": distinct,
            "note": "A prompt version is archived the first time a run uses it; variants never used in a run are not archived."}
