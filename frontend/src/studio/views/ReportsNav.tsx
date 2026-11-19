import { useState } from 'react';
import { RefreshCw, LayoutDashboard, FlaskConical, ListChecks, Gauge, ShieldCheck, Bot, ChevronRight, ChevronDown, TestTube2, Microscope, FileText } from 'lucide-react';
import { useStudio, openDashboard, openBenchmarks, openEvaluation, openGuardrails, openAgent, openCase, openRun } from '../store';
import { openExperimentsTab } from './OtherViews';
import { StatusDot, timeAgo, runRequirement, runStartedAt } from '../util';
import { useApi } from '../kit';

const AGENTS = ['RequirementAnalyst', 'ProjectAnalyst', 'Planner', 'Coder', 'Tester', 'Debugger', 'Verifier', 'Manager'];

function Group({ title, count, children, open: initial = true, testId }: { title: string; count?: React.ReactNode; children: React.ReactNode; open?: boolean; testId?: string }) {
  const [open, setOpen] = useState(initial);
  return (
    <div data-testid={testId}>
      <div className="st-section" style={{ paddingLeft: 6 }} onClick={() => setOpen(o => !o)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span style={{ flex: 1 }}>{title}</span>
        {count != null && <span className="st-faint" style={{ fontWeight: 400 }}>{count}</span>}
      </div>
      {open && children}
    </div>
  );
}

function Item({ icon, label, detail, onClick, active, testId, extra }: { icon: React.ReactNode; label: React.ReactNode; detail?: React.ReactNode;
  onClick: () => void; active?: boolean; testId?: string; extra?: React.ReactNode }) {
  return (
    <div className={`st-row${active ? ' selected' : ''}`} style={{ height: 'auto', padding: '4px 10px 4px 22px', alignItems: 'flex-start' }} onClick={onClick} data-testid={testId}>
      <span style={{ paddingTop: 1, flex: 'none' }}>{icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
        {detail && <div className="st-faint" style={{ fontSize: 11.5, whiteSpace: 'normal' }}>{detail}</div>}
      </div>
      {extra}
    </div>
  );
}

const pct = (k: number, n: number) => (n ? `${Math.round((k / n) * 100)}%` : '—');

/**
 * Index of every evaluation and report the backend computes: project-level (dashboard, experiments,
 * benchmarks, architecture comparison, criteria, guardrails), per agent, per benchmark case, per run.
 * Counts come straight from the API; nothing here is computed from fixtures.
 */
export function ReportsNav({ title = 'Reports & Evaluation' }: { title?: string }) {
  const activeTabId = useStudio(s => s.activeTabId);
  const recentRuns = useStudio(s => s.recentRuns);
  const evalAgent = useStudio(s => { const t = s.tabs.find(x => x.id === 'evaluation'); return t?.kind === 'evaluation' ? t.agent ?? '' : null; });
  const dash = useApi<any>('/dashboard/summary');
  const ev = useApi<any>('/evaluation/agents');
  const cases = useApi<any[]>('/benchmarks/cases');
  const exps = useApi<any[]>('/experiments');
  const guards = useApi<any>('/guardrails');
  const reload = () => { dash.reload(); ev.reload(); cases.reload(); exps.reload(); guards.reload(); };

  const real = dash.data?.real;
  const ok = real?.by_status?.success ?? 0;
  const criteria: any[] = ev.data?.criteria ?? [];
  const n = (cs: any[], st: string) => cs.filter(c => c.status === st).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} data-testid="reports-nav">
      <div className="st-head"><span className="title">{title}</span>
        <button className="st-icon-btn" title="Refresh" onClick={reload}><RefreshCw size={14} /></button></div>
      <div className="st-scroll" style={{ paddingBottom: 12 }}>
        <Group title="PROJECT EVALUATION" testId="nav-project">
          <Item icon={<LayoutDashboard size={15} />} label="Overview dashboard" active={activeTabId === 'dashboard'} onClick={openDashboard} testId="nav-dashboard"
            detail={real ? `${real.runs} real runs · ${pct(ok, real.runs)} success · ${(dash.data?.mock?.runs ?? 0)} mock` : dash.error ?? '…'} />
          <Item icon={<FlaskConical size={15} />} label="Experiments" active={activeTabId === 'experiments'} onClick={openExperimentsTab} testId="nav-experiments"
            detail={exps.data ? `${exps.data.length} experiments · ${exps.data.filter(e => e.status === 'running' || e.active).length} running` : exps.error ?? '…'} />
          <Item icon={<ListChecks size={15} />} label="Benchmarks & architecture comparison" active={activeTabId === 'benchmarks'} onClick={openBenchmarks} testId="nav-benchmarks"
            detail={cases.data ? `${cases.data.length} cases · ${cases.data.filter(c => c.results.real.all.n).length} with real results` : cases.error ?? '…'} />
          <Item icon={<Gauge size={15} />} label="All criteria, models & failures" active={activeTabId === 'evaluation' && evalAgent === ''} onClick={() => openEvaluation()} testId="nav-criteria"
            detail={ev.data ? `${criteria.length} criteria · ${n(criteria, 'evaluated')} evaluated · ${n(criteria, 'not_evaluated')} not evaluated` : ev.error ?? '…'} />
          <Item icon={<ShieldCheck size={15} />} label="Guardrails G1–G10" active={activeTabId === 'guardrails'} onClick={() => openGuardrails()} testId="nav-guardrails"
            detail={guards.data ? `${guards.data.guardrails?.length ?? 0} guardrails · decisions per run` : guards.error ?? '…'} />
        </Group>

        <Group title="AGENT EVALUATION" count={AGENTS.length} testId="nav-agents">
          {AGENTS.map(a => {
            const cs = criteria.filter(c => c.agent === a);
            return (
              <Item key={a} icon={<Bot size={15} />} label={a} active={activeTabId === 'evaluation' && evalAgent === a} onClick={() => openEvaluation(a)} testId={`nav-agent-${a}`}
                detail={ev.data ? `${cs.length} criteria · ${n(cs, 'evaluated')} evaluated · ${n(cs, 'insufficient_data')} small sample · ${n(cs, 'no_data') + n(cs, 'not_evaluated')} no data / not evaluated` : '…'}
                extra={<button className="st-icon-btn" title={`${a} anatomy: prompt, tools, internal architecture, history`}
                  onClick={e => { e.stopPropagation(); openAgent(a); }}><Microscope size={14} /></button>} />
            );
          })}
        </Group>

        <Group title="RUN REPORTS" count={recentRuns.length} open={false} testId="nav-runs">
          {recentRuns.length === 0 && <div className="st-faint" style={{ padding: '4px 22px', fontSize: 12 }}>No runs yet.</div>}
          {recentRuns.slice(0, 40).map(r => (
            <Item key={r.run_id} icon={<span style={{ paddingTop: 4, display: 'block' }}><StatusDot status={r.status} /></span>} label={runRequirement(r)}
              active={activeTabId === `run:${r.run_id}`} onClick={() => openRun(r.run_id)}
              detail={`${r.workspace_id} · ${r.architecture} · ${r.execution_mode} · ${timeAgo(runStartedAt(r))}`} />
          ))}
        </Group>

        <Group title="BENCHMARK CASES" count={cases.data?.length} open={false} testId="nav-cases">
          {cases.data?.map(c => (
            <Item key={c.id} icon={<TestTube2 size={15} />} label={c.title} active={activeTabId === `case:${c.id}`} onClick={() => openCase(c.id)}
              detail={`${c.category} · ${c.difficulty} · real ${c.results.real.all.n ? `${c.results.real.all.k}/${c.results.real.all.n} solved` : 'not run'}`} />
          ))}
        </Group>

        <div className="st-faint" style={{ padding: '10px 14px 0', fontSize: 11.5, lineHeight: 1.45, display: 'flex', gap: 6 }}>
          <FileText size={13} style={{ flex: 'none', marginTop: 1 }} />
          <span>Every number here is computed by the backend from persisted runs. Criteria without enough data say so instead of showing a score.</span>
        </div>
      </div>
    </div>
  );
}
