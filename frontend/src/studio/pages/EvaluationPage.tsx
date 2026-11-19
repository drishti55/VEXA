import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { useApi, Load, Page, Sec, Spark, Table, ModeTabs, RateBar, num, pct } from '../kit';
import { openAgent, openRun } from '../store';
import { fmtMs } from '../util';

const AGENTS = ['RequirementAnalyst', 'ProjectAnalyst', 'Planner', 'Coder', 'Tester', 'Debugger', 'Verifier', 'Manager'];

const STATUS: Record<string, [string, string]> = {
  evaluated: ['Evaluated', 'ok'], insufficient_data: ['Insufficient data', 'warn'], no_data: ['No data yet', ''], not_evaluated: ['Not Evaluated', 'err'],
};

export function EvaluationPage({ agent }: { agent?: string }) {
  const [selected, setSelected] = useState<string>(agent ?? 'Verifier');
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  useEffect(() => { if (agent) setSelected(agent); }, [agent]); // opened from an agent profile
  const shown = selected;
  const q = useApi<any>('/evaluation/agents');
  return (
    <Page testId="evaluation-page" onReload={q.reload} title="Agent evaluation"
      subtitle="Each criterion is computed from persisted runs and the independent hidden-test grader. Nothing is LLM-scored and nothing is stored: refresh to recompute."
      actions={<ModeTabs mode={mode} set={setMode} note />}>
      <Load q={q}>{d => {
        const crit = d.criteria.filter((c: any) => c.agent === shown);
        return (
          <>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
              {AGENTS.map(a => {
                const cs = d.criteria.filter((c: any) => c.agent === a);
                const ev = cs.filter((c: any) => c.status === 'evaluated').length;
                return (
                  <button key={a} className={`st-pill ${a === shown ? 'run' : ''}`} style={{ cursor: 'pointer', height: 26, fontSize: 12 }}
                    onClick={() => setSelected(a)} data-testid={`eval-agent-${a}`}>
                    {a} <span className="st-faint">{ev}/{cs.length}</span>
                  </button>
                );
              })}
            </div>
            <div className="st-faint" style={{ fontSize: 12, marginTop: 6 }}>{d.runs.real} real and {d.runs.mock} mock runs in the registry · scores below {d.min_sample} observations are flagged “insufficient data” · <button className="st-link" onClick={() => openAgent(shown)}>open {shown}'s anatomy</button></div>
            <Sec title={`${shown} — ${crit.length} criteria`}>
              <div style={{ display: 'grid', gap: 8 }} data-testid="criteria">
                {crit.map((c: any) => <CriterionCard key={c.id} c={c} mode={mode} />)}
              </div>
            </Sec>
            <ModelComparison />
            <FailureClusters mode={mode} />
          </>
        );
      }}</Load>
    </Page>
  );
}

function CriterionCard({ c, mode }: { c: any; mode: 'real' | 'mock' }) {
  const [open, setOpen] = useState(false);
  const r = c[mode];
  const status = mode === 'real' ? c.status : c.status === 'not_evaluated' ? 'not_evaluated' : r?.n ? 'evaluated' : 'no_data';
  const [label, tone] = STATUS[status];
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px', background: 'var(--bg-inset)' }} data-testid="criterion" data-status={status}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1.4fr) 1fr 130px auto', gap: 12, alignItems: 'center' }}>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-strong)' }}>{c.name}</div>
          <div className="st-faint" style={{ fontSize: 11.5 }}>{c.kind === 'heuristic' ? 'heuristic measurement' : c.kind === 'deterministic' ? 'deterministic measurement' : 'no valid measurement method yet'}{!c.higher_is_better && ' · lower is better'}</div>
        </div>
        <div>
          {c.status === 'not_evaluated' ? <span className="st-muted" style={{ fontSize: 12 }}>—</span> :
            !r?.n ? <span className="st-faint">no observations</span> :
              c.value === 'rate' ? <RateBar r={{ k: r.successes, n: r.n, rate: r.score, ci95: r.ci95 }} invert={!c.higher_is_better} /> :
                <span style={{ fontVariantNumeric: 'tabular-nums' }}><b>{c.id === 'db.iterations' ? num(r.score, 2) : pct(r.score, 1)}</b> <span className="st-faint">mean · n={r.n}{r.sd != null ? ` · sd ${c.id === 'db.iterations' ? num(r.sd, 2) : pct(r.sd, 1)}` : ''}</span></span>}
        </div>
        <div>{r?.trend ? <Spark points={r.trend} asPct={c.id !== 'db.iterations'} /> : null}</div>
        <span className={`st-pill ${tone}`}>{label}</span>
      </div>
      {c.status === 'not_evaluated' && <div style={{ fontSize: 12, marginTop: 6 }}><Info size={12} style={{ verticalAlign: -2 }} /> {c.missing}</div>}
      {mode === 'real' && c.status === 'no_data' && c.missing && <div className="st-muted" style={{ fontSize: 12, marginTop: 6 }}>{c.missing}</div>}
      <button className="st-link" style={{ fontSize: 12, marginTop: 6 }} onClick={() => setOpen(o => !o)}>{open ? 'Hide' : 'Show'} definition and method</button>
      {open && (
        <div className="rv-kv" style={{ marginTop: 6, gridTemplateColumns: '120px 1fr' }}>
          <span>Definition</span><span>{c.definition}</span>
          <span>Method</span><span>{c.method}</span>
          <span>Formula</span><span className="st-mono">{c.formula}</span>
          <span>Data source</span><span>{c.data_source}</span>
          {r?.n ? <><span>Sample</span><span>n={r.n}{r.successes != null && <> · {r.successes} successful · {r.failures} failed</>}</span>
            <span>Runs</span><span>{r.runs.slice(-12).map((id: string) => <button key={id} className="st-link st-mono" style={{ marginRight: 6 }} onClick={() => openRun(id)}>{id.slice(0, 8)}</button>)}</span></> : null}
        </div>
      )}
    </div>
  );
}

function ModelComparison() {
  const q = useApi<any>('/evaluation/models');
  return (
    <Sec title="Model comparison across agents" hint="real runs only — per model and agent, from the agent_runs table">
      <Load q={q} empty={d => !d.rows.length}>{d => (
        <Table testId="model-table" head={['model', 'agent', 'executions', 'success', 'error rate', 'avg time', 'avg tokens', 'LLM calls', 'retries']}
          rows={d.rows.map((r: any) => [<span className="st-mono" style={{ fontSize: 12 }}>{r.model}</span>, r.agent, r.executions,
            <RateBar r={r.success} width={80} />, pct(r.error_rate, 0), fmtMs(r.avg_duration_ms), r.avg_tokens == null ? 'n/a' : num(r.avg_tokens), r.llm_calls, r.validation_retries])} />
      )}</Load>
    </Sec>
  );
}

function FailureClusters({ mode }: { mode: 'real' | 'mock' }) {
  const q = useApi<any>(`/evaluation/failures?mode=${mode}`);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Sec title="Failure clusters" hint={q.data?.method}>
      <Load q={q}>{d => (
        <>
          <div className="st-muted" style={{ fontSize: 12, marginBottom: 8 }}>{d.failed_runs} of {d.runs} {mode} runs failed · by category: {Object.entries(d.by_category).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}</div>
          {d.clusters.length === 0 && <div className="st-muted">No failures recorded.</div>}
          {d.clusters.slice(0, 25).map((c: any) => (
            <div key={c.signature} style={{ borderTop: '1px solid var(--border)', padding: '6px 0' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', cursor: 'pointer' }} onClick={() => setOpen(o => o === c.signature ? null : c.signature)}>
                <b style={{ minWidth: 28, fontVariantNumeric: 'tabular-nums' }}>{c.occurrences}×</b>
                <span className="st-pill">{c.category}</span>
                <span className="st-mono" style={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.signature}</span>
                <span className="st-faint" style={{ fontSize: 11.5 }}>{c.run_count} run(s)</span>
              </div>
              {open === c.signature && (
                <div style={{ paddingLeft: 36, marginTop: 4, fontSize: 12 }}>
                  <pre className="st-pre">{c.example}</pre>
                  <div className="st-muted" style={{ marginTop: 4 }}>sources: {Object.entries(c.sources).map(([k, v]) => `${k} ${v}`).join(', ')} · architectures: {Object.entries(c.architectures).map(([k, v]) => `${k} ${v}`).join(', ')}</div>
                  <div>{c.runs.map((id: string) => <button key={id} className="st-link st-mono" style={{ marginRight: 6 }} onClick={() => openRun(id)}>{id.slice(0, 8)}</button>)}</div>
                </div>
              )}
            </div>
          ))}
        </>
      )}</Load>
    </Sec>
  );
}
