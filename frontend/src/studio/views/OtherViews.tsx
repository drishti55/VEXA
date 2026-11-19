import { useEffect, useState } from 'react';
import { Square, TestTube2, FileText, FlaskConical, RefreshCw, Bot, Blocks, Gauge, ShieldCheck, LayoutDashboard, Search } from 'lucide-react';
import { VexaApi } from '../../api/client';
import type { Experiment, SystemStatus } from '../../api/client';
import { useStudio, useLiveRuns, openTab, openRun, toast, setState, openAgent, openEvaluation, openBenchmarks, openCase, openExtension, openGuardrails, openDashboard } from '../store';
import { runInTerminal } from '../BottomPanel';
import { StatusDot, timeAgo } from '../util';
import { useApi } from '../kit';
import { ReportsNav } from './ReportsNav';

function Head({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="st-head"><span className="title">{title}</span>{children}</div>;
}

export const openExperimentsTab = () => openTab({ id: 'experiments', kind: 'experiments', title: 'Experiments' });

function QuickItem({ icon, label, hint, onClick, disabled, testId }: { icon: React.ReactNode; label: string; hint: string; onClick: () => void; disabled?: boolean; testId?: string }) {
  return (
    <button className="st-row" disabled={disabled} onClick={onClick} data-testid={testId}
      style={{ width: '100%', height: 'auto', padding: '6px 14px', background: 'transparent', textAlign: 'left', opacity: disabled ? .45 : 1, cursor: disabled ? 'default' : 'pointer' }}>
      {icon}<span style={{ flex: 1 }}><div>{label}</div><div className="st-faint" style={{ fontSize: 11.5 }}>{hint}</div></span>
    </button>
  );
}

/** Run and Debug: quick actions that go through existing, restricted backend endpoints. */
export function RunDebugView() {
  const workspaceId = useStudio(s => s.workspaceId);
  const live = useLiveRuns().filter(r => r.status === 'running');
  const latest = useStudio(s => s.recentRuns.find(r => r.workspace_id === s.workspaceId && r.status !== 'running'));
  const stop = async (id: string) => {
    try { await VexaApi.cancelAgentRun(id); toast('Cancellation requested.'); } catch (e: any) { toast(e.message, 'error'); }
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Run and Debug" />
      <div className="st-scroll">
        <QuickItem icon={<Bot size={16} />} label="Start agent workflow" hint="focus the composer in the Agent Runs panel" disabled={!workspaceId}
          onClick={() => { setState({ rightVisible: true }); setTimeout(() => (document.querySelector('[data-testid=requirement]') as HTMLElement | null)?.focus(), 0); }} />
        <QuickItem icon={<TestTube2 size={16} />} label="Run tests" hint="pytest in the workspace sandbox" disabled={!workspaceId} onClick={() => runInTerminal('pytest')} testId="quick-run-tests" />
        {live.map(r => <QuickItem key={r.run_id} icon={<Square size={16} style={{ color: 'var(--err)' }} />} label={`Stop run ${r.run_id.slice(0, 8)}`} hint={r.result?.requirement?.slice(0, 60) ?? ''} onClick={() => stop(r.run_id)} />)}
        <QuickItem icon={<FileText size={16} />} label="Open latest execution report" hint={latest ? `run ${latest.run_id.slice(0, 8)} · ${latest.status}` : 'no finished run in this workspace'}
          disabled={!latest} onClick={() => latest && openRun(latest.run_id)} />
        <QuickItem icon={<FlaskConical size={16} />} label="Run a benchmark experiment" hint="configure and start it on the Experiments page" onClick={openExperimentsTab} />
        <div className="st-empty st-muted" style={{ fontSize: 12 }}>
          VEXA has no step debugger. A run is observed through its events, coordination log, spans and guardrail decisions (bottom panel and the run tab).
        </div>
      </div>
    </div>
  );
}

export function ExperimentsView() {
  const [list, setList] = useState<Experiment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => VexaApi.listExperiments().then(l => { setList(l); setError(null); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Experiments"><button className="st-icon-btn" title="Refresh" onClick={load}><RefreshCw size={14} /></button></Head>
      <div style={{ padding: '0 10px 8px' }}><button className="st-btn block" onClick={openExperimentsTab} data-testid="open-experiments">Open Experiments</button></div>
      <div className="st-scroll">
        {error && <div className="st-empty st-error">{error}</div>}
        {list && list.length === 0 && <div className="st-empty st-muted">No experiment has been run.</div>}
        {list?.map(x => (
          <div key={x.experiment_id} className="st-row" style={{ height: 'auto', padding: '5px 12px', alignItems: 'flex-start' }} onClick={openExperimentsTab} title={x.experiment_id}>
            <span style={{ paddingTop: 5 }}><StatusDot status={x.status === 'completed' ? 'success' : x.status === 'running' ? 'running' : x.status === 'failed' ? 'failed' : 'interrupted'} /></span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="name" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{x.name}</div>
              <div className="st-faint" style={{ fontSize: 11.5 }}>{x.status} · {x.run_count} runs · {x.config?.execution_mode ?? '?'} · {timeAgo(x.created_at)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function StatusRow({ label, status, detail }: { label: string; status: string; detail?: React.ReactNode }) {
  return (
    <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <StatusDot status={['ok', 'configured', 'running', 'available'].includes(status) ? 'success' : ['not_started', 'no_key', 'not_probed'].includes(status) ? 'idle' : 'failed'} />
        <b style={{ flex: 1 }}>{label}</b><span className="st-muted" style={{ fontSize: 12 }}>{status.replace('_', ' ')}</span>
      </div>
      {detail && <div className="st-faint" style={{ fontSize: 11.5, marginTop: 2, paddingLeft: 14 }}>{detail}</div>}
    </div>
  );
}

/** Monitoring: the same /system/status the status bar reads, in full. */
export function MonitoringView() {
  const [st, setSt] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => VexaApi.systemStatus().then(s => { setSt(s); setError(null); }).catch(e => setError(e.message));
  useEffect(() => { load(); const t = setInterval(load, 10_000); return () => clearInterval(t); }, []);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Monitoring"><button className="st-icon-btn" title="Refresh" onClick={load}><RefreshCw size={14} /></button></Head>
      <div className="st-scroll" data-testid="monitoring">
        {error && <StatusRow label="Backend" status="unreachable" detail={error} />}
        {st && (
          <>
            <StatusRow label="Backend" status={st.backend.status} detail={`v${st.backend.version} · ${st.backend.environment}`} />
            <StatusRow label="Database" status={st.database.status} detail={st.database.status === 'ok' ? `${st.database.dialect} · ${st.database.runs} runs · ${st.database.experiments} experiments` : st.database.error} />
            <StatusRow label="LLM provider" status={st.llm.status} detail={<>{st.llm.model ? `${st.llm.model} (${st.llm.provider})` : 'no model configured'} · key {st.llm.status === 'configured' ? `from ${st.llm.key_source}` : 'missing'}<br />reachability is not probed automatically — use “Test model” in the run options</>} />
            <StatusRow label="A2A verifier" status={st.a2a.status} detail={st.a2a.url ?? st.a2a.note} />
            <StatusRow label="MCP servers" status={st.mcp.status} detail={<>{st.mcp.lifecycle}<br />{st.mcp.servers.map(s => `${s.name}${s.configured ? '' : ' (not configured)'}`).join(' · ')}</>} />
            <StatusRow label="Live updates (SSE)" status={st.sse.status} detail={st.sse.endpoint} />
            <StatusRow label="Sandbox" status="ok" detail={`backend: ${st.sandbox.backend}`} />
            <StatusRow label="Activity" status="ok" detail={`${st.active_runs.length} active run(s) · ${st.active_experiments.length} active experiment(s)`} />
            <div className="st-faint" style={{ padding: '6px 14px', fontSize: 11.5 }}>checked {new Date(st.checked_at).toLocaleTimeString()} · refreshes every 10 s · database operations are not instrumented with spans</div>
          </>
        )}
        <MonitoringLinks />
      </div>
    </div>
  );
}


function NavRow({ icon, label, detail, onClick, testId }: { icon: React.ReactNode; label: string; detail?: React.ReactNode; onClick: () => void; testId?: string }) {
  return (
    <div className="st-row" style={{ height: 'auto', padding: '5px 12px', alignItems: 'flex-start' }} onClick={onClick} data-testid={testId}>
      <span style={{ paddingTop: 1 }}>{icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="name">{label}</div>
        {detail && <div className="st-faint" style={{ fontSize: 11.5, whiteSpace: 'normal' }}>{detail}</div>}
      </div>
    </div>
  );
}

export function AgentsView() {
  const q = useApi<any[]>('/agents');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Agents"><button className="st-icon-btn" title="Refresh" onClick={q.reload}><RefreshCw size={14} /></button></Head>
      <div className="st-scroll">
        {q.error && <div className="st-empty st-error">{q.error}</div>}
        {q.data?.map(a => {
          const r = a.executions.real;
          return <NavRow key={a.name} testId="agent-row" icon={<Bot size={15} />} label={a.name} onClick={() => openAgent(a.name)}
            detail={<>{a.role}<br />{a.tool_count} tools · {a.can_write_files ? 'writes files' : 'read-only'} · real {r ? `${r.successful}/${r.executions} ok` : 'no runs'}{a.architectures.length < 4 ? ` · ${a.architectures.join(', ')} only` : ''}</>} />;
        })}
      </div>
    </div>
  );
}

export function EvaluationView() {
  return <ReportsNav title="Evaluation" />;
}

export function BenchmarksView() {
  const q = useApi<any[]>('/benchmarks/cases');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Benchmarks"><button className="st-icon-btn" title="Refresh" onClick={q.reload}><RefreshCw size={14} /></button></Head>
      <div style={{ padding: '0 10px 8px' }}><button className="st-btn block" onClick={openBenchmarks} data-testid="open-benchmarks">Overview and comparison</button></div>
      <div className="st-scroll">
        {q.error && <div className="st-empty st-error">{q.error}</div>}
        {q.data && <div className="st-muted" style={{ padding: '0 14px 6px', fontSize: 12 }}>{q.data.length} cases</div>}
        {q.data?.map(c => (
          <NavRow key={c.id} testId="case-row" icon={<TestTube2 size={15} />} label={c.title} onClick={() => openCase(c.id)}
            detail={`${c.category} · ${c.difficulty} · real ${c.results.real.all.n ? `${c.results.real.all.k}/${c.results.real.all.n} solved` : 'not run'} · mock ${c.results.mock.all.n}`} />
        ))}
      </div>
    </div>
  );
}

export function ExtensionsView() {
  const q = useApi<any>('/extensions');
  const [filter, setFilter] = useState('');
  const list = (q.data?.extensions ?? []).filter((e: any) => !filter || `${e.name} ${e.purpose} ${e.paths.join(' ')}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Extensions"><button className="st-icon-btn" title="Refresh" onClick={q.reload}><RefreshCw size={14} /></button></Head>
      <div style={{ padding: '0 8px 8px', position: 'relative' }}>
        <input className="st-input" placeholder="Search VEXA modules" value={filter} onChange={e => setFilter(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', paddingRight: 26 }} />
        <Search size={14} className="st-faint" style={{ position: 'absolute', right: 16, top: 7 }} />
      </div>
      <div className="st-section" style={{ paddingLeft: 12 }}><span style={{ flex: 1 }}>INSTALLED</span><span className="st-badge">{q.data?.extensions.length ?? 0}</span></div>
      <div className="st-scroll">
        {q.error && <div className="st-empty st-error">{q.error}</div>}
        {list.map((e: any) => (
          <div key={e.id} className="st-row" data-testid="extension-row" style={{ height: 'auto', padding: '8px 12px', alignItems: 'flex-start', gap: 10 }} onClick={() => openExtension(e.id, e.name)}>
            <span style={{ width: 36, height: 36, borderRadius: 6, background: 'var(--bg-active)', display: 'grid', placeItems: 'center', flex: 'none' }}>
              {e.id === 'guardrails' ? <ShieldCheck size={18} /> : e.id.includes('agent') || e.id === 'adk-verifier' ? <Bot size={18} /> : <Blocks size={18} />}
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', gap: 6 }}><b className="name" style={{ color: 'var(--text-strong)' }}>{e.name}</b><span className="st-faint" style={{ fontSize: 11 }}>{e.version}</span></div>
              <div className="st-muted" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.purpose || e.paths.join(', ')}</div>
              <div className="st-faint" style={{ fontSize: 11.5 }}>{e.paths[0]} · {e.files} files · {e.lines.toLocaleString()} lines · {e.status}</div>
            </div>
          </div>
        ))}
        <div className="st-empty st-faint" style={{ fontSize: 11.5 }}>{q.data?.note}</div>
      </div>
    </div>
  );
}

export function MonitoringLinks() {
  return (
    <div style={{ borderTop: '1px solid var(--border)', paddingTop: 4 }}>
      <NavRow icon={<LayoutDashboard size={15} />} label="Dashboard" onClick={openDashboard} testId="open-dashboard" />
      <NavRow icon={<ShieldCheck size={15} />} label="Guardrails G1–G10" onClick={() => openGuardrails()} testId="open-guardrails" />
      <NavRow icon={<Gauge size={15} />} label="Failure clusters and models" onClick={() => openEvaluation()} />
    </div>
  );
}
