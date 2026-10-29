"""
VEXA Tool Layer — Execution Engine

SandboxExecutor hierarchy:
  SandboxExecutor (abstract base)
  └── LocalSandboxExecutor   — subprocess on the host, workspace-bounded
  └── DockerSandboxExecutor  — throwaway container, no network, resource-capped

The concrete executor is selected by the ``sandbox_backend`` configuration key.
Agents must NEVER execute arbitrary commands. Every executor enforces:

  - an argv-level command policy (not just an executable-name allowlist)
  - cwd = workspace repository directory
  - hard timeout that kills the whole process group / container
  - a scrubbed, allowlisted environment (no host secrets)
  - stdout / stderr capture with a byte limit
  - structured ExecResult return

Threat model and limits
-----------------------
LocalSandboxExecutor runs as the current host user. The command policy blocks
inline code (``python -c``), package installation, git write operations and
pytest flags that load plugins or write outside the workspace. It does NOT stop
code *inside the workspace* (e.g. a test file written by an agent) from doing
anything the host user can do. Use SANDBOX_BACKEND=docker for real isolation.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.tools.models import ExecResult
from backend.tools.workspace import WorkspaceManager, WorkspaceNotFoundError

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Command policy
# ---------------------------------------------------------------------------

_PYTHON_RE = re.compile(r"^python(\d+(\.\d+)?)?(\.exe)?$")

_SIMPLE_EXECUTABLES: frozenset[str] = frozenset({
    "pytest", "pytest.exe",
    "git", "git.exe",
    "ruff", "ruff.exe",
    "mypy", "mypy.exe",
})

# `python -m <module>` is the only permitted python form.
_PYTHON_MODULES: frozenset[str] = frozenset({"pytest", "ruff", "mypy"})

# Read-only git sub-commands.
_GIT_SUBCOMMANDS: frozenset[str] = frozenset({"status", "diff", "log", "rev-parse", "show"})
_GIT_FORBIDDEN_ARG_PREFIXES: tuple[str, ...] = ("--output", "--ext-diff", "--no-index", "--exec", "-c")

# pytest flags that cannot load code or write outside the workspace.
_PYTEST_FLAGS: frozenset[str] = frozenset({
    "-q", "-v", "-vv", "-x", "-s", "-ra", "-rA", "--no-header", "--color=no",
})
_PYTEST_FLAG_PREFIXES: tuple[str, ...] = ("--tb=", "--maxfail=", "--durations=")
_PYTEST_FLAGS_WITH_VALUE: frozenset[str] = frozenset({"-k", "-m"})


def _is_safe_relative(arg: str) -> bool:
    """A positional path argument must be relative and must not climb out."""
    if not arg or arg.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", arg):
        return False
    return ".." not in PurePosixPath(arg.replace("\\", "/")).parts


def check_pytest_args(args: list[str]) -> str | None:
    """Return an error message if any pytest argument is not permitted."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in _PYTEST_FLAGS or a.startswith(_PYTEST_FLAG_PREFIXES):
            i += 1
            continue
        if a in _PYTEST_FLAGS_WITH_VALUE:
            if i + 1 >= len(args):
                return f"pytest flag '{a}' requires a value"
            i += 2
            continue
        if a.startswith("-"):
            return f"pytest argument '{a}' is not permitted"
        if not _is_safe_relative(a):
            return f"pytest path '{a}' must be relative to the workspace"
        i += 1
    return None


def check_command(argv: list[str]) -> str | None:
    """
    Return an error message if the command is not allowed, else None.

    Policy is argv-aware: the executable must be allowlisted AND its arguments
    must match the permitted form for that executable.
    """
    if not argv:
        return "Empty command"
    exe = Path(argv[0]).name.lower()

    if _PYTHON_RE.match(exe):
        if len(argv) < 3 or argv[1] != "-m" or argv[2] not in _PYTHON_MODULES:
            return f"Only 'python -m {{{', '.join(sorted(_PYTHON_MODULES))}}}' is permitted"
        if argv[2] == "pytest":
            return check_pytest_args(argv[3:])
        return None

    if exe not in _SIMPLE_EXECUTABLES:
        return (
            f"Command '{exe}' is not in the permitted executable list. "
            f"Allowed: python -m {sorted(_PYTHON_MODULES)}, {sorted(_SIMPLE_EXECUTABLES)}"
        )

    if exe.startswith("git"):
        if len(argv) < 2 or argv[1] not in _GIT_SUBCOMMANDS:
            return f"Only read-only git sub-commands are permitted: {sorted(_GIT_SUBCOMMANDS)}"
        for a in argv[2:]:
            if a.startswith(_GIT_FORBIDDEN_ARG_PREFIXES):
                return f"git argument '{a}' is not permitted"
        return None

    if exe.startswith("pytest"):
        return check_pytest_args(argv[1:])

    return None


# Kept for backward compatibility with earlier imports.
_check_allowlist = check_command

# ---------------------------------------------------------------------------
# Environment allowlist
# ---------------------------------------------------------------------------

_ENV_ALLOWLIST: frozenset[str] = frozenset({
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",  # Windows essentials
})


def build_sandbox_env(env_extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    Build the subprocess environment from an allowlist.

    Host secrets (API keys, tokens, database URLs) are never inherited because
    nothing outside the allowlist is copied.
    """
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    tmp = tempfile.gettempdir()
    env.update({
        "HOME": tmp,
        "TMPDIR": tmp,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    if env_extra:
        env.update(env_extra)
    return env


def _read_capped(fh, limit: int) -> str:
    fh.seek(0)
    data = fh.read(limit + 1)
    text = data[:limit].decode("utf-8", errors="replace")
    if len(data) > limit:
        text += f"\n[...output truncated at {limit} bytes]"
    return text


def _rejected(reason: str) -> ExecResult:
    return ExecResult(
        success=False,
        operation="exec",
        message=f"Command rejected: {reason}",
        exit_code=None,
        error=reason,
    )


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class SandboxExecutor(ABC):
    """Abstract executor interface. Subclasses differ in isolation level."""

    name: str = "abstract"

    @abstractmethod
    def run(
        self,
        argv: list[str],
        workspace_id: str,
        *,
        timeout: int | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> ExecResult:
        """
        Execute *argv* in the workspace's repository directory.

        Parameters
        ----------
        argv:
            Command + arguments, e.g. ["pytest", "tests/", "-v"]
        workspace_id:
            Workspace identifier. The cwd will be set to its repository dir.
        timeout:
            Seconds before the process is killed. None uses the config default.
        env_extra:
            Additional environment variables (merged with the sanitised env).

        Returns
        -------
        ExecResult with stdout, stderr, exit_code, duration_ms, timed_out.
        """


# ---------------------------------------------------------------------------
# Local implementation
# ---------------------------------------------------------------------------


class LocalSandboxExecutor(SandboxExecutor):
    """
    Runs commands directly on the host using subprocess.

    **Isolation level:** Limited. The process runs as the current user inside
    the workspace directory with an allowlisted environment, its own process
    group (killed as a whole on timeout) and POSIX resource limits
    (CPU seconds, max written file size, address space where the OS honours it).

    For untrusted generated code use DockerSandboxExecutor.
    """

    name = "local"

    def __init__(self, manager: WorkspaceManager) -> None:
        self._mgr = manager
        self._settings = get_settings()

    def _preexec(self, timeout: int):
        if os.name != "posix":
            return None
        mem_bytes = self._settings.tool_max_memory_mb * 1024 * 1024
        fsize_bytes = self._settings.tool_max_file_write_mb * 1024 * 1024

        def _limits() -> None:
            import resource
            for res, val in (
                (resource.RLIMIT_CPU, timeout + 5),
                (resource.RLIMIT_FSIZE, fsize_bytes),
                (resource.RLIMIT_CORE, 0),
                (getattr(resource, "RLIMIT_AS", None), mem_bytes),
            ):
                if res is None:
                    continue
                try:
                    resource.setrlimit(res, (val, val))
                except (ValueError, OSError):
                    pass  # Not supported on this OS (e.g. RLIMIT_AS on macOS)

        return _limits

    def run(
        self,
        argv: list[str],
        workspace_id: str,
        *,
        timeout: int | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> ExecResult:
        deny_reason = check_command(argv)
        if deny_reason:
            return _rejected(deny_reason)

        try:
            cwd = self._mgr.require(workspace_id)
        except WorkspaceNotFoundError as exc:
            return ExecResult(success=False, operation="exec", message=str(exc), exit_code=None, error=str(exc))

        effective_timeout = timeout if timeout is not None else self._settings.tool_exec_timeout_seconds
        half = self._settings.tool_max_output_bytes // 2
        env = build_sandbox_env(env_extra)

        logger.debug("Executing %s | cwd=%s | timeout=%ss", argv, cwd, effective_timeout)

        t0 = time.monotonic()
        timed_out = False
        popen_kwargs: dict = {}
        if os.name == "posix":
            popen_kwargs["process_group"] = 0
            popen_kwargs["preexec_fn"] = self._preexec(effective_timeout)
        else:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        # Output goes to temp files (not pipes) so RLIMIT_FSIZE bounds it and a
        # chatty process cannot exhaust backend memory.
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            try:
                proc = subprocess.Popen(argv, cwd=str(cwd), stdout=out_f, stderr=err_f, env=env, **popen_kwargs)
            except FileNotFoundError as exc:
                return ExecResult(
                    success=False, operation="exec", message=f"Executable not found: {argv[0]}",
                    exit_code=None, error=str(exc), duration_ms=(time.monotonic() - t0) * 1000,
                )
            except Exception as exc:
                return ExecResult(
                    success=False, operation="exec", message=f"Execution failed: {exc}",
                    exit_code=None, error=str(exc), duration_ms=(time.monotonic() - t0) * 1000,
                )
            try:
                exit_code = proc.wait(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_tree(proc)
                proc.wait()
                exit_code = -1

            stdout = _read_capped(out_f, half)
            stderr = _read_capped(err_f, half)

        if timed_out:
            stderr = (stderr + "\n" if stderr else "") + f"Process killed after {effective_timeout}s timeout"

        duration_ms = (time.monotonic() - t0) * 1000
        success = (exit_code == 0) and not timed_out
        return ExecResult(
            success=success,
            operation="exec",
            message="OK" if success else ("Timed out" if timed_out else f"Exit code {exit_code}"),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            if os.name == "posix":
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# Docker implementation
# ---------------------------------------------------------------------------


class DockerSandboxExecutor(SandboxExecutor):
    """
    Runs each command in a throwaway Docker container.

    - workspace repository mounted read-write at /workspace (nothing else)
    - no network, read-only root filesystem, small /tmp tmpfs
    - all Linux capabilities dropped, no-new-privileges
    - memory / CPU / PID limits; container killed on timeout
    - runs as the host user's uid:gid so files stay owned by the user

    The image must contain python and pytest. Build the default one with:
        docker build -t vexa-sandbox:latest -f docker/sandbox.Dockerfile docker
    """

    name = "docker"

    def __init__(self, manager: WorkspaceManager) -> None:
        self._mgr = manager
        self._settings = get_settings()

    def _docker_bin(self) -> str | None:
        configured = self._settings.sandbox_docker_binary
        if os.path.isabs(configured):
            return configured if os.access(configured, os.X_OK) else None
        return shutil.which(configured)

    @staticmethod
    def _container_argv(argv: list[str]) -> list[str]:
        exe = Path(argv[0]).name.lower()
        if _PYTHON_RE.match(exe):
            return ["python", *argv[1:]]
        if exe.startswith("pytest"):
            return ["python", "-m", "pytest", *argv[1:]]
        return [exe.removesuffix(".exe"), *argv[1:]]

    def run(
        self,
        argv: list[str],
        workspace_id: str,
        *,
        timeout: int | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> ExecResult:
        deny_reason = check_command(argv)
        if deny_reason:
            return _rejected(deny_reason)

        try:
            repo = self._mgr.require(workspace_id).resolve()
        except WorkspaceNotFoundError as exc:
            return ExecResult(success=False, operation="exec", message=str(exc), exit_code=None, error=str(exc))

        docker = self._docker_bin()
        if docker is None:
            msg = (
                f"Docker sandbox selected but docker binary '{self._settings.sandbox_docker_binary}' "
                "was not found. Set SANDBOX_DOCKER_BINARY or SANDBOX_BACKEND=local."
            )
            return ExecResult(success=False, operation="exec", message=msg, exit_code=None, error=msg)

        s = self._settings
        effective_timeout = timeout if timeout is not None else s.tool_exec_timeout_seconds
        name = f"vexa-sbx-{uuid.uuid4().hex[:12]}"
        cmd = [
            docker, "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", f"{s.tool_max_memory_mb}m", "--memory-swap", f"{s.tool_max_memory_mb}m",
            "--cpus", str(s.sandbox_docker_cpus),
            "--pids-limit", "256",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONHASHSEED=0",
            "-v", f"{repo}:/workspace:rw", "-w", "/workspace",
        ]
        if hasattr(os, "getuid"):
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for k, v in (env_extra or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [s.sandbox_docker_image, *self._container_argv(argv)]

        half = s.tool_max_output_bytes // 2
        t0 = time.monotonic()
        timed_out = False
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            try:
                proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=build_sandbox_env())
                try:
                    exit_code = proc.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    subprocess.run([docker, "kill", name], capture_output=True, timeout=30)
                    proc.wait(timeout=30)
                    exit_code = -1
            except Exception as exc:
                return ExecResult(
                    success=False, operation="exec", message=f"Docker execution failed: {exc}",
                    exit_code=None, error=str(exc), duration_ms=(time.monotonic() - t0) * 1000,
                )
            stdout = _read_capped(out_f, half)
            stderr = _read_capped(err_f, half)

        if exit_code == 125:  # docker itself failed (daemon down, image missing, ...)
            return ExecResult(
                success=False, operation="exec", message="Docker sandbox could not start the container",
                exit_code=None, stdout=stdout, stderr=stderr, error=stderr.strip()[:500],
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        if timed_out:
            stderr = (stderr + "\n" if stderr else "") + f"Container killed after {effective_timeout}s timeout"

        success = exit_code == 0 and not timed_out
        return ExecResult(
            success=success,
            operation="exec",
            message="OK" if success else ("Timed out" if timed_out else f"Exit code {exit_code}"),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_executor(manager: WorkspaceManager) -> SandboxExecutor:
    """
    Return the configured SandboxExecutor based on SANDBOX_BACKEND.

    There is deliberately no silent fallback: if docker is selected and
    unavailable, executions fail with an explicit error.
    """
    backend = get_settings().sandbox_backend
    if backend == "docker":
        return DockerSandboxExecutor(manager)
    return LocalSandboxExecutor(manager)


__all__ = [
    "SandboxExecutor", "LocalSandboxExecutor", "DockerSandboxExecutor",
    "create_executor", "check_command", "check_pytest_args", "build_sandbox_env", "ExecResult",
]

if sys.version_info < (3, 11):  # process_group= requires 3.11
    raise RuntimeError("VEXA requires Python 3.11+")
