import { useEffect, useMemo, useState } from 'react';
import {
  Square, Download, Bot, Wrench, FileText, FilePen, ShieldAlert, Cpu, ChevronRight, ChevronDown, ArrowRight, Radio,
  Network, Database, AlertTriangle, RotateCcw,
} from 'lucide-react';
import { VexaApi } from '../../api/client';
import type { AgentRunResponse } from '../../api/client';
import { useStudio, toast, openFile, getState, switchWorkspace, openCompare, openAgent } from '../store';
import { fmtMs, fmtTime, StatusDot } from '../util';
import { agentViews, timeline, dispatchSequence } from './runModel';
import type { AgentView, TimelineItem } from './runModel';
import { CoordinationView, StateView, TraceView, ReportView } from '../../RunInsights';
import { DiffView } from './DiffView';
import { Waterfall } from '../BottomPanel';

type SubTab = 'live' | 'changes' | 'waterfall' | 'coordination' | 'state' | 'trace' | 'report';

const STATUS_LABEL: Record<string, string> = {
  not_dispatched: 'Not dispatched', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted',
};

export function RunView({ runId }: { runId: string }) {
  const run = useStudio(s => s.runs[runId]);
  const live = useStudio(s => s.liveRunIds.includes(runId));
  const [sub, setSub] = useState<SubTab>('live');
  if (!run) return <div className="st-empty st-muted">Loading run {runId.slice(0, 8)}…</div>;
  const res = run.result;
  const running = run.status === 'running';
  const mock = run.execution_mode === 'mock';

  const cancel = async () => {
    try { await VexaApi.cancelAgentRun(runId); toast('Cancellation requested: the run stops before the next agent starts.'); }
    catch (e: any) { toast(e.message, 'error'); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} data-testid="run-view">
      <div style={{ padding: '12px 16px 8px', borderBottom: '1px solid var(--border)', flex: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <StatusDot status={run.status} pulse={running} />
          <span data-testid="run-status" style={{ fontWeight: 600, color: 'var(--text-strong)', textTransform: 'uppercase', fontSize: 12 }}>{run.status}</span>
          <span className="st-pill">{run.architecture}</span>
          <span className={`st-pill ${mock ? 'mock' : 'warn'}`} title={mock ? 'Mock mode: agents return scripted, schema-valid answers. Tools, sandbox, guardrails and tracing are real; the agents are not.' : 'Real model calls'}>
            {mock ? 'MOCK · scripted agents' : 'REAL'}
          </span>
          {res?.model && <span className="st-pill"><Cpu size={11} />{res.model}</span>}
          {res?.prompt_variant && <span className="st-pill">prompt: {res.prompt_variant}</span>}
          {res?.tool_transport && <span className="st-pill">tools: {res.tool_transport}</span>}
          {res?.verifier_backend && <span className="st-pill">verifier: {res.verifier_backend}</span>}
          {live && <span className="st-pill run"><Radio size={11} className="pulse" />live (SSE)</span>}
          <span style={{ flex: 1 }} />
          {running && <button className="st-btn secondary" style={{ height: 24 }} onClick={cancel} data-testid="cancel-run"><Square size={12} />Stop run</button>}
          {!running && <button className="st-btn secondary" style={{ height: 24 }} onClick={() => VexaApi.downloadRunReport(runId, 'json').catch(e => toast(e.message, 'error'))}><Download size={12} />Report JSON</button>}
          {!running && <button className="st-btn secondary" style={{ height: 24 }} onClick={() => VexaApi.downloadRunReport(runId, 'md').catch(e => toast(e.message, 'error'))}><Download size={12} />Markdown</button>}
        </div>
        <div style={{ marginTop: 8, color: 'var(--text-strong)', lineHeight: 1.45 }}>{res?.requirement}</div>
        <div className="st-muted" style={{ marginTop: 6, display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 12 }}>
          <span>workspace <b style={{ color: 'var(--text)' }}>{run.workspace_id}</b></span>
          <span>started {fmtTime(res?.started_at)}</span>
          <span>duration {fmtMs(run.total_duration_ms)}</span>
          <span>files changed {run.files_changed?.length ?? 0}</span>
          <span>tests {res?.final_test_result ? (res.final_test_result.no_tests ? 'none found' : `${res.final_test_result.tests_passed}/${res.final_test_result.tests_found} passed`) : running ? 'pending' : 'not run'}</span>
          <span>verified {res?.verification_result ? (res.verification_result.verified ? 'yes' : 'no') : running ? 'pending' : '—'}</span>
          <span>tokens {res?.usage_available ? res.total_tokens.toLocaleString() : 'not reported'}</span>
          <span>cost {res?.estimated_cost_usd != null ? `$${res.estimated_cost_usd.toFixed(4)}` : 'n/a'}</span>
          <span className="st-faint">run {run.run_id}</span>
        </div>
        {run.workspace_id !== getState().workspaceId && (
          <div style={{ marginTop: 6, fontSize: 12 }} className="st-muted">
            This run belongs to another workspace. <button className="st-link" onClick={() => switchWorkspace(run.workspace_id)}>Open {run.workspace_id}</button>
          </div>
        )}
        {run.errors.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--err)' }}>
            {run.errors.slice(0, 3).map((e, i) => <div key={i}><AlertTriangle size={12} style={{ verticalAlign: -2 }} /> {e}</div>)}
          </div>
        )}
      </div>
      <div className="st-ptabs" style={{ borderBottom: '1px solid var(--border)' }}>
        {(['live', 'changes', 'waterfall', 'coordination', 'state', 'trace', 'report'] as SubTab[]).map(t => (
          <button key={t} className={`st-ptab${sub === t ? ' active' : ''}`} onClick={() => setSub(t)} data-testid={`run-tab-${t}`}>
            {t === 'live' ? 'Agents & Timeline' : t === 'changes' ? `Changes (${res?.code_changes?.length ?? 0})` : t === 'trace' ? 'Trace details' : t}
          </button>
        ))}
      </div>
      <div className="st-scroll">
        {sub === 'live' && <LiveTab run={run} />}
        {sub === 'changes' && (
          <div style={{ padding: 16 }}>
            {(res?.code_changes?.length ?? 0) === 0 ? <div className="st-muted">{running ? 'No file change yet.' : `This run changed no files${run.execution_mode === 'mock' ? ' (mock agents never write)' : ''}.`}</div> :
              <DiffView changes={res!.code_changes!} />}
            {(res?.files_changed?.length ?? 0) > 0 && <div className="st-faint" style={{ fontSize: 12, marginTop: 8 }}>Files changed: {res!.files_changed.map(f => <button key={f} className="st-link st-mono" style={{ marginRight: 8 }} onClick={() => openFile(f)}>{f}</button>)}</div>}
          </div>
        )}
        {sub === 'waterfall' && <Waterfall run={run} filters />}
        {!['live', 'changes', 'waterfall'].includes(sub) && (
          <div className="legacy" style={{ padding: 12 }}>
            {sub === 'coordination' && <CoordinationView result={res} />}
            {sub === 'state' && <StateView result={res} />}
            {sub === 'trace' && <TraceView result={res} />}
            {sub === 'report' && <ReportView runId={runId} finished={!running} />}
          </div>
        )}
      </div>
    </div>
  );
}

/** The run as it was at time t (epoch ms), rebuilt from its persisted records. Final per-agent metrics are dropped. */
function runAt(run: AgentRunResponse, t: number): AgentRunResponse {
  const r: any = run.result ?? {};
  const before = (iso?: string | null) => !iso || +new Date(iso) <= t;
  const trace = r.trace ? { ...r.trace, agent_metrics: {}, spans: (r.trace.spans ?? []).filter((s: any) => s.start_ns / 1e6 <= t),
    callback_events: (r.trace.callback_events ?? []).filter((c: any) => (typeof c.at === 'number' ? c.at * 1000 : +new Date(c.at)) <= t) } : r.trace;
  const events = (r.events ?? []).filter((e: any) => before(e.timestamp));
  return { ...run, status: 'running', result: { ...r, agent_metrics: {}, trace, events,
    coordination_log: (r.coordination_log ?? []).filter((c: any) => before(c.at)),
    guardrail_events: (r.guardrail_events ?? []).filter((g: any) => before(g.at)),
    current_agent: [...events].reverse().find((e: any) => e.event === 'started')?.agent ?? '' } };
}

function LiveTab({ run: liveRun }: { run: AgentRunResponse }) {
  const recentRuns = useStudio(s => s.recentRuns);
  const items0 = useMemo(() => timeline(liveRun), [liveRun]);
  const times = items0.map(i => i.t).filter(t => isFinite(t));
  const t0 = times.length ? Math.min(...times) : 0, t1 = times.length ? Math.max(...times) : 0;
  const [replayAt, setReplayAt] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing || replayAt == null) return;
    const next = times.filter(x => x > replayAt).sort((a, b) => a - b)[0];
    // at the last event stop playing (asynchronously, like every other step)
    const id = setTimeout(() => (next == null ? setPlaying(false) : setReplayAt(next)), 350);
    return () => clearTimeout(id);
  }, [playing, replayAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = useMemo(() => (replayAt == null ? liveRun : runAt(liveRun, replayAt)), [liveRun, replayAt]);
  const agents = useMemo(() => agentViews(run), [run]);
  const items = useMemo(() => timeline(run), [run]);
  const finished = liveRun.status !== 'running';
  const others = recentRuns.filter(r => r.run_id !== liveRun.run_id).slice(0, 40);
  const [selected, setSelected] = useState<string | null>(null);
  const sel = agents.find(a => a.name === selected) ?? null;
  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {finished && times.length > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '6px 10px', borderRadius: 6,
          border: `1px solid ${replayAt != null ? 'var(--mock)' : 'var(--border)'}`, background: replayAt != null ? 'color-mix(in srgb, var(--mock) 10%, transparent)' : undefined }} data-testid="replay-bar">
          {replayAt == null ? (
            <>
              <button className="st-btn secondary" style={{ height: 24 }} onClick={() => { setReplayAt(t0); setPlaying(true); }} data-testid="replay-start">Replay</button>
              <span className="st-faint" style={{ fontSize: 12 }}>step through this run's recorded events ({items0.length}) — no new run is started</span>
            </>
          ) : (
            <>
              <b style={{ color: 'var(--mock)', fontSize: 12 }}>REPLAY of recorded events — not a new run</b>
              <button className="st-btn secondary" style={{ height: 24 }} onClick={() => setPlaying(p => !p)}>{playing ? 'Pause' : 'Play'}</button>
              <input type="range" min={t0} max={t1} value={replayAt} onChange={e => { setPlaying(false); setReplayAt(+e.target.value); }} style={{ flex: 1, minWidth: 140 }} />
              <span className="st-mono" style={{ fontSize: 12 }}>+{fmtMs(replayAt - t0)}</span>
              <button className="st-btn secondary" style={{ height: 24 }} onClick={() => { setPlaying(false); setReplayAt(null); }}>Exit replay</button>
            </>
          )}
          <span style={{ flex: 1 }} />
          <select className="st-select" value="" onChange={e => e.target.value && openCompare(liveRun.run_id, e.target.value)} data-testid="compare-select">
            <option value="">Compare with…</option>
            {others.map(o => <option key={o.run_id} value={o.run_id}>{o.run_id.slice(0, 8)} · {o.architecture} · {o.execution_mode} · {o.status}</option>)}
          </select>
        </div>
      )}
      <Section title="Workflow" hint={`as executed by the ${run.architecture} architecture — drawn from its coordination log, not a fixed pipeline`}>
        <Workflow run={run} onPick={setSelected} />
      </Section>
      <Section title="Agents" hint="click an agent to inspect its input, output, tools and guardrail decisions">
        <div className="rv-grid">
          {agents.map(a => <AgentCard key={a.name} a={a} current={run.result?.current_agent === a.name && run.status === 'running'}
            selected={selected === a.name} onClick={() => setSelected(s => s === a.name ? null : a.name)} />)}
        </div>
        {sel && <AgentDetail a={sel} mock={run.execution_mode === 'mock'} />}
      </Section>
      <Communication run={run} />
      <Section title={`Timeline (${items.length})`} hint="agent lifecycle, coordination, guardrail and CrewAI callback events in time order — click to expand">
        <Timeline items={items} />
      </Section>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--text-strong)' }}>{title}</h3>
        {hint && <span className="st-faint" style={{ fontSize: 12 }}>{hint}</span>}
      </div>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------- workflow per architecture

function Workflow({ run, onPick }: { run: AgentRunResponse; onPick: (a: string) => void }) {
  const seq = dispatchSequence(run);
  const coord = run.result?.coordination_log ?? [];
  const agents = agentViews(run);
  const statusOf = (name: string) => agents.find(a => a.name === name)?.status ?? 'not_dispatched';
  if (seq.length === 0) {
    return <div className="st-muted" style={{ fontSize: 12 }}>{run.status === 'running' ? 'Waiting for the first dispatch…' : 'No agent was dispatched in this run.'}</div>;
  }
  // the k-th dispatch of an agent is "running" only if it is the agent's latest dispatch and the agent is running
  const lastIdx: Record<string, number> = {};
  seq.forEach((d, i) => { lastIdx[d.agent] = i; });
  const node = (d: typeof seq[number], i: number) => {
    const st = lastIdx[d.agent] === i ? statusOf(d.agent) : 'completed';
    return (
      <button key={d.seq} className={`rv-node ${st}`} onClick={() => onPick(d.agent)} title={`dispatch #${d.seq} by ${d.actor}`}>
        <StatusDot status={st === 'not_dispatched' ? 'idle' : st} pulse={st === 'running'} />{d.agent}{d.n > 1 && <span className="st-faint">#{d.n}</span>}
      </button>
    );
  };
  const flow = (
    <div className="rv-flow" data-testid="workflow">
      {seq.map((d, i) => <span key={d.seq} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>{i > 0 && <ArrowRight size={13} className="st-faint" />}{node(d, i)}</span>)}
    </div>
  );

  if (run.architecture === 'hierarchical') {
    const decisions = coord.filter(c => c.kind === 'decision' || c.kind === 'review');
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {flow}
        <div className="st-muted" style={{ fontSize: 12 }}>Manager decisions and reviews ({decisions.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 220, overflow: 'auto' }}>
          {decisions.length === 0 && <span className="st-faint" style={{ fontSize: 12 }}>none recorded yet</span>}
          {decisions.map(c => (
            <div key={c.seq} style={{ fontSize: 12, display: 'flex', gap: 8 }}>
              <span className={`st-pill ${c.kind === 'review' ? (c.data?.verdict === 'accept' ? 'ok' : 'warn') : 'run'}`}>{c.kind}</span>
              <span><b>{c.actor}</b>{c.target ? <> → <b>{c.target}</b></> : null}: {c.detail}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (run.architecture === 'event_driven') {
    const evs = coord.filter(c => c.kind === 'event' || c.kind === 'delivery');
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {flow}
        <div className="st-muted" style={{ fontSize: 12 }}>Published events and subscriber deliveries ({evs.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 220, overflow: 'auto' }}>
          {evs.map(c => (
            <div key={c.seq} style={{ fontSize: 12, display: 'flex', gap: 8, paddingLeft: c.kind === 'delivery' ? 20 : 0 }}>
              <span className={`st-pill ${c.kind === 'event' ? 'warn' : ''}`}>{c.kind === 'event' ? 'publish' : 'deliver'}</span>
              <span><b>{c.actor}</b>{c.target ? <> → <b>{c.target}</b></> : null}{c.detail ? `: ${c.detail}` : ''}
                {c.kind === 'event' && Array.isArray(c.data?.subscribers) && <span className="st-muted"> · subscribers: {c.data.subscribers.join(', ') || 'none'}</span>}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (run.architecture === 'blackboard') {
    const access = run.result?.state?.access_log ?? [];
    const keys = [...new Set(access.map(a => a.key))];
    const who = (key: string, kind: 'read' | 'write') => [...new Set(access.filter(a => a.key === key && a.kind === kind).map(a => a.agent))];
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {flow}
        <div className="st-muted" style={{ fontSize: 12 }}>Blackboard items — who wrote and who read each one</div>
        <table style={{ fontSize: 12, borderCollapse: 'collapse' }}>
          <thead><tr className="st-muted" style={{ textAlign: 'left' }}><th style={{ padding: '2px 12px 2px 0' }}>item</th><th style={{ padding: '2px 12px 2px 0' }}>writers</th><th>readers</th></tr></thead>
          <tbody>{keys.map(k => (
            <tr key={k}><td className="st-mono" style={{ padding: '2px 12px 2px 0' }}><Database size={11} style={{ verticalAlign: -1 }} /> {k}</td>
              <td style={{ padding: '2px 12px 2px 0', color: 'var(--ok)' }}>{who(k, 'write').join(', ') || '—'}</td>
              <td style={{ color: 'var(--info)' }}>{who(k, 'read').join(', ') || '—'}</td></tr>
          ))}</tbody>
        </table>
      </div>
    );
  }
  return flow;
}

// ---------------------------------------------------------------- communication (agent-to-agent vs tool protocols)

function Communication({ run }: { run: AgentRunResponse }) {
  const msgs = (run.result?.coordination_log ?? []).filter(c => c.kind === 'message');
  const a2a = msgs.filter(m => m.data?.protocol === 'a2a' || m.data?.protocol === 'delegation');
  const mcpSpans = (run.result?.trace?.spans ?? []).filter(s => s.kind === 'tool' && s.attributes?.['vexa.transport'] === 'mcp');
  const byServer: Record<string, number> = {};
  mcpSpans.forEach(s => { const k = s.attributes['vexa.mcp_server'] ?? 'mcp'; byServer[k] = (byServer[k] ?? 0) + 1; });
  return (
    <Section title="Communication" hint="agent-to-agent messages (A2A, manager delegation) are kept apart from tool traffic (MCP)">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
          <div className="st-muted" style={{ fontSize: 12, marginBottom: 6 }}>Agent-to-agent ({a2a.length})</div>
          {a2a.length === 0 && <div className="st-faint" style={{ fontSize: 12 }}>No agent-to-agent message in this run.</div>}
          <div style={{ maxHeight: 180, overflow: 'auto' }}>
            {a2a.map(m => (
              <div key={m.seq} style={{ fontSize: 12, marginBottom: 2 }}>
                <span className={`st-pill ${m.data?.protocol === 'a2a' ? 'mock' : ''}`}>{m.data?.protocol}</span> <b>{m.actor}</b> → <b>{m.target}</b>: {m.detail}
              </div>
            ))}
          </div>
        </div>
        <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
          <div className="st-muted" style={{ fontSize: 12, marginBottom: 6 }}>MCP tool calls ({mcpSpans.length})</div>
          {mcpSpans.length === 0 && <div className="st-faint" style={{ fontSize: 12 }}>{run.result?.tool_transport === 'direct' ? 'Tools ran in-process (transport: direct), not over MCP.' : 'No MCP tool call recorded.'}</div>}
          {Object.entries(byServer).map(([srv, n]) => <div key={srv} style={{ fontSize: 12 }}><span className="st-pill run">{srv}</span> {n} call(s)</div>)}
          {(run.result?.mcp_servers ?? []).map(sv => (
            <div key={sv.name} className="st-faint" style={{ fontSize: 11.5, marginTop: 4 }}>{sv.name}: {sv.status} · {sv.tools.length} tools</div>
          ))}
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- agents

function AgentCard({ a, current, selected, onClick }: { a: AgentView; current: boolean; selected: boolean; onClick: () => void }) {
  const blocked = a.guardrails.filter(g => g.decision === 'blocked').length;
  const llmModel = a.llmCalls[0]?.model;
  return (
    <button className={`rv-agent${selected ? ' sel' : ''}${a.status === 'running' ? ' running' : ''}`} onClick={onClick} data-testid="agent-card" data-agent={a.name} data-status={a.status}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Bot size={14} style={{ flex: 'none', color: a.status === 'not_dispatched' ? 'var(--text-faint)' : 'var(--text-strong)' }} />
        <span style={{ fontWeight: 600, color: 'var(--text-strong)', flex: 1 }}>{a.name}</span>
        <StatusDot status={a.status === 'not_dispatched' ? 'idle' : a.status} pulse={a.status === 'running'} />
        <span style={{ fontSize: 11 }} className="st-muted">{STATUS_LABEL[a.status]}{current ? ' · now' : ''}</span>
      </div>
      <div className="st-muted" style={{ fontSize: 11.5, marginTop: 6, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' }}>
        <span>runs {a.invocations}{a.failures ? <span style={{ color: 'var(--err)' }}> · {a.failures} failed</span> : null}</span>
        <span>time {a.invocations ? fmtMs(a.durationMs) : '—'}</span>
        <span>LLM calls {a.llmCalls.length}</span>
        <span>tokens {a.inputTokens != null ? (a.inputTokens + (a.outputTokens ?? 0)).toLocaleString() : 'n/a'}</span>
        <span><Wrench size={10} style={{ verticalAlign: -1 }} /> tools {a.tools.length}</span>
        <span><FilePen size={10} style={{ verticalAlign: -1 }} /> wrote {a.filesWritten.length}</span>
        {a.retries > 0 && <span style={{ color: 'var(--warn)' }}><RotateCcw size={10} style={{ verticalAlign: -1 }} /> retries {a.retries}</span>}
        {blocked > 0 && <span style={{ color: 'var(--err)' }}><ShieldAlert size={10} style={{ verticalAlign: -1 }} /> blocked {blocked}</span>}
      </div>
      {(a.framework || llmModel) && <div className="st-faint" style={{ fontSize: 11, marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{[a.framework, llmModel].filter(Boolean).join(' · ')}</div>}
      {a.status === 'running' && a.lastDetail && <div style={{ fontSize: 11.5, marginTop: 4, color: 'var(--run)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.lastDetail}</div>}
    </button>
  );
}

function AgentDetail({ a, mock }: { a: AgentView; mock: boolean }) {
  return (
    <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 6, padding: 12, background: 'var(--bg-panel)' }} data-testid="agent-detail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Bot size={15} /><b style={{ color: 'var(--text-strong)' }}>{a.name}</b>
        <button className="st-link" style={{ fontSize: 12 }} onClick={() => openAgent(a.name)}>agent profile</button>
        <span className="st-pill">{STATUS_LABEL[a.status]}</span>
        {a.framework && <span className="st-pill">{a.framework}</span>}
        {mock && <span className="st-pill mock">scripted in mock mode</span>}
      </div>
      <div className="rv-kv" style={{ marginBottom: 12 }}>
        <span>first started</span><span>{fmtTime(a.firstStartedAt)}</span>
        <span>last finished</span><span>{fmtTime(a.lastFinishedAt)}</span>
        <span>total time</span><span>{fmtMs(a.durationMs)} over {a.invocations} invocation(s)</span>
        <span>tokens</span><span>{a.inputTokens != null ? `${a.inputTokens.toLocaleString()} in · ${(a.outputTokens ?? 0).toLocaleString()} out` : (a.usageNote ?? 'not reported')}</span>
        <span>state read</span><span className="st-mono">{a.stateReads.join(', ') || '—'}</span>
        <span>state written</span><span className="st-mono">{a.stateWrites.join(', ') || '—'}</span>
        <span>files read</span><span>{a.filesRead.length ? a.filesRead.map(f => <button key={f} className="st-link st-mono" style={{ marginRight: 8 }} onClick={() => openFile(f)}>{f}</button>) : '—'}</span>
        <span>files written</span><span>{a.filesWritten.length ? a.filesWritten.map(f => <button key={f} className="st-link st-mono" style={{ marginRight: 8, color: 'var(--run)' }} onClick={() => openFile(f)}>{f}</button>) : '—'}</span>
      </div>
      {a.errors.length > 0 && <Collapsible title={`Errors (${a.errors.length})`} open>{a.errors.map((e, i) => <pre key={i} className="st-pre" style={{ color: 'var(--err)', marginBottom: 4 }}>{e}</pre>)}</Collapsible>}
      <Collapsible title={`Tool calls (${a.tools.length})`} open={a.tools.length > 0 && a.tools.length <= 12}>
        {a.tools.length === 0 ? <div className="st-faint" style={{ fontSize: 12 }}>none</div> : (
          <table style={{ fontSize: 12, borderCollapse: 'collapse', width: '100%' }}>
            <thead><tr className="st-muted" style={{ textAlign: 'left' }}><th>tool</th><th>transport</th><th>arguments</th><th>status</th><th style={{ textAlign: 'right' }}>time</th></tr></thead>
            <tbody>{a.tools.map(t => (
              <tr key={t.spanId} style={{ borderTop: '1px solid var(--border)' }}>
                <td className="st-mono" style={{ padding: '3px 8px 3px 0' }}>{t.name}</td>
                <td style={{ padding: '3px 8px 3px 0' }}><span className={`st-pill ${t.transport === 'mcp' ? 'run' : t.transport === 'a2a' ? 'mock' : ''}`}>{t.transport}{t.mcpServer ? ` · ${t.mcpServer}` : ''}</span></td>
                <td className="st-mono st-muted" style={{ padding: '3px 8px 3px 0', maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.args}>{t.args ?? ''}</td>
                <td style={{ color: t.status === 'ok' || t.status === 'OK' ? 'var(--ok)' : t.status === 'unset' ? 'var(--text-muted)' : 'var(--err)' }}>{t.status}</td>
                <td style={{ textAlign: 'right' }}>{fmtMs(t.durationMs)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Collapsible>
      <Collapsible title={`LLM calls (${a.llmCalls.length})`}>
        {a.llmCalls.length === 0 ? <div className="st-faint" style={{ fontSize: 12 }}>{mock ? 'none — mock agents do not call a model' : 'none'}</div> :
          a.llmCalls.map((c, i) => <div key={i} style={{ fontSize: 12 }} className="st-mono">{c.model} · {c.inputTokens ?? '?'} in / {c.outputTokens ?? '?'} out · {c.finishReason ?? '—'} · {fmtMs(c.durationMs)} · {c.status}</div>)}
      </Collapsible>
      <Collapsible title={`Guardrail decisions (${a.guardrails.length})`}>
        {a.guardrails.length === 0 ? <div className="st-faint" style={{ fontSize: 12 }}>none recorded for this agent</div> :
          a.guardrails.map(g => <div key={g.seq} style={{ fontSize: 12 }}><span className={`st-pill ${g.decision === 'blocked' ? 'err' : g.decision === 'flagged' ? 'warn' : ''}`}>{g.rule} {g.decision}</span> {g.rule_name}{g.tool ? ` · ${g.tool}` : ''}{g.reason ? ` — ${g.reason}` : ''}</div>)}
      </Collapsible>
      <Collapsible title={`Input — task prompt (${a.inputs.length})`}>
        {a.inputs.length === 0 ? <div className="st-faint" style={{ fontSize: 12 }}>No CrewAI task prompt recorded{mock ? ' (mock agents are scripted and receive no prompt)' : ''}.</div> :
          a.inputs.map((x, i) => <pre key={i} className="st-pre" style={{ marginBottom: 6 }}>{x.text}</pre>)}
      </Collapsible>
      <Collapsible title={`Output (${a.outputs.length})`}>
        {a.outputs.length === 0 ? <div className="st-faint" style={{ fontSize: 12 }}>No raw model output recorded. The structured result is in the State tab.</div> :
          a.outputs.map((x, i) => <pre key={i} className="st-pre" style={{ marginBottom: 6 }}>{prettyJson(x.text)}</pre>)}
      </Collapsible>
      <div className="st-faint" style={{ fontSize: 11, marginTop: 6 }}>Prompts and outputs are redacted by the backend before storage (configured secrets and credential-shaped strings removed).</div>
    </div>
  );
}

function prettyJson(t: string) {
  try { return JSON.stringify(JSON.parse(t), null, 2); } catch { return t; }
}

function Collapsible({ title, open: initial = false, children }: { title: string; open?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(initial);
  return (
    <div style={{ marginTop: 6 }}>
      <div className="st-section" style={{ paddingLeft: 0 }} onClick={() => setOpen(o => !o)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{title}
      </div>
      {open && <div style={{ padding: '4px 0 6px 18px' }}>{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- timeline

const SOURCE_ICON: Record<TimelineItem['source'], React.ReactNode> = {
  agent: <Bot size={12} />, coordination: <Network size={12} />, guardrail: <ShieldAlert size={12} />, callback: <FileText size={12} />,
};

function Timeline({ items }: { items: TimelineItem[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<Set<TimelineItem['source']>>(new Set(['agent', 'coordination', 'guardrail', 'callback']));
  const shown = items.map((it, i) => ({ it, i })).filter(({ it }) => filter.has(it.source));
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }} data-testid="timeline">
      <div style={{ display: 'flex', gap: 6, padding: '6px 12px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        {(['agent', 'coordination', 'guardrail', 'callback'] as const).map(s => (
          <label key={s} style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={filter.has(s)} onChange={() => setFilter(f => { const n = new Set(f); if (n.has(s)) n.delete(s); else n.add(s); return n; })} />
            {s} <span className="st-faint">({items.filter(x => x.source === s).length})</span>
          </label>
        ))}
      </div>
      <div style={{ maxHeight: 420, overflow: 'auto', padding: '4px 0' }}>
        {shown.length === 0 && <div className="st-empty st-muted">No events yet.</div>}
        {shown.map(({ it, i }) => (
          <div key={i}>
            <div className="rv-tl-row" onClick={() => setOpen(o => { const n = new Set(o); if (n.has(i)) n.delete(i); else n.add(i); return n; })}>
              <span className="st-mono st-faint">{isFinite(it.t) ? new Date(it.t).toLocaleTimeString([], { hour12: false }) + '.' + String(new Date(it.t).getMilliseconds()).padStart(3, '0') : '—'}</span>
              <span style={{ color: `var(--${it.tone === 'muted' ? 'text-faint' : it.tone})` }}>{SOURCE_ICON[it.source]}</span>
              <span style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: open.has(i) ? 'normal' : 'nowrap' }}>
                <b style={{ color: 'var(--text-strong)' }}>{it.actor}</b>{it.target ? <> → <b>{it.target}</b></> : null} <span style={{ color: it.tone === 'err' ? 'var(--err)' : it.tone === 'warn' ? 'var(--warn)' : undefined }}>{it.text}</span>
              </span>
            </div>
            {open.has(i) && <pre className="st-pre" style={{ margin: '2px 12px 6px 126px' }}>{JSON.stringify(it.data, null, 2)}</pre>}
          </div>
        ))}
      </div>
    </div>
  );
}
