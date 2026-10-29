"""
VEXA code-intelligence MCP server (stdio, local, no API key).

Tools
-----
``python_api_docs(symbol)``  Documentation and signature of an *installed*
                             Python module, class or function (stdlib or
                             site-packages), e.g. ``pathlib.Path.resolve``.
``check_python(path)``       Static check of one workspace Python file: syntax
                             errors (with line/column), unused imports and
                             names used before any import or definition at
                             module level. The file is parsed with ``ast``;
                             it is never imported or executed.

Trust boundary
--------------
- The server is bound to ONE workspace (command line), like vexa-workspace;
  ``check_python`` reads files through ToolService path checks.
- ``python_api_docs`` imports only modules that resolve to the standard
  library or site-packages and not into the workspace root, so it cannot
  execute workspace or VEXA code; module names are validated (dotted
  identifiers only).
- Output is truncated; there is no network access.

Run manually:
    python -m backend.mcp_servers.code_intel_server --workspace-root workspaces --workspace-id my-ws
"""

from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import importlib.util
import inspect
import os
import re
import site
import sysconfig
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

MAX_DOC_CHARS = 4000
MAX_MEMBERS = 40
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,5}$")


def _inside(path: str | None, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def installed_roots() -> list[Path]:
    paths = {sysconfig.get_paths()[k] for k in ("stdlib", "platstdlib", "purelib", "platlib")}
    paths |= set(site.getsitepackages())
    return [Path(p) for p in paths if p]


def _importable(locations: list[str], forbidden_roots: list[Path], allowed_roots: list[Path]) -> bool:
    if not locations:  # built-in / frozen module
        return True
    return all(any(_inside(loc, r) for r in allowed_roots) and not any(_inside(loc, r) for r in forbidden_roots)
               for loc in locations)


def api_docs(symbol: str, *, forbidden_roots: list[Path], allowed_roots: list[Path] | None = None) -> dict[str, Any]:
    allowed_roots = allowed_roots if allowed_roots is not None else installed_roots()
    symbol = (symbol or "").strip()
    if not _SYMBOL.match(symbol):
        return {"ok": False, "error": "symbol must be a dotted Python name such as 'pathlib.Path.resolve'"}
    parts = symbol.split(".")
    module, attrs = None, []
    for i in range(len(parts), 0, -1):  # longest importable prefix
        name = ".".join(parts[:i])
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            continue
        origin = spec.origin if spec.origin not in (None, "built-in", "frozen") else None
        locations = [loc for loc in [origin, *(spec.submodule_search_locations or [])] if loc]
        if not _importable(locations, forbidden_roots, allowed_roots):
            return {"ok": False, "error": f"'{name}' is not an installed package (project or workspace code); "
                                          "read it with read_file instead"}
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # broken optional dependency etc.
            return {"ok": False, "error": f"could not import '{name}': {type(exc).__name__}"}
        attrs = parts[i:]
        break
    if module is None:
        return {"ok": False, "error": f"no installed module provides '{symbol}'"}
    obj: Any = module
    for a in attrs:
        if a.startswith("__") or not hasattr(obj, a):
            return {"ok": False, "error": f"'{a}' not found on '{getattr(obj, '__name__', symbol)}'"}
        obj = getattr(obj, a)
    try:
        signature = str(inspect.signature(obj)) if callable(obj) else None
    except (TypeError, ValueError):
        signature = None
    members = None
    if inspect.ismodule(obj) or inspect.isclass(obj):
        members = sorted(n for n in dir(obj) if not n.startswith("_"))[:MAX_MEMBERS]
    doc = inspect.getdoc(obj) or ""
    return {
        "ok": True, "operation": "python_api_docs", "symbol": symbol,
        "kind": type(obj).__name__, "signature": signature,
        "module_version": getattr(module, "__version__", None),
        "doc": doc[:MAX_DOC_CHARS], "doc_truncated": len(doc) > MAX_DOC_CHARS, "public_members": members,
    }


def _bound_names(node: ast.AST) -> set[str]:
    """Names bound anywhere in the module (defs, assignments, imports, loops, with, except, comprehensions)."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
            args = n.args if not isinstance(n, ast.ClassDef) else None
            if args:
                for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                    if a is not None:
                        names.add(a.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
        elif isinstance(n, ast.MatchAs) and n.name:
            names.add(n.name)
    return names


def check_source(source: str, path: str = "<string>") -> dict[str, Any]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {"ok": True, "operation": "check_python", "path": path, "valid_syntax": False,
                "errors": [{"line": exc.lineno, "column": exc.offset, "message": exc.msg}], "warnings": []}
    warnings: list[dict[str, Any]] = []
    imported: dict[str, int] = {}
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            if isinstance(n, ast.ImportFrom) and n.module == "__future__":
                continue
            for a in n.names:
                if a.name != "*":
                    imported[(a.asname or a.name).split(".")[0]] = n.lineno
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    loaded |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    exported: set[str] = set()
    for n in tree.body:  # names listed in __all__ count as used
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets):
            if isinstance(n.value, (ast.List, ast.Tuple)):
                exported |= {e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    for name, line in sorted(imported.items(), key=lambda kv: kv[1]):
        if name not in loaded and name not in exported:
            warnings.append({"line": line, "rule": "unused-import", "message": f"'{name}' imported but unused"})
    bound = _bound_names(tree) | set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__builtins__"}
    star = any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree))
    if not star:
        seen: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound and n.id not in seen:
                seen.add(n.id)
                warnings.append({"line": n.lineno, "rule": "undefined-name", "message": f"'{n.id}' is never defined"})
    return {"ok": True, "operation": "check_python", "path": path, "valid_syntax": True, "errors": [],
            "warnings": sorted(warnings, key=lambda w: w["line"])[:50]}


def build_server(workspace_root: str, workspace_id: str) -> FastMCP:
    os.environ["WORKSPACE_ROOT"] = workspace_root
    from backend.tools.service import ToolService

    svc = ToolService(workspace_root=workspace_root)
    if not svc.workspace_exists(workspace_id):
        raise SystemExit(f"workspace '{workspace_id}' does not exist under {workspace_root}")
    forbidden = [Path(workspace_root)]

    mcp = FastMCP("vexa-code-intel",
                  instructions="Local Python code intelligence: installed-package API docs and static file checks.")
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read_only)
    def python_api_docs(symbol: str) -> dict[str, Any]:
        """Docstring, signature and public members of an installed Python module/class/function, e.g. 'json.dumps'."""
        return api_docs(symbol, forbidden_roots=forbidden)

    @mcp.tool(annotations=read_only)
    def check_python(path: str) -> dict[str, Any]:
        """Static check of a workspace .py file: syntax errors, unused imports, undefined names. Never runs it."""
        if not path.endswith(".py"):
            return {"ok": False, "operation": "check_python", "error": "only .py files can be checked"}
        res = svc.read_file(workspace_id, path)
        if not res.success:
            return {"ok": False, "operation": "check_python", "error": res.message}
        return check_source(res.data["content"], path)

    return mcp


def main() -> None:
    p = argparse.ArgumentParser(description="VEXA code-intelligence MCP server (stdio)")
    p.add_argument("--workspace-root", required=True)
    p.add_argument("--workspace-id", required=True)
    a = p.parse_args()
    build_server(a.workspace_root, a.workspace_id).run("stdio")


if __name__ == "__main__":
    main()
