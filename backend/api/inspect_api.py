"""
VEXA API — guardrail inspector and extension (module) catalog for VEXA Studio.

GET /guardrails                        G1–G10: purpose (from the guardrails module docstring), rules, stage,
                                       enforcement type, implementing functions (linked to source), statistics
GET /guardrails/events                 recorded decisions, filterable (rule, decision, agent, run_id, mode)
GET /extensions                        VEXA's modules as inspectable extensions
GET /extensions/{id}                   anatomy: files, classes, functions, endpoints, data models, settings,
                                       internal/external dependencies, dependants, related agents and tests,
                                       entry points with their internal calls, runtime evidence

The category of each extension is a fixed mapping from directories to the capability names used in the
UI; everything listed inside an extension is discovered from the code at request time.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.api.source import REPO_ROOT, find_line, source_ref

router = APIRouter(tags=["inspect"])

# ---------------------------------------------------------------- guardrails

_G: dict[str, dict[str, Any]] = {
    "G1": {"rules": ["requirement_screen"], "impl": [("backend.guardrails", "check_requirement"), ("backend.guardrails", "blocking"), ("backend.guardrails", "needs_review")],
           "enforcement": "heuristic", "enforcement_note": "regex patterns; unambiguous matches are blocked, ambiguous ones need human confirmation"},
    "G2": {"rules": ["tool_authorization"], "impl": [("backend.guardrails", "guard_tool_call"), ("backend.guardrails", "TOOL_POLICY")],
           "enforcement": "deterministic", "enforcement_note": "allow-list per agent role"},
    "G3": {"rules": ["tool_budget"], "impl": [("backend.guardrails", "guard_tool_call")], "enforcement": "deterministic",
           "enforcement_note": "counter per agent invocation"},
    "G4": {"rules": ["secret_write", "secret_egress", "credential_file"], "impl": [("backend.guardrails", "written_secret"), ("backend.guardrails", "guard_tool_call")],
           "enforcement": "deterministic", "enforcement_note": "exact match of registered secrets; credential-file path patterns"},
    "G5": {"rules": ["risky_code"], "impl": [("backend.guardrails", "risky_code")], "enforcement": "heuristic",
           "enforcement_note": "regex patterns; flags only, never blocks"},
    "G6": {"rules": ["tool_output", "repo_content", "injection_classifier", "tainted_egress"],
           "impl": [("backend.guardrails", "detect_injection"), ("backend.guardrails", "spotlight"), ("backend.guardrails", "guard_tool_output"), ("backend.guardrails", "InjectionClassifier")],
           "enforcement": "heuristic", "enforcement_note": "pattern detection and an optional model classifier are signals; spotlighting (delimiting untrusted output) and the taint block on network egress are deterministic"},
    "G7": {"rules": ["run_time_budget", "run_token_budget"], "impl": [("backend.guardrails", "check_run_budget"), ("backend.guardrails", "check_token_budget")],
           "enforcement": "deterministic", "enforcement_note": "wall-clock and token limits checked before dispatch"},
    "G8": {"rules": ["output_schema", "acceptance_check"], "impl": [("backend.agents.schemas", "make_guardrail"), ("backend.agents.crew", "SoftwareEngineeringCrew._check_acceptance")],
           "enforcement": "deterministic", "enforcement_note": "Pydantic validation with bounded re-prompting; acceptance check is recorded, not rewritten"},
    "G9": {"rules": ["tool_arguments"], "impl": [("backend.guardrails", "validate_tool_args"), ("backend.guardrails", "TOOL_ARG_SCHEMAS")],
           "enforcement": "deterministic", "enforcement_note": "strict Pydantic schema per tool"},
    "G10": {"rules": ["tool_result"], "impl": [("backend.guardrails", "validate_tool_result"), ("backend.guardrails", "guard_tool_output")],
            "enforcement": "deterministic", "enforcement_note": "shape and size checks; registered secrets masked"},
}


def _resolve(module: str, dotted: str) -> Any:
    import importlib

    obj: Any = importlib.import_module(module)
    for part in dotted.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _impl_ref(module: str, dotted: str) -> dict[str, Any]:
    obj = _resolve(module, dotted)
    ref = source_ref(obj) if obj is not None and (callable(obj) and not isinstance(obj, dict)) else None
    if ref is None:  # module-level constants (TOOL_POLICY, TOOL_ARG_SCHEMAS)
        ref = find_line(module.replace(".", "/") + ".py", rf"^{re.escape(dotted)}\b")
    return {"name": f"{module}.{dotted}", "source": ref}


def _docstring_sections() -> dict[str, str]:
    import backend.guardrails as g

    doc = g.__doc__ or ""
    block = doc.split("Guards (each is logged as a guardrail event on the run)")[-1].split("Limits (honest)")[0]
    out: dict[str, list[str]] = defaultdict(list)
    current = None
    for line in block.splitlines():
        m = re.match(r"^(G\d+)\s+(.*)$", line)
        if m:
            current = m.group(1)
            out[current].append(m.group(2).strip())
        elif current and line.strip() and not line.startswith("-"):
            out[current].append(line.strip())
    return {k: re.sub(r"\s+", " ", " ".join(v)) for k, v in out.items()}


def _events(mode: str | None = None) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from backend.db.models import Run
    from backend.db.registry import get_registry

    out = []
    with get_registry()._session() as s:
        q = select(Run.run_id, Run.execution_mode, Run.result_json, Run.started_at)
        if mode:
            q = q.where(Run.execution_mode == mode)
        for rid, m, res, started in s.execute(q):
            for ev in (res or {}).get("guardrail_events") or []:
                out.append({**ev, "run_id": rid, "mode": m, "run_started_at": started.isoformat() if started else None})
    return out


@router.get("/guardrails")
def guardrails() -> dict:
    import backend.guardrails as g

    docs = _docstring_sections()
    events = _events()
    out = []
    for gid, spec in _G.items():
        mine = [e for e in events if e.get("rule") == gid]
        stats = {}
        for mode in ("real", "mock"):
            m = [e for e in mine if e["mode"] == mode]
            by_day: dict[str, Counter] = defaultdict(Counter)
            for e in m:
                by_day[(e.get("at") or e.get("run_started_at") or "")[:10]][e.get("decision")] += 1
            stats[mode] = {
                "total": len(m), "decisions": dict(Counter(e.get("decision") for e in m)),
                "retries": sum(1 for e in m if e.get("action") == "retry"),
                "not_evaluated": sum(1 for e in m if e.get("decision") == "indeterminate"),
                "by_rule": dict(Counter(e.get("kind") for e in m)),
                "agents": dict(Counter(e.get("agent") or "runtime" for e in m)),
                "trend": [{"date": d, **dict(c)} for d, c in sorted(by_day.items())],
            }
        out.append({
            "id": gid, "name": g.RULES[spec["rules"][0]][1] if spec["rules"][0] in g.RULES else gid,
            "purpose": docs.get(gid, ""),
            "rules": [{"kind": r, "name": g.RULES.get(r, (gid, r))[1], "stage": g.STAGES.get(r)} for r in spec["rules"]],
            "stages": sorted({g.STAGES.get(r) for r in spec["rules"] if g.STAGES.get(r)}),
            "enforcement": spec["enforcement"], "enforcement_note": spec["enforcement_note"],
            "implementation": [_impl_ref(m_, f) for m_, f in spec["impl"]],
            "stats": stats,
        })
    return {"version": g.GUARDRAILS_VERSION, "module": "backend/guardrails.py",
            "limits": re.sub(r"\s+", " ", re.sub(r"^-+\s*", "", (g.__doc__ or "").split("Limits (honest)")[-1].strip())).strip(),
            "decision_meaning": g.STATUS, "guardrails": out}


@router.get("/guardrails/events")
def guardrail_events(rule: str | None = None, decision: str | None = None, agent: str | None = None, run_id: str | None = None,
                     mode: str | None = Query(default=None, pattern="^(real|mock)$"), limit: int = Query(default=200, ge=1, le=2000)) -> dict:
    ev = _events(mode)
    if rule:
        ev = [e for e in ev if e.get("rule") == rule]
    if decision:
        ev = [e for e in ev if e.get("decision") == decision]
    if agent:
        ev = [e for e in ev if (e.get("agent") or "runtime") == agent]
    if run_id:
        ev = [e for e in ev if e["run_id"] == run_id]
    ev.sort(key=lambda e: e.get("at") or "", reverse=True)
    return {"total": len(ev), "events": ev[:limit]}


# ---------------------------------------------------------------- extensions

_EXTENSIONS: list[dict[str, Any]] = [
    {"id": "orchestration", "name": "Agent Orchestration", "paths": ["backend/orchestration"]},
    {"id": "agent-runtime", "name": "Agent Runtime (CrewAI)", "paths": ["backend/agents"]},
    {"id": "llm-providers", "name": "LLM Provider Integration", "paths": ["backend/agents/config.py"]},
    {"id": "mcp-servers", "name": "MCP Tool Servers", "paths": ["backend/mcp_servers"]},
    {"id": "mcp-client", "name": "MCP Client Bridge", "paths": ["backend/mcp_client"]},
    {"id": "a2a", "name": "A2A Integration", "paths": ["backend/a2a_bridge"]},
    {"id": "adk-verifier", "name": "Google ADK Verifier", "paths": ["backend/adk_agents"]},
    {"id": "guardrails", "name": "Guardrail Engine", "paths": ["backend/guardrails.py"]},
    {"id": "tools", "name": "Repository Intelligence & Tool Layer", "paths": ["backend/tools"]},
    {"id": "testing-engine", "name": "Testing Engine (sandbox)", "paths": ["backend/tools/execution.py"]},
    {"id": "evaluation", "name": "Benchmark & Experiment Engine", "paths": ["backend/evaluation"]},
    {"id": "observability", "name": "Observability", "paths": ["backend/observability"]},
    {"id": "persistence", "name": "Run Registry (persistence)", "paths": ["backend/db"]},
    {"id": "api", "name": "HTTP API", "paths": ["backend/api", "backend/main.py"]},
    {"id": "studio", "name": "VEXA Studio UI", "paths": ["frontend/src/studio"]},
]
_AGENT_NAMES = ("RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Debugger", "Verifier", "Manager")


def _files(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        full = REPO_ROOT / p
        if full.is_file():
            out.append(p)
        elif full.is_dir():
            out += sorted(f.relative_to(REPO_ROOT).as_posix() for f in full.rglob("*")
                          if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".ts", ".tsx", ".css"))
    return out


def _module_name(rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


@lru_cache(maxsize=1)
def _python_index() -> dict[str, dict[str, Any]]:
    """Per Python file in backend/: definitions, imports and calls (ast)."""
    idx: dict[str, dict[str, Any]] = {}
    for f in sorted((REPO_ROOT / "backend").rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        text = f.read_text(encoding="utf-8")
        tree = ast.parse(text)
        classes, functions, models, imports = [], [], [], set()
        external = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases]
                doc = (ast.get_docstring(node) or "").split("\n")[0]
                classes.append({"name": node.name, "line": node.lineno, "bases": bases, "doc": doc})
                if any(b.endswith(("BaseModel", "Base", "_LLMOutput", "AgentResult", "_Args", "DeclarativeBase", "BaseSettings")) for b in bases):
                    models.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({"name": node.name, "line": node.lineno, "doc": (ast.get_docstring(node) or "").split("\n")[0]})
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                (imports if node.module.startswith("backend") else external).add(node.module)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    (imports if a.name.startswith("backend") else external).add(a.name)
        calls: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        fn = sub.func
                        names.add(fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else "")
                calls[node.name] = names - {""}
        settings = sorted(set(re.findall(r"settings\.([a-z_][a-z0-9_]*)", text)))
        idx[rel] = {"classes": classes, "functions": functions, "models": models, "imports": sorted(imports),
                    "external": sorted({e.split(".")[0] for e in external}), "calls": calls, "settings": settings,
                    "agents": sorted(a for a in _AGENT_NAMES if a in text), "lines": text.count("\n") + 1}
    return idx


def _stdlib(name: str) -> bool:
    return name in sys.stdlib_module_names or name == "__future__"


def _owner(module: str) -> str | None:
    """Extension id that owns a dotted backend module (most specific path wins)."""
    rel_candidates = [module.replace(".", "/") + ".py", module.replace(".", "/") + "/__init__.py"]
    best, best_len = None, -1
    for ext in _EXTENSIONS:
        for p in ext["paths"]:
            for rc in rel_candidates:
                if (rc == p or rc.startswith(p.rstrip("/") + "/")) and len(p) > best_len:
                    best, best_len = ext["id"], len(p)
    return best


def _routes_for(files: list[str]) -> list[dict[str, Any]]:
    """Endpoints declared by the APIRouter of each module (route paths already include the prefix)."""
    import importlib

    out = []
    for f in files:
        mod_name = _module_name(f)
        if not mod_name:
            continue
        try:
            router_ = getattr(importlib.import_module(mod_name), "router", None)
        except Exception:
            continue
        for r in getattr(router_, "routes", []) or []:
            ep = getattr(r, "endpoint", None)
            if ep is not None and hasattr(r, "methods"):
                out.append({"path": r.path, "methods": sorted(set(r.methods) - {"HEAD", "OPTIONS"}), "name": ep.__name__,
                            "source": source_ref(ep)})
    return out


def _tests_for(module_names: set[str]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        text = f.read_text(encoding="utf-8")
        hits = sorted(m for m in module_names if re.search(rf"\b{re.escape(m)}\b", text))
        if hits:
            out.append({"path": f.relative_to(REPO_ROOT).as_posix(), "tests": len(re.findall(r"^\s*(?:async )?def test_", text, re.M)), "imports": hits})
    return out


def _runtime_evidence(ext_id: str) -> dict[str, Any] | None:
    """Recorded activity that this module produces (only where the link is direct)."""
    from sqlalchemy import func, select

    from backend.db.models import CoordinationRow, Run, Span
    from backend.db.registry import get_registry

    with get_registry()._session() as s:
        if ext_id == "mcp-client":
            spans = [r for r in s.execute(select(Span.attributes, Span.status, Span.duration_ms).where(Span.kind == "tool")).all()
                     if (r.attributes or {}).get("vexa.transport") == "mcp"]
            return {"label": "tool calls over MCP", "count": len(spans), "errors": sum(str(x.status).lower() not in ("ok", "unset") for x in spans),
                    "avg_ms": (sum(x.duration_ms for x in spans) / len(spans)) if spans else None}
        if ext_id == "a2a":
            n = s.scalar(select(func.count()).select_from(CoordinationRow).where(CoordinationRow.kind == "message", CoordinationRow.actor.like("adk:%"))) or 0
            return {"label": "A2A task messages from the ADK verifier", "count": n}
        if ext_id == "orchestration":
            return {"label": "runs per architecture", "by": dict(s.execute(select(Run.architecture, func.count()).group_by(Run.architecture)).all())}
        if ext_id == "observability":
            return {"label": "persisted spans by kind", "by": dict(s.execute(select(Span.kind, func.count()).group_by(Span.kind)).all())}
        if ext_id == "evaluation":
            return {"label": "graded benchmark runs", "count": s.scalar(select(func.count()).select_from(Run).where(Run.task_id.is_not(None))) or 0}
        if ext_id == "persistence":
            return {"label": "runs in the registry", "count": s.scalar(select(func.count()).select_from(Run)) or 0}
        if ext_id == "testing-engine":
            spans = [r for r in s.execute(select(Span.attributes, Span.status, Span.duration_ms).where(Span.kind == "tool")).all()
                     if (r.attributes or {}).get("vexa.tool") == "run_tests"]
            return {"label": "sandboxed test executions", "count": len(spans),
                    "avg_ms": (sum(x.duration_ms for x in spans) / len(spans)) if spans else None}
        if ext_id == "guardrails":
            return {"label": "recorded guardrail decisions", "count": len(_events())}
    return None


def _summary(ext: dict[str, Any]) -> dict[str, Any]:
    files = _files(ext["paths"])
    idx = _python_index()
    py = [f for f in files if f in idx]
    # purpose: the package docstring (__init__.py) if it has one, else the largest module's docstring
    purpose = ""
    ordered = sorted(py, key=lambda f: (not f.endswith("__init__.py"), -idx[f]["lines"]))
    for f in ordered:
        doc = ast.get_docstring(ast.parse((REPO_ROOT / f).read_text(encoding="utf-8")))
        if doc:
            purpose = doc.strip().split("\n\n")[0].replace("\n", " ")
            break
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode())
        h.update((REPO_ROOT / f).read_bytes())
    mods = {_module_name(f) for f in py} - {None}
    loaded = sum(1 for m in mods if m in sys.modules)
    return {"id": ext["id"], "name": ext["name"], "paths": ext["paths"], "purpose": purpose, "files": len(files),
            "lines": sum(idx[f]["lines"] for f in py) if py else sum((REPO_ROOT / f).read_text(encoding="utf-8").count("\n") + 1 for f in files),
            "version": "c-" + h.hexdigest()[:10],
            "status": ("loaded" if loaded else "not loaded in this process") if py else "frontend (not a backend module)",
            "modules_loaded": f"{loaded}/{len(mods)}" if mods else None}


@router.get("/extensions")
def extensions() -> dict:
    from backend.core.config import get_settings

    return {"vexa_version": get_settings().app_version, "extensions": [_summary(e) for e in _EXTENSIONS],
            "note": "Each extension groups a directory (or file) of the VEXA codebase; contents are discovered from the code."}


@router.get("/extensions/{ext_id}")
def extension(ext_id: str) -> dict:
    ext = next((e for e in _EXTENSIONS if e["id"] == ext_id), None)
    if ext is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown extension '{ext_id}'")
    idx = _python_index()
    files = _files(ext["paths"])
    py = [f for f in files if f in idx]
    mods = {_module_name(f) for f in py} - {None}
    deps, external, agents = Counter(), set(), set()
    for f in py:
        for imp in idx[f]["imports"]:
            owner = _owner(imp)
            if owner and owner != ext_id:
                deps[owner] += 1
        external |= {e for e in idx[f]["external"] if not _stdlib(e) and e != "backend"}
        agents |= set(idx[f]["agents"])
    dependants: Counter = Counter()
    entry_points: dict[str, set[str]] = defaultdict(set)
    for other, info in idx.items():
        if other in py:
            continue
        o_owner = _owner(_module_name(other) or "")
        for imp in info["imports"]:
            if imp in mods and o_owner and o_owner != ext_id:
                dependants[o_owner] += 1
        text = (REPO_ROOT / other).read_text(encoding="utf-8")
        for m in mods:
            for match in re.finditer(rf"from {re.escape(m)} import ([^\n(]+|\([^)]*\))", text):
                for name in re.split(r"[,\s()]+", match.group(1)):
                    if name and name != "as":
                        entry_points[name].add(other)
    defined = {fn["name"]: f for f in py for fn in idx[f]["functions"]} | {c["name"]: f for f in py for c in idx[f]["classes"]}
    flow = []
    for name, users in sorted(entry_points.items()):
        if name not in defined:
            continue
        f = defined[name]
        internal = sorted(c for c in idx[f]["calls"].get(name, set()) if c in defined and c != name)
        line = next((x["line"] for x in idx[f]["functions"] + idx[f]["classes"] if x["name"] == name), None)
        flow.append({"entry": name, "source": {"path": f, "line": line}, "used_by": sorted(users)[:8], "calls": internal})
    summary = _summary(ext)
    return {
        **summary,
        "file_list": [{"path": f, "lines": idx[f]["lines"] if f in idx else None,
                       "classes": idx[f]["classes"] if f in idx else [], "functions": idx[f]["functions"] if f in idx else [],
                       "models": idx[f]["models"] if f in idx else []} for f in files],
        "endpoints": _routes_for(py),
        "data_models": sorted({m for f in py for m in idx[f]["models"]}),
        "settings": sorted({x for f in py for x in idx[f]["settings"]}),
        "depends_on": [{"id": k, "imports": v} for k, v in deps.most_common()],
        "external_dependencies": sorted(external),
        "used_by": [{"id": k, "imports": v} for k, v in dependants.most_common()],
        "related_agents": sorted(agents),
        "execution_flow": flow[:40],
        "tests": _tests_for(mods),
        "runtime_evidence": _runtime_evidence(ext_id),
    }
