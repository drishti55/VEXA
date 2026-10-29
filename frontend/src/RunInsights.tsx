import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowRight, Boxes, Download, FileText, GitBranch, Radio, ShieldAlert, Timer, Wrench } from 'lucide-react';
import { VexaApi } from './api/client';
import type { AgentMetrics, CoordinationEvent, GuardrailEvent, RunResult, Span } from './api/client';

function Panel({ title, icon, children, right }: { title: string; icon: React.ReactNode; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted flex items-center gap-2">{icon}{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="text-xs text-vexa-muted italic">{text}</div>;
}

const KIND_STYLE: Record<string, string> = {
  dispatch: 'text-vexa-accent',
  decision: 'text-purple-300',
  review: 'text-pink-300',
  event: 'text-amber-300',
  delivery: 'text-amber-200/70',
  message: 'text-emerald-300',
  stop: 'text-vexa-muted',
};

const na = (v: number | null | undefined, fmt: (x: number) => string = String) => (v === null || v === undefined ? 'n/a' : fmt(v));

// ---------------------------------------------------------------------------
// Coordination: manager decisions/reviews, events, A2A + MCP messages
// ---------------------------------------------------------------------------

export function CoordinationView({ result }: { result?: RunResult }) {
  const log: CoordinationEvent[] = result?.coordination_log ?? [];
  const [hideDispatch, setHideDispatch] = useState(true);
  const shown = log.filter(c => !(hideDispatch && (c.kind === 'delivery' || c.kind === 'dispatch')));
  const a2a = log.filter(c => c.kind === 'message' && c.data?.protocol === 'a2a');
  const mcpMsgs = log.filter(c => c.kind === 'message' && c.data?.protocol === 'mcp');
  const verifier = result?.verification_result;
  const mcpSpans = (result?.trace?.spans ?? []).filter(s => s.attributes['vexa.transport'] === 'mcp');

  return (
    <div className="space-y-4">
      <Panel title={`Coordination log · ${result?.architecture ?? '-'}`} icon={<GitBranch className="w-4 h-4" />}
        right={<label className="text-xs text-vexa-muted flex items-center gap-2">
          <input type="checkbox" checked={hideDispatch} onChange={e => setHideDispatch(e.target.checked)} />hide dispatch/delivery</label>}>
        {shown.length === 0 ? <Empty text={log.length ? 'Only dispatch entries (a fixed pipeline makes no decisions).' : 'No coordination recorded yet.'} /> : (
          <div className="font-mono text-xs space-y-1 max-h-96 overflow-y-auto">
            {shown.map(c => (
              <div key={c.seq} className="flex gap-2 items-start">
                <span className="text-vexa-muted w-8 shrink-0 text-right">{c.seq}</span>
                <span className={`w-16 shrink-0 uppercase ${KIND_STYLE[c.kind] ?? ''}`}>{c.kind}</span>
                <span className="text-gray-300 shrink-0">{c.actor}</span>
                {c.target && <><ArrowRight className="w-3 h-3 mt-0.5 text-vexa-muted shrink-0" /><span className="text-white shrink-0">{c.target}</span></>}
                <span className="text-vexa-muted break-words" title={c.detail}>{c.detail}</span>
                {c.kind === 'decision' && c.data?.accepted === false && <span className="text-vexa-error shrink-0">rejected</span>}
                {c.kind === 'decision' && c.data?.revision && <span className="text-pink-300 shrink-0">revision</span>}
                {c.kind === 'dispatch' && c.data?.work_package && <span className="text-sky-300 shrink-0">steps {c.data.work_package.join(', ')}</span>}
                {c.kind === 'decision' && c.data?.route && <span className="text-vexa-muted shrink-0">route: {c.data.route}</span>}
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Panel title={`A2A · verifier ${verifier?.backend ?? result?.verifier_backend ?? 'n/a'}`} icon={<Radio className="w-4 h-4" />}>
          {a2a.length === 0 ? <Empty text={verifier ? 'This run used the in-process CrewAI Verifier (no A2A).' : 'The Verifier has not run yet.'} /> : (
            <div className="text-xs space-y-2">
              {a2a.map(m => (
                <div key={m.seq} className="font-mono">
                  <span className="text-emerald-300">{m.actor}</span> → <span className="text-white">{m.target}</span>
                  <div className="text-vexa-muted pl-2">{m.detail}{m.data?.task_id ? ` · task ${String(m.data.task_id).slice(0, 8)}` : ''}</div>
                </div>
              ))}
              {verifier?.remote && (
                <div className="text-vexa-muted border-t border-vexa-border pt-2">
                  Agent card <span className="text-white">{verifier.remote.agent}</span> · protocol {verifier.remote.protocol_version ?? '?'} · states {(verifier.remote.states_seen ?? []).join(' → ')}
                </div>
              )}
            </div>
          )}
        </Panel>
        <Panel title={`MCP · tools ${result?.tool_transport ?? 'n/a'}`} icon={<Boxes className="w-4 h-4" />}>
          {(result?.mcp_servers ?? []).length === 0 ? <Empty text={result?.tool_transport === 'direct' ? 'Direct tool transport selected (no MCP).' : 'MCP servers start when the run starts.'} /> : (
            <div className="text-xs space-y-2">
              {result!.mcp_servers!.map(s => (
                <div key={s.name}>
                  <span className="font-mono text-white">{s.name}</span>{' '}
                  <span className={s.status === 'connected' ? 'text-vexa-success' : 'text-vexa-warning'}>{s.status}</span>
                  {s.tools.length > 0 && <div className="text-vexa-muted font-mono pl-2">{s.tools.join(', ')}</div>}
                </div>
              ))}
              {mcpMsgs.map(m => <div key={m.seq} className="text-vexa-muted font-mono">{m.detail}</div>)}
              <div className="text-vexa-muted">{mcpSpans.length} tool call(s) over MCP in this run</div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared state / blackboard: who read and wrote which knowledge item
// ---------------------------------------------------------------------------

export function StateView({ result }: { result?: RunResult }) {
  const entries = result?.state?.entries ?? [];
  const accessLog = result?.state?.access_log;
  const [selected, setSelected] = useState<string | null>(null);

  const { keys, agents, cell, access } = useMemo(() => {
    const access = accessLog ?? [];
    const keys = Array.from(new Set(access.map(a => a.key)));
    const agents = Array.from(new Set(access.map(a => a.agent)));
    const cell = new Map<string, { r: number; w: number }>();
    for (const a of access) {
      const k = `${a.agent}|${a.key}`;
      const c = cell.get(k) ?? { r: 0, w: 0 };
      if (a.kind === 'read') c.r++; else c.w++;
      cell.set(k, c);
    }
    return { keys, agents, cell, access };
  }, [accessLog]);

  const reads = access.filter(a => a.kind === 'read').length;
  const sel = entries.find(e => e.entry_id === selected);

  return (
    <div className="space-y-4">
      <Panel title="Knowledge access matrix" icon={<Boxes className="w-4 h-4" />}>
        <p className="text-xs text-vexa-muted mb-3">
          {reads === 0
            ? 'No agent read the shared state: outputs were passed directly (state is an audit mirror).'
            : `${reads} reads through the shared state — agents coordinated via the blackboard.`}
        </p>
        {keys.length === 0 ? <Empty text="No state activity yet." /> : (
          <div className="overflow-x-auto">
            <table className="text-xs font-mono">
              <thead>
                <tr><th className="text-left pr-3 text-vexa-muted font-normal">agent \ item</th>
                  {keys.map(k => <th key={k} className="px-2 text-vexa-muted font-normal whitespace-nowrap">{k}</th>)}</tr>
              </thead>
              <tbody>
                {agents.map(ag => (
                  <tr key={ag} className="border-t border-vexa-border/50">
                    <td className="pr-3 py-1 text-white whitespace-nowrap">{ag}</td>
                    {keys.map(k => {
                      const c = cell.get(`${ag}|${k}`);
                      return (
                        <td key={k} className="px-2 text-center">
                          {c ? <span>{c.w > 0 && <span className="text-amber-300">W{c.w > 1 ? c.w : ''}</span>}{c.w > 0 && c.r > 0 && ' '}{c.r > 0 && <span className="text-sky-300">R{c.r > 1 ? c.r : ''}</span>}</span> : <span className="text-vexa-border">·</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={`Versioned entries (${entries.length})`} icon={<GitBranch className="w-4 h-4" />}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="font-mono text-xs space-y-1 max-h-72 overflow-y-auto">
            {entries.map(e => (
              <button key={e.entry_id} onClick={() => setSelected(e.entry_id)}
                className={`w-full text-left px-2 py-1 rounded ${selected === e.entry_id ? 'bg-vexa-accent/20 text-vexa-accent' : 'hover:bg-black/30 text-gray-300'}`}>
                #{e.seq} {e.key} <span className="text-vexa-muted">v{e.version} · {e.author}</span>
              </button>
            ))}
          </div>
          <pre className="text-[11px] bg-black/40 rounded p-2 max-h-72 overflow-auto whitespace-pre-wrap text-gray-300">
            {sel ? JSON.stringify({ derived_from: sel.derived_from, value: sel.value }, null, 2) : 'Select an entry to see its value and provenance.'}
          </pre>
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trace hierarchy, tool history, errors/retries, per-agent metrics, guardrails
// ---------------------------------------------------------------------------

const SPAN_COLOR: Record<string, string> = {
  run: 'bg-slate-500', agent: 'bg-vexa-accent', tool: 'bg-amber-500', llm: 'bg-purple-500',
};

function orderSpans(spans: Span[]): { span: Span; depth: number }[] {
  const children = new Map<string | null, Span[]>();
  for (const s of spans) {
    const k = s.parent_span_id;
    children.set(k, [...(children.get(k) ?? []), s]);
  }
  const ids = new Set(spans.map(s => s.span_id));
  const out: { span: Span; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const s of (children.get(parent) ?? []).sort((a, b) => a.start_ns - b.start_ns)) {
      out.push({ span: s, depth });
      walk(s.span_id, depth + 1);
    }
  };
  walk(null, 0);
  for (const s of spans) if (s.parent_span_id && !ids.has(s.parent_span_id) && !out.find(o => o.span === s)) out.push({ span: s, depth: 0 });
  return out;
}

const DECISION_STYLE: Record<string, string> = {
  allowed: 'text-vexa-success', blocked: 'text-vexa-error', sanitized: 'text-sky-300',
  flagged: 'text-vexa-warning', indeterminate: 'text-vexa-muted',
};

export function TraceView({ result }: { result?: RunResult }) {
  const spans: Span[] = (result?.trace?.spans ?? []).filter(s => s.start_ns && s.end_ns);
  const metrics: Record<string, AgentMetrics> = result?.agent_metrics ?? result?.trace?.agent_metrics ?? {};
  const guards: GuardrailEvent[] = result?.guardrail_events ?? [];
  const [showAllowed, setShowAllowed] = useState(false);
  const [showProtocolInternals, setShowProtocolInternals] = useState(false);
  const sources = Array.from(new Set(spans.map(s => s.source ?? 'vexa')));
  const t0 = Math.min(...spans.map(s => s.start_ns));
  const t1 = Math.max(...spans.map(s => s.end_ns));
  const total = Math.max(t1 - t0, 1);
  // a2a-sdk request plumbing (dispatcher / event queue) is real but noisy; hidden unless asked for.
  const ordered = orderSpans(spans)
    .filter(({ span }) => showProtocolInternals || !(span.source && span.source.startsWith('a2a') && span.kind === 'internal'))
    .slice(0, 300);
  const tools = spans.filter(s => s.kind === 'tool').sort((a, b) => a.start_ns - b.start_ns);
  const errorSpans = spans.filter(s => s.status === 'error');
  const retries = (result?.trace?.callback_events ?? []).filter(e => e.kind === 'guardrail_failed' || e.kind === 'tool_error' || e.kind === 'task_failed');
  const shownGuards = guards.filter(g => showAllowed || g.decision !== 'allowed');
  const guardCounts = guards.reduce<Record<string, number>>((acc, g) => { acc[g.decision] = (acc[g.decision] ?? 0) + 1; return acc; }, {});

  if (!result) return <Empty text="Start or open a run to see its trace." />;

  return (
    <div className="space-y-4">
      <Panel title={`Trace hierarchy ${result.trace_id ? `· ${result.trace_id.slice(0, 16)}` : ''}`} icon={<Timer className="w-4 h-4" />}>
        {ordered.length === 0 ? <Empty text="Spans appear as soon as agents and tools finish." /> : (
          <div className="space-y-0.5 max-h-96 overflow-y-auto">
            {ordered.map(({ span: s, depth }) => {
              const left = ((s.start_ns - t0) / total) * 100;
              const width = Math.max(((s.end_ns - s.start_ns) / total) * 100, 0.4);
              const foreign = s.source && s.source !== 'vexa';
              const label = s.kind === 'run' ? `run · ${result.architecture}` : foreign ? s.name : (s.attributes['vexa.tool'] ?? s.attributes['vexa.agent'] ?? s.name);
              const extra = [foreign ? s.source : null, s.attributes['vexa.transport'],
                s.attributes['vexa.origin'] === 'scripted' ? 'scripted' : null,
                s.attributes['vexa.reconstructed'] ? 'reconstructed from telemetry' : null].filter(Boolean).join(' · ');
              const events = (s.events ?? []).map(e => e.name).join(', ');
              return (
                <div key={s.span_id} className="flex items-center gap-2 text-[11px] font-mono" data-testid="trace-span"
                  data-source={s.source ?? 'vexa'} data-kind={s.kind} data-status={s.status}
                  title={`${s.name} · ${s.duration_ms.toFixed(0)} ms · status ${s.status}${s.status_message ? ' · ' + s.status_message : ''}${events ? ' · events: ' + events : ''}`}>
                  <span className={`w-44 shrink-0 truncate ${s.kind === 'agent' || s.kind === 'run' ? 'text-white' : 'text-vexa-muted'}`}
                    style={{ paddingLeft: `${depth * 10}px` }}>{label}{extra && <span className="text-vexa-muted"> ({extra})</span>}</span>
                  <div className="relative flex-1 h-3 bg-black/30 rounded">
                    <div className={`absolute h-3 rounded ${SPAN_COLOR[s.kind] ?? 'bg-gray-500'} ${s.status === 'error' ? 'ring-1 ring-vexa-error' : ''}`}
                      style={{ left: `${left}%`, width: `${width}%` }} />
                  </div>
                  <span className="w-16 shrink-0 text-right text-vexa-muted">{s.duration_ms.toFixed(0)}ms</span>
                </div>
              );
            })}
          </div>
        )}
        <div className="flex flex-wrap gap-4 mt-3 text-[11px] text-vexa-muted">
          {Object.entries(SPAN_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className={`w-3 h-2 rounded ${c}`} />{k}</span>)}
          <span data-testid="trace-sources">sources: {sources.join(', ')}</span>
          {sources.some(x => x.startsWith('a2a')) && (
            <label className="flex items-center gap-1"><input type="checkbox" checked={showProtocolInternals}
              onChange={e => setShowProtocolInternals(e.target.checked)} />A2A protocol internals</label>)}
          <span>{spans.filter(s => s.kind === 'llm').length === 0 && result.execution_mode === 'mock' ? '· no LLM spans in mock mode' : ''}</span>
        </div>
      </Panel>

      <Panel title={`Per-agent metrics (${result.execution_mode})`} icon={<Boxes className="w-4 h-4" />}>
        {Object.keys(metrics).length === 0 ? <Empty text="No agent has finished yet." /> : (
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead className="text-vexa-muted">
                <tr>{['Agent', 'Framework', 'Status', 'Calls', 'Time (s)', 'LLM calls', 'Tokens in/out', 'Cost', 'Tools', 'Tool err', 'Retries', 'Blocks', 'Failures'].map(h =>
                  <th key={h} className="text-left font-normal pr-3 pb-1 whitespace-nowrap">{h}</th>)}</tr>
              </thead>
              <tbody className="font-mono">
                {Object.entries(metrics).map(([agent, m]) => (
                  <tr key={agent} className="border-t border-vexa-border/50">
                    <td className="pr-3 py-1 text-white">{agent}</td>
                    <td className="pr-3 text-vexa-muted">{m.framework}</td>
                    <td className={`pr-3 ${m.status === 'failed' ? 'text-vexa-error' : ''}`}>{m.status}</td>
                    <td className="pr-3">{m.invocations}</td>
                    <td className="pr-3">{(m.duration_ms / 1000).toFixed(2)}</td>
                    <td className="pr-3">{m.llm_calls}</td>
                    <td className="pr-3" title={m.usage_note ?? ''}>{m.input_tokens === null || m.input_tokens === undefined ? 'n/a' : `${m.input_tokens}/${m.output_tokens}`}</td>
                    <td className="pr-3">{na(m.estimated_cost_usd, x => `$${x.toFixed(4)}`)}</td>
                    <td className="pr-3">{m.tool_calls}</td>
                    <td className={`pr-3 ${m.tool_errors ? 'text-vexa-warning' : ''}`}>{m.tool_errors}</td>
                    <td className="pr-3" title="schema-validation retries + LLM rate-limit retries">{(m.validation_retries ?? 0) + (m.llm_retries ?? 0)}</td>
                    <td className={`pr-3 ${m.guardrail_blocks ? 'text-vexa-error' : ''}`}>{m.guardrail_blocks ?? 0}</td>
                    <td className={m.failures ? 'text-vexa-error' : ''}>{m.failures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[11px] text-vexa-muted mt-2">n/a = not measured (no LLM call, or the provider did not report usage) — never shown as 0.</p>
          </div>
        )}
      </Panel>

      <Panel title={`Tool calls (${tools.length})`} icon={<Wrench className="w-4 h-4" />}>
        {tools.length === 0 ? <Empty text="No tool calls yet." /> : (
          <div className="overflow-x-auto max-h-64 overflow-y-auto">
            <table className="text-xs w-full font-mono">
              <thead className="text-vexa-muted text-left"><tr>{['Agent', 'Tool', 'Transport', 'Origin', 'Status', 'ms', 'Args / result'].map(h => <th key={h} className="font-normal pr-3">{h}</th>)}</tr></thead>
              <tbody>
                {tools.map(s => (
                  <tr key={s.span_id} className="border-t border-vexa-border/50">
                    <td className="pr-3 py-0.5">{s.attributes['vexa.agent'] ?? (s.source === 'google-adk' ? 'Verifier' : '')}</td>
                    <td className="pr-3 text-white">{s.attributes['vexa.tool'] ?? s.attributes['gen_ai.tool.name'] ?? s.name}</td>
                    <td className="pr-3">{s.attributes['vexa.transport'] ?? (s.source === 'google-adk' ? 'adk (in-process)' : 'direct')}</td>
                    <td className="pr-3 text-vexa-muted">{s.attributes['vexa.origin'] ?? (s.source && s.source !== 'vexa' ? s.source : 'agent')}</td>
                    <td className={`pr-3 ${s.status === 'error' ? 'text-vexa-error' : 'text-vexa-success'}`}>{s.status === 'error' ? 'error' : 'ok'}</td>
                    <td className="pr-3">{s.duration_ms.toFixed(0)}</td>
                    <td className="text-vexa-muted truncate max-w-72" title={`${s.attributes['vexa.args'] ?? s.attributes['gen_ai.tool.call.arguments'] ?? ''} → ${s.attributes['vexa.result'] ?? ''}`}>{s.attributes['vexa.args'] ?? s.attributes['gen_ai.tool.call.arguments'] ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={`Errors & retries (${errorSpans.length + retries.length + (result.errors?.length ?? 0)})`} icon={<AlertTriangle className="w-4 h-4" />}>
        {errorSpans.length + retries.length + (result.errors?.length ?? 0) === 0 ? <Empty text="No errors, failed spans or retries." /> : (
          <div className="text-xs font-mono space-y-1 max-h-48 overflow-y-auto">
            {(result.errors ?? []).map((e, i) => <div key={`e${i}`} className="text-vexa-error break-words">run: {e}</div>)}
            {errorSpans.map(s => <div key={s.span_id} className="text-vexa-error break-words">{s.name}: {s.status_message}</div>)}
            {retries.map((e, i) => <div key={`r${i}`} className="text-vexa-warning break-words">{e.agent}: {e.kind} {e.error ? `— ${e.error}` : ''}</div>)}
          </div>
        )}
      </Panel>

      <Panel title={`Guardrail decisions (${guards.length})`} icon={<ShieldAlert className="w-4 h-4" />}
        right={<label className="text-xs text-vexa-muted flex items-center gap-2">
          <input type="checkbox" checked={showAllowed} onChange={e => setShowAllowed(e.target.checked)} />show allowed</label>}>
        <div className="flex gap-3 text-xs mb-2">
          {Object.entries(guardCounts).map(([d, n]) => <span key={d} className={DECISION_STYLE[d]}>{d}: {n}</span>)}
          {guards.length === 0 && <Empty text="No guardrail decisions recorded yet." />}
        </div>
        {shownGuards.length > 0 && (
          <div className="text-xs font-mono space-y-1 max-h-56 overflow-y-auto">
            {shownGuards.map(g => (
              <div key={g.seq} className="flex gap-2">
                <span className="w-8 text-vexa-muted">{g.rule}</span>
                <span className={`w-20 ${DECISION_STYLE[g.decision] ?? ''}`}>{g.decision}</span>
                <span className="w-16 text-vexa-muted">{g.action}</span>
                <span className="w-28 shrink-0 text-white truncate">{g.agent ?? '-'}</span>
                <span className="text-gray-300 truncate" title={g.reason}>{g.tool ? `[${g.tool}] ` : ''}{g.reason}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Final report
// ---------------------------------------------------------------------------

export function ReportView({ runId, finished }: { runId: string | null; finished: boolean }) {
  const [md, setMd] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!runId || !finished) return;
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) { setLoading(true); setError(null); } });
    VexaApi.getReportMarkdown(runId)
      .then(t => { if (!cancelled) setMd(t); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId, finished]);

  return (
    <Panel title="Final report (validated RunReport)" icon={<FileText className="w-4 h-4" />}
      right={finished && runId ? (
        <div className="flex gap-2">
          {(['json', 'md'] as const).map(f => (
            <button key={f} onClick={() => VexaApi.downloadRunReport(runId, f).catch(e => setError(e.message))}
              className="px-2 py-1 text-xs rounded border border-vexa-border hover:bg-black/30 flex items-center gap-1">
              <Download className="w-3 h-3" />{f.toUpperCase()}
            </button>
          ))}
        </div>) : undefined}>
      {!runId ? <Empty text="Start or open a run to see its report." /> :
        !finished ? <Empty text="The report is generated when the run finishes (also for failed runs)." /> :
          loading ? <Empty text="Loading report…" /> :
            error ? <div className="text-xs text-vexa-error">{error}</div> :
              <pre className="text-xs whitespace-pre-wrap font-mono text-gray-200 max-h-[36rem] overflow-y-auto">{md}</pre>}
    </Panel>
  );
}
