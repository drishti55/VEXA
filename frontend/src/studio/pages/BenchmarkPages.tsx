import { useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { useApi, Load, Page, Sec, Stats, Table, ModeTabs, RateBar, SourceLink, num, pct } from '../kit';
import { openCase, openRun, openSource } from '../store';
import { fmtMs, timeAgo, StatusDot } from '../util';
import { DiffView } from '../run/DiffView';

const ARCHS = ['sequential', 'hierarchical', 'event_driven', 'blackboard'];

export function BenchmarksPage() {
  const ov = useApi<any>('/benchmarks/overview');
  const cases = useApi<any[]>('/benchmarks/cases');
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  const [model, setModel] = useState('');
  const cmp = useApi<any>(`/benchmarks/compare?mode=${mode}${model ? `&model=${encodeURIComponent(model)}` : ''}`);
  return (
    <Page testId="benchmarks-page" title="Benchmarks and experiments" onReload={() => { ov.reload(); cases.reload(); cmp.reload(); }}
      subtitle="A case is a task definition with hidden tests and a reference solution; a run is one execution of a case. The two are never added together.">
      <Load q={ov}>{o => (
        <Sec title="Overview">
          <Stats items={[
            { label: 'Datasets', value: o.datasets.length, hint: o.datasets.map((d: any) => d.id).join(', ') },
            { label: 'Benchmark cases', value: o.total_cases, hint: o.datasets[0]?.categories.join(', ') },
            { label: 'Experiments', value: o.experiments.total, hint: Object.entries(o.experiments.by_status).map(([k, v]) => `${k} ${v}`).join(' · ') },
            { label: 'Experiment runs', value: num(o.experiment_runs.total), hint: 'runs linked to an experiment' },
            { label: 'Real benchmark runs', value: o.benchmark_runs.real.runs, hint: Object.entries(o.benchmark_runs.real.by_status).map(([k, v]) => `${k} ${v}`).join(' · ') },
            { label: 'Mock benchmark runs', value: o.benchmark_runs.mock.runs, hint: 'scripted agents' },
            { label: 'Pending', value: o.experiment_runs.pending, hint: o.experiment_runs.definitions.pending },
            { label: 'Skipped', value: o.experiment_runs.skipped, hint: o.experiment_runs.definitions.skipped + (o.experiment_runs.plan_unknown_for.length ? ` · plan unknown for ${o.experiment_runs.plan_unknown_for.length} older experiment(s)` : '') },
            { label: 'Evaluation coverage', value: pct(o.evaluation_coverage.rate), hint: `${o.evaluation_coverage.graded_runs}/${o.evaluation_coverage.benchmark_runs} runs graded · ${o.evaluation_coverage.cases_with_real_results}/${o.evaluation_coverage.cases} cases have real-model results` },
            { label: 'Last execution', value: o.last_execution ? timeAgo(o.last_execution) : '—', hint: o.last_execution?.slice(0, 19).replace('T', ' ') },
          ]} />
        </Sec>
      )}</Load>

      <Sec title="Cases" hint="task success = all hidden and visible tests pass, judged by the independent grader">
        <Load q={cases}>{cs => (
          <Table testId="cases-table" head={['case', 'category', 'difficulty', 'criteria', 'real · all architectures', 'mock']}
            rows={cs.map(c => [
              <button className="st-link" onClick={() => openCase(c.id)}>{c.title}</button>, c.category, c.difficulty, c.acceptance_criteria,
              <RateBar r={c.results.real.all} width={90} />, <RateBar r={c.results.mock.all} width={60} />,
            ])} />
        )}</Load>
      </Sec>

      <Sec title="Architecture comparison" hint="same cases, graded runs only" right={<ModeTabs mode={mode} set={setMode} note />}>
        <Load q={cmp}>{d => (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
              <span className="st-muted" style={{ fontSize: 12 }}>Model</span>
              <select className="st-select" value={model} onChange={e => setModel(e.target.value)}>
                <option value="">all ({d.models.length})</option>
                {d.models.map((m: string) => <option key={m}>{m}</option>)}
              </select>
              {d.warnings.map((w: string) => <span key={w} className="st-pill warn"><AlertTriangle size={11} />{w}</span>)}
            </div>
            <Table testId="compare-table" head={['metric', ...ARCHS]} rows={[
              ['graded runs', ...ARCHS.map(a => <span>{d.architectures[a].runs} <span className="st-faint">({d.architectures[a].cases} cases)</span>{d.architectures[a].sample !== 'ok' && <span className="st-pill warn" style={{ marginLeft: 4 }}>{d.architectures[a].sample}</span>}</span>)],
              ['task success (hidden tests)', ...ARCHS.map(a => <RateBar r={d.architectures[a].task_success} width={80} />)],
              ['verification pass', ...ARCHS.map(a => <RateBar r={d.architectures[a].verification_pass} width={80} />)],
              ['sandbox test pass', ...ARCHS.map(a => <RateBar r={d.architectures[a].test_pass} width={80} />)],
              ['run failed', ...ARCHS.map(a => <RateBar r={d.architectures[a].run_failed} width={80} invert />)],
              ['acceptance coverage (heuristic)', ...ARCHS.map(a => pct(d.architectures[a].acceptance_coverage.mean))],
              ['mean duration', ...ARCHS.map(a => fmtMs(d.architectures[a].duration_ms.mean))],
              ['mean tokens', ...ARCHS.map(a => d.architectures[a].tokens.runs_with_usage ? num(d.architectures[a].tokens.mean) : 'n/a')],
              ['mean tool calls', ...ARCHS.map(a => num(d.architectures[a].tool_calls.mean, 1))],
              ['mean retries', ...ARCHS.map(a => num(d.architectures[a].retries.mean, 1))],
              ['cost', ...ARCHS.map(a => d.architectures[a].cost_usd.runs_with_cost ? `$${d.architectures[a].cost_usd.mean.toFixed(4)}` : <span className="st-faint">{d.architectures[a].cost_usd.label}</span>)],
            ]} />
            <div style={{ marginTop: 10 }}>
              {Object.entries(d.differences).map(([k, v]: [string, any]) => (
                <div key={k} style={{ fontSize: 12.5 }}>
                  <b>{k.replace('_minus_', ' − ')}</b> task success: {v.diff == null ? 'n/a' : `${(v.diff * 100).toFixed(0)} pts`} (95% CI {pct(v.low)} to {pct(v.high)}) — <span className="st-muted">{v.interpretation}</span>
                </div>
              ))}
              <div className="st-faint" style={{ fontSize: 12, marginTop: 6 }}>{d.note}</div>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="st-muted" style={{ fontSize: 12, marginBottom: 4 }}>Case × architecture (task success k/n)</div>
              <Table testId="case-matrix" head={['case', ...ARCHS]} rows={d.case_matrix.map((r: any) => [
                <button className="st-link" onClick={() => openCase(r.case)}>{r.case}</button>,
                ...ARCHS.map(a => r[a].n ? <span title={`${r[a].k}/${r[a].n}`} style={{ color: r[a].k === r[a].n ? 'var(--ok)' : r[a].k === 0 ? 'var(--err)' : 'var(--warn)' }}>
                  {r[a].k}/{r[a].n} {r[a].k === r[a].n ? 'pass' : r[a].k === 0 ? 'fail' : 'mixed'}</span> : <span className="st-faint">—</span>),
              ])} />
            </div>
          </>
        )}</Load>
      </Sec>
    </Page>
  );
}

export function CasePage({ caseId }: { caseId: string }) {
  const q = useApi<any>(`/benchmarks/cases/${encodeURIComponent(caseId)}`);
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  const [arch, setArch] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Load q={q}>{c => {
      const runs = c.runs.filter((r: any) => r.mode === mode && (!arch || r.architecture === arch));
      return (
        <Page testId="case-page" title={c.title} subtitle={`${c.id} · ${c.category} · ${c.difficulty} · timeout ${c.timeout_seconds}s · content hash ${c.content_hash}`} onReload={q.reload}>
          <Sec title="Input requirement"><pre className="st-pre">{c.requirement}</pre></Sec>
          <Sec title="Expected" hint="ground truth for grading">
            <div className="st-muted" style={{ fontSize: 12, marginBottom: 4 }}>Acceptance criteria</div>
            <ul style={{ margin: '0 0 8px', paddingLeft: 18 }}>{c.acceptance_criteria.map((x: string) => <li key={x} className="st-mono" style={{ fontSize: 12.5 }}>{x}</li>)}</ul>
            <div className="rv-kv" style={{ gridTemplateColumns: '120px 1fr' }}>
              <span>Task definition</span><span><SourceLink src={{ path: c.files.task }} /></span>
              <span>Starting repo</span><span>{c.files.repo.map((f: string) => <span key={f} style={{ marginRight: 10 }}><SourceLink src={{ path: f }} label={f.split('/repo/')[1]} /></span>)}</span>
              <span>Hidden tests</span><span>{c.files.hidden_tests.map((f: string) => <span key={f} style={{ marginRight: 10 }}><SourceLink src={{ path: f }} label={f.split('/hidden_tests/')[1]} /></span>)}</span>
              <span>Reference solution</span><span>{c.files.solution.map((f: string) => <span key={f} style={{ marginRight: 10 }}><SourceLink src={{ path: f }} label={f.split('/solution/')[1]} /></span>)}</span>
            </div>
          </Sec>
          <Sec title={`Runs on this case (${runs.length})`} hint="click a run to compare expected and actual"
            right={<span style={{ display: 'flex', gap: 6 }}><select className="st-select" value={arch} onChange={e => setArch(e.target.value)}><option value="">all architectures</option>{ARCHS.map(a => <option key={a}>{a}</option>)}</select><ModeTabs mode={mode} set={setMode} /></span>}>
            {runs.length === 0 && <div className="st-muted">No {mode} run of this case{arch ? ` with ${arch}` : ''}.</div>}
            {runs.map((r: any) => (
              <div key={r.run_id} style={{ borderTop: '1px solid var(--border)', padding: '6px 0' }} data-testid="case-run">
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: 'pointer', flexWrap: 'wrap' }} onClick={() => setOpen(o => o === r.run_id ? null : r.run_id)}>
                  {r.grading?.task_success ? <CheckCircle2 size={15} style={{ color: 'var(--ok)' }} /> : <XCircle size={15} style={{ color: 'var(--err)' }} />}
                  <b>{r.grading?.task_success ? 'task success' : 'task failed'}</b>
                  <span className="st-mono st-faint">{r.run_id.slice(0, 8)}</span>
                  <span className="st-pill">{r.architecture}</span>
                  <span className="st-muted" style={{ fontSize: 12 }}>{r.model ?? 'scripted'} · hidden {r.grading?.hidden ? `${r.grading.hidden.passed}/${r.grading.hidden.collected}` : '—'} · visible {r.grading?.visible ? `${r.grading.visible.passed}/${r.grading.visible.collected}` : '—'}{r.grading?.regression ? ' · regression' : ''} · verified {r.verified == null ? '—' : r.verified ? 'yes' : 'no'}</span>
                  <span style={{ flex: 1 }} /><span className="st-faint" style={{ fontSize: 12 }}><StatusDot status={r.status} /> {r.status} · {timeAgo(r.started_at)}</span>
                </div>
                {open === r.run_id && (
                  <div style={{ padding: '8px 0 4px 24px', display: 'grid', gap: 10 }}>
                    <Table head={['expected criterion', 'in requirement analysis', 'verifier verdict']} rows={r.criteria.map((x: any) => [
                      <span className="st-mono" style={{ fontSize: 12 }}>{x.expected}</span>,
                      x.covered_by_analysis ? <span style={{ color: 'var(--ok)' }}>✓ covered</span> : <span style={{ color: 'var(--err)' }}>✗ missing</span>,
                      x.verifier === 'satisfied' ? <span style={{ color: 'var(--ok)' }}>satisfied</span> : x.verifier === 'failed' ? <span style={{ color: 'var(--err)' }}>failed</span> : <span className="st-faint">not judged</span>,
                    ])} />
                    <div className="st-faint" style={{ fontSize: 11.5 }}>coverage is a heuristic lexical match</div>
                    <div><span className="st-muted" style={{ fontSize: 12 }}>Extracted by the RequirementAnalyst:</span> {r.extracted_criteria.length ? r.extracted_criteria.map((e: string) => <div key={e} className="st-mono" style={{ fontSize: 12 }}>• {e}</div>) : <span className="st-faint">none</span>}</div>
                    {r.grading?.hidden?.failures?.length > 0 && <pre className="st-pre" style={{ color: 'var(--err)' }}>{r.grading.hidden.failures.join('\n')}</pre>}
                    <div><span className="st-muted" style={{ fontSize: 12 }}>Actual changes ({r.code_changes.length})</span>
                      {r.code_changes.length ? <DiffView changes={r.code_changes} /> : <div className="st-faint">no file changes recorded</div>}</div>
                    <div><button className="st-btn secondary" onClick={() => openRun(r.run_id)}>Open run</button> <button className="st-btn secondary" onClick={() => c.files.solution[0] && openSource(c.files.solution[0])}>Open reference solution</button></div>
                  </div>
                )}
              </div>
            ))}
          </Sec>
        </Page>
      );
    }}</Load>
  );
}

