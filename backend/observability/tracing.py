"""
Run tracing and provenance.

Each run gets an OpenTelemetry trace:

    run  (vexa.run)
     ├── agent  (vexa.agent: RequirementAnalyst, ...)
     │    ├── llm   (vexa.llm: model, tokens, finish reason)   ← CrewAI LLM events
     │    └── tool  (vexa.tool: write_file, run_tests, ...)    ← VEXA tool adapters
     └── ...

Spans are real OTel SDK spans (W3C trace/span ids). VEXA's TracerProvider has:
- a collecting processor that keeps each run's finished spans in memory so the
  run can be reconstructed and persisted, and
- an OTLP exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. Jaeger/Tempo).

Framework spans (Google ADK's own OpenTelemetry instrumentation) are collected
too: VEXA installs its provider as the global one when none is configured (or
adds its collector to an existing SDK provider), and routes spans without a
``vexa.run_id`` attribute to the run that owns their trace id. The A2A verifier
server continues the caller's trace from the ``traceparent`` header, so ADK's
invoke_agent / call_llm / execute_tool spans become children of the A2A call
span. This only works when the ADK server runs in this process (embedded
mode); an external ADK server keeps the same trace id but exports its spans
from its own process (e.g. via OTLP).

Foreign span attributes are redacted and truncated before storage; ADK's
message-content capture is disabled for the embedded verifier.

``RunObserver`` is attached to a RunContext and is the single entry point used
by the runtime, tool adapters and the CrewAI event listener. It also keeps
per-agent metrics and file provenance (which tool call by which agent wrote
which file).
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.trace import Status, StatusCode

from backend.observability.redaction import redact

_FILE_WRITE_TOOLS = {"write_file", "patch_file", "delete_file"}


class _CollectingProcessor(SpanProcessor):  # noqa: D101
    """Routes finished spans to the RunObserver that owns their run id."""

    def __init__(self) -> None:
        self._sinks: dict[str, RunObserver] = {}
        self._by_trace: dict[str, RunObserver] = {}  # framework spans carry no vexa.run_id
        self._lock = threading.Lock()

    def register(self, run_id: str, observer: RunObserver) -> None:
        with self._lock:
            self._sinks[run_id] = observer
            self._by_trace[observer.trace_id] = observer

    def unregister(self, run_id: str) -> None:
        with self._lock:
            obs = self._sinks.pop(run_id, None)
            if obs is not None:
                self._by_trace.pop(obs.trace_id, None)

    def observers(self) -> list[RunObserver]:
        with self._lock:
            return list(self._sinks.values())

    def on_end(self, span: ReadableSpan) -> None:
        run_id = (span.attributes or {}).get("vexa.run_id")
        with self._lock:
            sink = self._sinks.get(run_id) if run_id else self._by_trace.get(_hex(span.context.trace_id, 32))
        if sink is not None:
            sink._collect(span)


_provider_lock = threading.Lock()
_provider: TracerProvider | None = None
_collector = _CollectingProcessor()


def _get_tracer():
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = TracerProvider(resource=Resource.create({"service.name": "vexa"}))
            _provider.add_span_processor(_collector)
            if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            _share_with_frameworks(_provider)
        return _provider.get_tracer("vexa")


def _share_with_frameworks(provider: TracerProvider) -> None:
    """Let ADK's global-tracer spans reach the collector without replacing a user's OTel setup."""
    current = otel_trace.get_tracer_provider()
    if isinstance(current, TracerProvider):  # an application already configured OTel
        if current is not provider:
            current.add_span_processor(_collector)
        return
    otel_trace.set_tracer_provider(provider)


def ensure_tracing() -> None:
    _get_tracer()


def _hex(value: int, width: int) -> str:
    return format(value, f"0{width}x")


_FOREIGN_ATTR_MAX = 300
_FOREIGN_DROP = ("llm_request", "llm_response", "tool_response", "gen_ai.input.messages", "gen_ai.output.messages",
                 "gen_ai.system_instructions")


def _span_source(span: ReadableSpan) -> str:
    scope = getattr(span, "instrumentation_scope", None)
    name = (getattr(scope, "name", "") or "").lower()
    if (span.attributes or {}).get("vexa.kind") or name == "vexa":
        return "vexa"
    return "google-adk" if "adk" in name or name.startswith("gcp.vertex") else (name or "otel")


def _foreign_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Framework span attributes: drop message bodies, truncate the rest, mask secrets."""
    out = {}
    for k, v in attrs.items():
        if any(d in k for d in _FOREIGN_DROP):
            out[k] = "[omitted: message content is not stored]"
            continue
        out[k] = redact(v if isinstance(v, (bool, int, float)) else str(v), _FOREIGN_ATTR_MAX)
    return out


def _foreign_kind(name: str, attrs: dict[str, Any]) -> str:
    op = str(attrs.get("gen_ai.operation.name", ""))
    if op == "execute_tool" or name.startswith("execute_tool"):
        return "tool"
    if name.startswith("call_llm") or op in ("chat", "generate_content"):
        return "llm"
    if op == "invoke_agent" or name.startswith("invoke_agent"):
        return "agent"
    return "internal"


def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    attrs = dict(span.attributes or {})
    source = _span_source(span)
    if source != "vexa":
        kind = _foreign_kind(span.name, attrs)
        attrs = _foreign_attrs(attrs)
        attrs["vexa.source"] = source
    else:
        kind = attrs.pop("vexa.kind", "internal")
    return {
        "trace_id": _hex(span.context.trace_id, 32),
        "span_id": _hex(span.context.span_id, 16),
        "parent_span_id": _hex(span.parent.span_id, 16) if span.parent else None,
        "name": span.name,
        "kind": kind,
        "source": source,
        "start_ns": span.start_time,
        "end_ns": span.end_time,
        "duration_ms": ((span.end_time or 0) - (span.start_time or 0)) / 1e6,
        "status": span.status.status_code.name.lower(),
        "status_message": span.status.description,
        "attributes": attrs,
        "events": [{"name": e.name, "attributes": dict(e.attributes or {})} for e in span.events],
    }


def _new_metrics() -> dict[str, Any]:
    return {
        "framework": "crewai", "status": "pending", "first_started_at": None, "last_finished_at": None,
        "invocations": 0, "failures": 0, "duration_ms": 0.0,
        "llm_calls": 0, "llm_failures": 0, "usage_reported_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "tool_calls": 0, "tool_errors": 0, "validation_retries": 0, "guardrail_blocks": 0, "llm_retries": 0,
    }


def _iso_now() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _finalise_metrics(m: dict[str, Any]) -> dict[str, Any]:
    """Tokens are None (unavailable) unless the provider reported usage for every LLM call."""
    out = dict(m)
    # Calls the provider rejected (rate limit, auth, network) consumed no tokens and carry no usage;
    # usage is "available" when every call that produced a response reported it.
    answered = m["llm_calls"] - m["llm_failures"]
    usage_ok = answered > 0 and m["usage_reported_calls"] >= answered
    out["usage_available"] = usage_ok
    if not usage_ok:
        out["input_tokens"] = out["output_tokens"] = None
        out["usage_note"] = ("no LLM calls (mock, scripted or tool-only agent)" if m["llm_calls"] == 0
                             else "every LLM call failed" if answered <= 0
                             else f"provider reported usage for {m['usage_reported_calls']}/{answered} answered calls")
    return out


class RunObserver:
    """Per-run tracing, metrics and provenance. Thread-safe."""

    def __init__(self, run_id: str, attributes: dict[str, Any] | None = None) -> None:
        self.run_id = run_id
        self._tracer = _get_tracer()
        self._lock = threading.RLock()
        self._spans: list[dict[str, Any]] = []
        self._agent_spans: dict[str, Any] = {}
        self._llm_spans: dict[str, Any] = {}
        self._tool_spans: dict[str, Any] = {}
        self.agent_metrics: dict[str, dict[str, Any]] = defaultdict(_new_metrics)
        self._unattributed = _new_metrics()  # LLM calls whose agent could not be resolved
        self._llm_agents: dict[str, str | None] = {}
        self._llm_done: set[str] = set()
        self.file_provenance: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.callback_events: list[dict[str, Any]] = []
        self._run_span = self._tracer.start_span(
            "vexa.run", attributes=self._attrs("run", **(attributes or {})),
        )
        self.trace_id = _hex(self._run_span.get_span_context().trace_id, 32)
        _collector.register(run_id, self)
        self._closed = False
        self.guard_sink = None  # set by the runtime: RunContext.guard

    # -- helpers ---------------------------------------------------------

    def _attrs(self, kind: str, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"vexa.run_id": self.run_id, "vexa.kind": kind}
        for k, v in extra.items():
            if v is None:
                continue
            out[f"vexa.{k}"] = v if isinstance(v, (bool, int, float, str)) else str(v)
        return out

    def _ctx_for(self, agent: str | None):
        parent = self._agent_spans.get(agent) if agent else None
        return otel_trace.set_span_in_context(parent or self._run_span)

    def _collect(self, span: ReadableSpan) -> None:
        with self._lock:
            self._spans.append(_span_to_dict(span))

    # -- agents ----------------------------------------------------------

    def agent_started(self, agent: str) -> None:
        with self._lock:
            old = self._agent_spans.pop(agent, None)
            if old is not None:  # previous invocation never closed
                old.set_status(Status(StatusCode.ERROR, "superseded"))
                old.end()
            m = self.agent_metrics[agent]
            self._agent_spans[agent] = self._tracer.start_span(
                f"agent:{agent}", context=otel_trace.set_span_in_context(self._run_span),
                attributes=self._attrs("agent", agent=agent, framework=m["framework"],
                                       invocation=m["invocations"] + 1),
            )
            m["invocations"] += 1
            m["status"] = "running"
            m["first_started_at"] = m["first_started_at"] or _iso_now()

    def agent_finished(self, agent: str, duration_ms: float, error: str | None = None) -> None:
        with self._lock:
            span = self._agent_spans.pop(agent, None)
            m = self.agent_metrics[agent]
            m["duration_ms"] += duration_ms
            m["last_finished_at"] = _iso_now()
            m["status"] = "failed" if error else "completed"
            if error:
                m["failures"] += 1
            if span is not None:
                span.set_status(Status(StatusCode.ERROR, redact(error, 500)) if error else Status(StatusCode.OK))
                span.end()

    # -- tools -----------------------------------------------------------

    def tool_started(self, agent: str | None, tool: str, args: dict[str, Any], origin: str = "agent") -> str:
        """origin: agent (chosen by the LLM) | scripted (mock agents) | orchestrator (runtime itself)."""
        with self._lock:
            span = self._tracer.start_span(
                f"tool:{tool}", context=self._ctx_for(agent),
                attributes=self._attrs("tool", tool=tool, agent=agent, origin=origin,
                                       args=str(redact(args, max_len=300))),
            )
            key = _hex(span.get_span_context().span_id, 16)
            self._tool_spans[key] = (span, agent, tool, args, time.perf_counter())
            if agent:
                self.agent_metrics[agent]["tool_calls"] += 1
            return key

    def tool_finished(self, key: str, ok: bool, summary: str = "", **attrs: Any) -> None:
        with self._lock:
            item = self._tool_spans.pop(key, None)
            if item is None:
                return
            span, agent, tool, args, t0 = item
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(f"vexa.{k}", v if isinstance(v, (bool, int, float, str)) else str(v))
            if summary:
                span.set_attribute("vexa.result", redact(summary, max_len=500))
            if not ok:
                span.set_status(Status(StatusCode.ERROR, redact(summary, 300)))
                if agent:
                    self.agent_metrics[agent]["tool_errors"] += 1
            else:
                span.set_status(Status(StatusCode.OK))
            if ok and tool in _FILE_WRITE_TOOLS and isinstance(args.get("path"), str):
                self.file_provenance[args["path"]].append({
                    "agent": agent, "tool": tool, "span_id": key,
                    "at_ms": round((time.perf_counter() - t0) * 1000, 1),
                })
            span.end()

    def has_open_llm_call(self, call_id: str) -> bool:
        with self._lock:
            return call_id in self._llm_spans

    def open_llm_agent(self, call_id: str) -> str | None:
        with self._lock:
            return self._llm_agents.get(call_id)

    def native_framework_spans(self, source: str = "google-adk") -> list[dict[str, Any]]:
        with self._lock:
            return [sp for sp in self._spans if sp.get("source") == source]

    def record_remote(self, agent: str, parent_key: str | None, telemetry: dict[str, Any], origin: str) -> dict[str, Any]:
        """Merge what a remote agent reported over A2A into this run's trace and metrics.

        Metrics (tool calls, LLM calls, tokens, retries) always come from the
        telemetry. Spans: if the framework's own OpenTelemetry spans for those
        calls were already collected in this trace (embedded ADK server), no
        extra spans are created, so nothing appears twice. Otherwise one span
        per reported call is created with the remote timestamps and marked
        ``vexa.reconstructed=true`` (it was rebuilt from telemetry, not recorded
        by OTel in the remote process).
        """
        with self._lock:
            parent_item = self._tool_spans.get(parent_key) if parent_key else None
            parent = parent_item[0] if parent_item else self._agent_spans.get(agent) or self._run_span
            ctx = otel_trace.set_span_in_context(parent)
            native = {sp["kind"] for sp in self._spans if sp.get("source") == "google-adk"}
            m = self.agent_metrics[agent]
            for call in telemetry.get("tool_calls", []):
                m["tool_calls"] += 1
                if not call.get("ok"):
                    m["tool_errors"] += 1
                if "tool" in native:
                    continue
                span = self._tracer.start_span(
                    f"tool:{call['tool']}", context=ctx, start_time=call.get("start_ns"),
                    attributes=self._attrs("tool", tool=call["tool"], agent=agent, origin=origin, transport="adk",
                                           reconstructed=True, args=str(redact(call.get("args", {}), max_len=300))),
                )
                span.set_status(Status(StatusCode.OK) if call.get("ok")
                                else Status(StatusCode.ERROR, redact(call.get("summary", ""), 300)))
                span.end(end_time=call.get("end_ns"))
            for call in telemetry.get("llm_calls", []):
                usage, error = call.get("usage"), call.get("error")
                prompt = int((usage or {}).get("prompt_tokens") or 0)
                completion = int((usage or {}).get("completion_tokens") or 0)
                m["llm_calls"] += 1
                m["input_tokens"] += prompt
                m["output_tokens"] += completion
                if usage:
                    m["usage_reported_calls"] += 1
                if error:
                    m["llm_failures"] += 1
                if "llm" in native:
                    continue
                span = self._tracer.start_span("llm.call", context=ctx, start_time=call.get("start_ns"),
                                               attributes=self._attrs("llm", agent=agent, origin=origin,
                                                                      reconstructed=True))
                span.set_attribute("vexa.usage_available", bool(usage))
                span.set_attribute("vexa.input_tokens", prompt)
                span.set_attribute("vexa.output_tokens", completion)
                span.set_status(Status(StatusCode.ERROR, redact(error, 300)) if error else Status(StatusCode.OK))
                span.end(end_time=call.get("end_ns"))
            for r in telemetry.get("retries", []):
                m["llm_retries"] += 1
                parent.add_event("retry", {k: str(v)[:200] for k, v in redact(r, 200).items()},
                                 timestamp=r.get("at_ns"))
            for ev in telemetry.get("events", []):
                parent.add_event(f"remote.{ev.get('event', 'event')}",
                                 {k: str(v)[:200] for k, v in redact(ev, 200).items()}, timestamp=ev.get("at_ns"))
            return {"native_span_kinds": sorted(native), "reconstructed": not {"tool", "llm"} <= native}

    # -- LLM calls (from CrewAI events) -----------------------------------

    def llm_started(self, call_id: str, agent: str | None, model: str | None) -> None:
        with self._lock:
            if call_id in self._llm_done:
                return
            self._llm_agents[call_id] = agent
            self._llm_spans[call_id] = self._tracer.start_span(
                "llm.call", context=self._ctx_for(agent),
                attributes=self._attrs("llm", agent=agent, model=model, call_id=call_id),
            )
            (self.agent_metrics[agent] if agent else self._unattributed)["llm_calls"] += 1

    def llm_finished(self, call_id: str, agent: str | None, usage: dict[str, Any] | None,
                     error: str | None = None, finish_reason: str | None = None) -> None:
        with self._lock:
            if call_id in self._llm_done:  # already closed by the other capture path: no double count
                return
            self._llm_done.add(call_id)
            span = self._llm_spans.pop(call_id, None)
            self._llm_agents.pop(call_id, None)
            u = usage or {}
            prompt = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
            completion = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
            m = self.agent_metrics[agent] if agent else self._unattributed
            m["input_tokens"] += prompt
            m["output_tokens"] += completion
            if usage:
                m["usage_reported_calls"] += 1
            if error:
                m["llm_failures"] += 1
            if span is None:
                return
            span.set_attribute("vexa.usage_available", bool(usage))
            span.set_attribute("vexa.input_tokens", prompt)
            span.set_attribute("vexa.output_tokens", completion)
            if finish_reason:
                span.set_attribute("vexa.finish_reason", finish_reason)
            span.set_status(Status(StatusCode.ERROR, redact(error, 300)) if error else Status(StatusCode.OK))
            span.end()

    # -- agent annotations, state access, guardrails ----------------------

    def set_framework(self, agent: str, framework: str) -> None:
        with self._lock:
            self.agent_metrics[agent]["framework"] = framework

    def annotate_agent(self, agent: str, **attrs: Any) -> None:
        span = self._agent_spans.get(agent)
        if span is not None:
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(f"vexa.{k}", v if isinstance(v, (bool, int, float, str)) else str(v))

    def state_event(self, kind: str, key: str, agent: str, version: int | None) -> None:
        target = self._agent_spans.get(agent)
        (target or self._run_span).add_event(f"state.{kind}", {"key": key, "agent": agent, "version": version or 0})

    def guardrail_event(self, ev: dict[str, Any]) -> None:
        agent = ev.get("agent")
        with self._lock:
            if agent and ev["decision"] == "blocked":
                self.agent_metrics[agent]["guardrail_blocks"] += 1
        target = self._agent_spans.get(agent) if agent else None
        (target or self._run_span).add_event(f"guardrail.{ev['decision']}", {
            "rule": ev["rule"], "kind": ev["kind"], "reason": str(ev.get("reason", ""))[:200]})

    def traceparent(self, span_key: str | None = None) -> str:
        """W3C traceparent for propagating this trace to another service (A2A)."""
        span = None
        if span_key:
            item = self._tool_spans.get(span_key)
            span = item[0] if item else None
        ctx = (span or self._run_span).get_span_context()
        return f"00-{_hex(ctx.trace_id, 32)}-{_hex(ctx.span_id, 16)}-01"

    # -- generic callback events -------------------------------------------

    def callback_event(self, kind: str, agent: str | None, **data: Any) -> None:
        with self._lock:
            self.callback_events.append({
                "seq": len(self.callback_events) + 1, "kind": kind, "agent": agent,
                "at": time.time(), **redact(data, max_len=2000),
            })
            if kind == "guardrail_failed" and agent:
                self.agent_metrics[agent]["validation_retries"] += 1
        if kind in ("guardrail_failed", "guardrail_passed") and self.guard_sink is not None:
            # CrewAI schema-guardrail outcomes are G8 decisions
            ok = kind == "guardrail_passed"
            self.guard_sink("output_schema", agent, "allowed" if ok else "blocked",
                            "output matched schema" if ok else f"schema violation, agent re-prompted: {data.get('error')}",
                            action="proceed" if ok else "retry", retry_count=data.get("retry_count"))
        target = self._agent_spans.get(agent) if agent else None
        (target or self._run_span).add_event(kind, {k: str(v)[:200] for k, v in redact(data, 200).items()})

    # -- lifecycle -------------------------------------------------------

    def close(self, status: str, error: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for span in list(self._agent_spans.values()) + [s[0] for s in self._tool_spans.values()] \
                    + list(self._llm_spans.values()):
                span.set_status(Status(StatusCode.ERROR, "run ended before span closed"))
                span.end()
            self._agent_spans.clear(), self._tool_spans.clear(), self._llm_spans.clear()
            self._run_span.set_attribute("vexa.status", status)
            failed = bool(error) or status == "failed"
            self._run_span.set_status(Status(StatusCode.ERROR, redact(error or status, 500)) if failed
                                      else Status(StatusCode.OK))
            self._run_span.end()
        _collector.unregister(self.run_id)

    def tokens_used(self) -> int:
        """Tokens reported so far (calls without usage are not counted; see usage_totals for availability)."""
        with self._lock:
            return sum(m["input_tokens"] + m["output_tokens"] for m in [*self.agent_metrics.values(), self._unattributed])

    def usage_totals(self) -> dict[str, Any]:
        """Run-level tokens summed from per-call LLM events (each call counted exactly once).

        Available only when at least one LLM call happened and every call reported usage;
        otherwise tokens are None, never 0.
        """
        with self._lock:
            buckets = [*self.agent_metrics.values(), self._unattributed]
            calls = sum(m["llm_calls"] - m["llm_failures"] for m in buckets)  # answered calls
            reported = sum(m["usage_reported_calls"] for m in buckets)
            if calls <= 0 or reported < calls:
                return {"usage_available": False, "llm_calls": calls, "usage_reported_calls": reported,
                        "input_tokens": None, "output_tokens": None, "total_tokens": None}
            inp = sum(m["input_tokens"] for m in buckets)
            out = sum(m["output_tokens"] for m in buckets)
            return {"usage_available": True, "llm_calls": calls, "usage_reported_calls": reported,
                    "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}

    def spans(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._spans, key=lambda s: s["start_ns"] or 0)

    def export(self) -> dict[str, Any]:
        with self._lock:
            return {
                "trace_id": self.trace_id,
                "spans": self.spans(),
                "agent_metrics": {k: _finalise_metrics(v) for k, v in self.agent_metrics.items()},
                "file_provenance": {k: list(v) for k, v in self.file_provenance.items()},
                "callback_events": list(self.callback_events),
            }
