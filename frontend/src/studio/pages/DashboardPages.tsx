import { useEffect, useMemo, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { useApi, Load, Page, Sec, Stats, Table, ModeTabs, RateBar, num } from '../kit';
import { openAgent, openRun, openGuardrails, openBenchmarks, openEvaluation, useStudio, ensureRun, setState } from '../store';
import { fmtMs, StatusDot } from '../util';
import { agentViews, dispatchSequence } from '../run/runModel';

const ARCHS = ['sequential', 'hierarchical', 'event_driven', 'blackboard'];

export function DashboardPage() {
  const sum = useApi<any>('/dashboard/summary');
  const agents = useApi<any[]>('/agents');
  const sys = useApi<any>('/system/status');
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  return (
    <Page testId="dashboard-page" title="Dashboard" onReload={() => { sum.reload(); agents.reload(); sys.reload(); }}
      subtitle="Everything on this page is aggregated from the run registry on request." actions={<ModeTabs mode={mode} set={setMode} note />}>
      <Load q={sum}>{s => {
        const m = s[mode];
        return (
          <>
            <Sec title="System overview">
              <Stats items={[
                { label: 'Total runs', value: num(m.runs) },
                { label: 'Successful', value: num(m.by_status.success), tone: 'ok', hint: 'run status success (sandbox tests + verification)' },
                { label: 'Partial', value: num(m.by_status.partial), tone: m.by_status.partial ? 'warn' : undefined },
                { label: 'Failed', value: num(m.by_status.failed), tone: m.by_status.failed ? 'err' : undefined },
                { label: 'Interrupted', value: num(m.by_status.interrupted) },
                { label: 'Active runs', value: num(sys.data?.active_runs.length ?? 0), hint: 'running in this backend process' },
                { label: 'Avg run duration', value: fmtMs(m.avg_duration_ms) },
                { label: 'Tokens', value: m.runs_with_usage ? num(m.tokens_total) : 'n/a', hint: `${m.runs_with_usage} run(s) reported usage` },
                { label: 'Benchmark cases', value: s.benchmark_cases, hint: 'task definitions' },
                { label: 'Benchmark runs', value: num(s.experiment_runs), hint: 'executions of cases (real + mock)' },
              ]} />
              <div className="st-faint" style={{ fontSize: 12, marginTop: 6 }}>{s.note}</div>
            </Sec>
            <Sec title="Architecture performance" hint="run status by architecture" right={<button className="st-link" onClick={openBenchmarks}>benchmark comparison <ArrowRight size={12} /></button>}>
              <Table testId="dash-arch" head={['architecture', 'runs', 'run success', 'mean duration', 'mean tokens']} rows={ARCHS.map(a => {
                const x = m.by_architecture[a];
                return [a, x.runs, <RateBar r={x.success} width={100} />, fmtMs(x.avg_duration_ms), x.avg_tokens == null ? 'n/a' : num(x.avg_tokens)];
              })} />
            </Sec>
          </>
        );
      }}</Load>
      <Sec title="Agent performance" hint="executions with no failed invocation / executions" right={<button className="st-link" onClick={() => openEvaluation()}>evaluation criteria <ArrowRight size={12} /></button>}>
        <Load q={agents}>{list => (
          <Table testId="dash-agents" head={['agent', 'executions', 'success', 'failed']} rows={list.map(a => {
            const e = a.executions[mode];
            return [<button className="st-link" onClick={() => openAgent(a.name)}>{a.name}</button>, e?.executions ?? 0,
              e?.executions ? <RateBar r={{ k: e.successful, n: e.executions, rate: e.successful / e.executions, ci95: [null, null] }} width={100} /> : <span className="st-faint">no data</span>,
              e?.failed ?? 0];
          })} />
        )}</Load>
      </Sec>
      <Sec title="System health" right={<button className="st-link" onClick={() => setState({ activity: 'monitoring', sidebarVisible: true })}>monitoring <ArrowRight size={12} /></button>}>
        <Load q={sys}>{st => (
          <Table head={['component', 'status', 'detail']} rows={[
            ['Backend', st.backend.status, `v${st.backend.version}`],
            ['Database', st.database.status, `${st.database.dialect ?? ''} · ${st.database.runs ?? '?'} runs`],
            ['LLM provider', st.llm.status, `${st.llm.model ?? '—'} · reachability not probed`],
            ['MCP servers', st.mcp.status, st.mcp.lifecycle],
            ['A2A verifier', st.a2a.status, st.a2a.url ?? st.a2a.note],
            ['SSE', st.sse.status, st.sse.endpoint],
            ['Workers', 'n/a', 'runs execute in backend threads; there is no separate worker process'],
          ].map(([c, s, d]) => [c, <span><StatusDot status={['ok', 'configured', 'running', 'available'].includes(s) ? 'success' : s === 'n/a' || s === 'not_started' || s === 'no_key' ? 'idle' : 'failed'} /> {s}</span>, <span className="st-faint" style={{ fontSize: 12 }}>{d}</span>])} />
        )}</Load>
        <div style={{ marginTop: 8 }}><button className="st-link" onClick={() => openGuardrails()}>Guardrail decisions <ArrowRight size={12} /></button></div>
      </Sec>
    </Page>
  );
}

/** Two runs side by side: configuration, outcome, dispatch sequence, per-agent metrics, files. */
export function ComparePage({ a, b }: { a: string; b: string }) {
  const runA = useStudio(s => s.runs[a]);
  const runB = useStudio(s => s.runs[b]);
  useEffect(() => { ensureRun(a); ensureRun(b); }, [a, b]);
  const agents = useMemo(() => {
    if (!runA || !runB) return [];
    const va = agentViews(runA), vb = agentViews(runB);
    return [...new Set([...va, ...vb].map(x => x.name))].map(n => [n, va.find(x => x.name === n), vb.find(x => x.name === n)] as const);
  }, [runA, runB]);
  if (!runA || !runB) return <div className="st-empty st-muted">Loading runs…</div>;
  const field = (label: string, f: (r: typeof runA) => React.ReactNode) => [label, f(runA), f(runB)];
  const mismatch = runA.execution_mode !== runB.execution_mode;
  return (
    <Page testId="compare-page" title="Run comparison" subtitle={mismatch ? 'Warning: one run is mock (scripted agents) and the other real — outcomes are not comparable.' : 'Two recorded executions side by side.'}>
      <Sec title="Configuration and outcome">
        <Table head={['', <button className="st-link st-mono" onClick={() => openRun(a)}>{a.slice(0, 8)}</button>, <button className="st-link st-mono" onClick={() => openRun(b)}>{b.slice(0, 8)}</button>]} rows={[
          field('requirement', r => <span style={{ fontSize: 12 }}>{r.result?.requirement}</span>),
          field('workspace', r => r.workspace_id), field('architecture', r => r.architecture), field('mode', r => r.execution_mode),
          field('model', r => r.result?.model ?? '—'), field('prompt variant', r => r.result?.prompt_variant ?? '—'),
          field('status', r => <span><StatusDot status={r.status} /> {r.status}</span>), field('duration', r => fmtMs(r.total_duration_ms)),
          field('tokens', r => r.result?.usage_available ? num(r.result.total_tokens) : 'n/a'),
          field('tests', r => r.result?.final_test_result ? `${r.result.final_test_result.tests_passed}/${r.result.final_test_result.tests_found}` : '—'),
          field('verified', r => r.result?.verification_result ? String(r.result.verification_result.verified) : '—'),
          field('debug iterations', r => r.debug_iterations), field('files changed', r => (r.result?.files_changed ?? []).join(', ') || '—'),
          field('dispatches', r => <span style={{ fontSize: 12 }}>{dispatchSequence(r).map(d => d.agent).join(' → ') || '—'}</span>),
          field('errors', r => <span style={{ fontSize: 12, color: r.errors.length ? 'var(--err)' : undefined }}>{r.errors.join('; ') || '—'}</span>),
        ]} />
      </Sec>
      <Sec title="Agents">
        <Table testId="compare-agents" head={['agent', 'A: status · time · tokens · tools', 'B: status · time · tokens · tools']} rows={agents.map(([n, x, y]) => [
          <button className="st-link" onClick={() => openAgent(n)}>{n}</button>,
          ...[x, y].map(v => v && v.status !== 'not_dispatched' ? `${v.status} · ${fmtMs(v.durationMs)} · ${v.inputTokens != null ? num(v.inputTokens + (v.outputTokens ?? 0)) : 'n/a'} · ${v.tools.length}` : '—'),
        ])} />
      </Sec>
    </Page>
  );
}
