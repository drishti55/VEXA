import { useCallback, useEffect, useState } from 'react';
import { BarChart3, CheckCircle2, Download, ExternalLink, FlaskConical, Loader2, Play, RefreshCw, RotateCcw, Square, XCircle } from 'lucide-react';
import { VexaApi } from './api/client';
import type { Comparison, ConditionSummary, Experiment, ExperimentOptions, ExperimentRunRow, ExperimentSummary, RateStat, Validation } from './api/client';

const pct = (x: number | null | undefined) => (x === null || x === undefined ? 'n/a' : `${(100 * x).toFixed(1)}%`);
const ACTIVE = ['queued', 'running'];
// Missing measurements are 'n/a', never 0.
const num = (x: number | null | undefined, digits: number, scale = 1) =>
  (x === null || x === undefined ? 'n/a' : (x / scale).toFixed(digits));

function Rate({ r }: { r: RateStat }) {
  const [lo, hi] = r.ci95;
  return <span title={`95% Wilson CI ${pct(lo)} – ${pct(hi)}`}>{pct(r.rate)} <span className="text-vexa-muted">({r.k}/{r.n})</span></span>;
}

function SuccessBar({ c }: { c: ConditionSummary }) {
  const [lo, hi] = c.task_success.ci95;
  return (
    <div className="relative h-3 w-32 bg-black/40 rounded" title="bar = task success, whisker = 95% CI">
      <div className="absolute h-3 rounded bg-vexa-accent" style={{ width: `${100 * (c.task_success.rate ?? 0)}%` }} />
      {lo !== null && hi !== null && <div className="absolute top-1 h-1 bg-white/70" style={{ left: `${100 * lo}%`, width: `${100 * (hi - lo)}%` }} />}
    </div>
  );
}

function Checks({ label, options, value, onChange }: { label: string; options: { name: string; description?: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="space-y-1">
      <legend className="text-xs text-vexa-muted mb-1">{label}</legend>
      {options.map(o => (
        <label key={o.name} className="flex items-start gap-2 text-xs" title={o.description}>
          <input type="checkbox" className="mt-0.5" checked={value.includes(o.name)}
            onChange={e => onChange(e.target.checked ? [...value, o.name] : value.filter(x => x !== o.name))} />
          <span>{o.name}</span>
        </label>
      ))}
    </fieldset>
  );
}

const input = 'w-full bg-vexa-bg border border-vexa-border rounded p-1.5 text-xs focus:outline-none focus:border-vexa-accent';

function Comparisons({ title, items, label }: { title: string; items: Comparison[]; label: (c: Comparison) => string }) {
  return (
    <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4">
      <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-3">{title}</h3>
      {items.length === 0 ? <div className="text-xs text-vexa-muted">Needs at least two values of this factor.</div> : (
        <div className="text-xs font-mono space-y-1">
          {items.map((c, i) => {
            const d = c.success_diff_a_minus_b;
            const sig = d.low !== null && d.high !== null && (d.low > 0 || d.high < 0);
            return (
              <div key={i} data-testid="comparison">
                <span className="text-vexa-muted">{label(c)}</span> {c.a} − {c.b}: <span className={sig && c.comparable !== false ? 'text-vexa-success' : 'text-gray-300'}>{pct(d.diff)}</span>
                <span className="text-vexa-muted"> [{pct(d.low)}, {pct(d.high)}]{sig ? ' · interval excludes 0' : ''}</span>
                {c.comparable === false && (
                  <div className="text-vexa-warning pl-4" data-testid="comparison-warning" title={(c.warnings ?? []).join('\n')}>
                    ⚠ not like-for-like: {(c.warnings ?? []).join('; ')}
                  </div>)}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ExperimentsPage({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [options, setOptions] = useState<ExperimentOptions | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<ExperimentSummary | null>(null);
  const [runs, setRuns] = useState<ExperimentRunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<Validation | null>(null);

  // configuration form
  const [name, setName] = useState('architecture-comparison');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<'mock' | 'real'>('mock');
  const [tasks, setTasks] = useState<string[]>([]);
  const [archs, setArchs] = useState<string[]>(['sequential', 'hierarchical', 'event_driven', 'blackboard']);
  const [variants, setVariants] = useState<string[]>(['baseline']);
  const [transport, setTransport] = useState('mcp');
  const [verifier, setVerifier] = useState('adk_a2a');
  const [repeats, setRepeats] = useState(1);
  const [seed, setSeed] = useState(1234);
  const [model, setModel] = useState('');
  const [inPrice, setInPrice] = useState('');
  const [outPrice, setOutPrice] = useState('');
  const [maxCost, setMaxCost] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelTest, setModelTest] = useState<string | null>(null);
  const [confirmCost, setConfirmCost] = useState(false);

  const refresh = useCallback(() => VexaApi.listExperiments().then(setExperiments).catch(e => setError(e.message)), []);

  useEffect(() => {
    VexaApi.getExperimentOptions().then(o => {
      setOptions(o);
      setTasks(o.tasks.slice(0, 3).map(t => t.id));
      setModel(o.configured_model.model);
      if (o.configured_model.input_cost_per_1m !== null) setInPrice(String(o.configured_model.input_cost_per_1m));
      if (o.configured_model.output_cost_per_1m !== null) setOutPrice(String(o.configured_model.output_cost_per_1m));
    }).catch(e => setError(e.message));
    refresh();
  }, [refresh]);

  const loadDetail = useCallback((id: string) => {
    Promise.all([VexaApi.getExperimentSummary(id), VexaApi.getExperimentRuns(id)])
      .then(([s, r]) => { setSummary(s); setRuns(r); })
      .catch(e => setError(e.message));
  }, []);

  // poll while anything is running
  const anyActive = experiments.some(e => ACTIVE.includes(e.status));
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => {
      refresh();
      if (selected) loadDetail(selected);
    }, 2000);
    return () => clearInterval(t);
  }, [anyActive, selected, refresh, loadDetail]);

  const config = () => ({
    name, description: description || undefined, execution_mode: mode, tasks, architectures: archs,
    prompt_variants: variants, repeats, seed, tool_transport: transport, verifier_backend: verifier,
    models: [{
      provider: model.includes('/') ? model.split('/')[0] : (options?.configured_model.provider ?? 'openai'), model,
      input_cost_per_1m: inPrice ? Number(inPrice) : null, output_cost_per_1m: outPrice ? Number(outPrice) : null,
    }],
    max_cost_usd: maxCost ? Number(maxCost) : null,
  });

  const validate = async () => {
    setError(null);
    try { setValidation(await VexaApi.validateExperiment(config(), apiKey)); } catch (e: any) { setError(e.message); }
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await VexaApi.startExperiment(config(), confirmCost, apiKey);
      setSelected(r.experiment_id);
      setSummary(null);
      setRuns([]);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const select = (id: string) => { setSelected(id); setSummary(null); setRuns([]); loadDetail(id); };
  const current = experiments.find(e => e.experiment_id === selected);

  return (
    <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
      {/* Left: configuration + list */}
      <div className="w-full lg:w-96 p-5 border-r border-vexa-border space-y-5 overflow-y-auto">
        <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4 space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-vexa-muted flex items-center gap-2"><FlaskConical className="w-4 h-4" />New experiment</h2>
          {!options ? <Loader2 className="w-4 h-4 animate-spin" /> : (<>
            <input data-testid="exp-name" className={input} value={name} onChange={e => setName(e.target.value)} placeholder="Experiment name" />
            <textarea className={input} rows={2} value={description} onChange={e => setDescription(e.target.value)} placeholder="Description (optional)" />
            <div className="flex gap-2 text-xs">
              {(['mock', 'real'] as const).map(m => (
                <button key={m} data-testid={`exp-mode-${m}`} onClick={() => setMode(m)} className={`flex-1 py-1.5 rounded border ${mode === m ? 'border-vexa-accent text-vexa-accent bg-vexa-accent/10' : 'border-vexa-border text-vexa-muted'}`}>
                  {m === 'mock' ? 'Mock (no LLM)' : 'Real (paid LLM)'}
                </button>
              ))}
            </div>
            <fieldset>
              <legend className="text-xs text-vexa-muted mb-1 flex justify-between w-full">
                Benchmark tasks
                <span className="space-x-2">
                  <button className="text-vexa-accent" onClick={() => setTasks(options.tasks.map(t => t.id))}>all</button>
                  <button className="text-vexa-accent" onClick={() => setTasks([])}>none</button>
                </span>
              </legend>
              <div className="max-h-40 overflow-y-auto space-y-1">
                {options.tasks.map(t => (
                  <label key={t.id} className="flex items-center gap-2 text-xs">
                    <input type="checkbox" data-testid={`exp-task-${t.id}`} checked={tasks.includes(t.id)} onChange={e => setTasks(p => e.target.checked ? [...p, t.id] : p.filter(x => x !== t.id))} />
                    <span>{t.title}</span><span className="text-vexa-muted">· {t.category}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid grid-cols-2 gap-3">
              <Checks label="Architectures" options={options.architectures} value={archs} onChange={setArchs} />
              <Checks label="Prompt strategies" options={options.prompt_variants} value={variants} onChange={setVariants} />
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <label>Tools<select className={input} value={transport} onChange={e => setTransport(e.target.value)}>
                {options.tool_transports.map(t => <option key={t}>{t}</option>)}</select></label>
              <label>Verifier<select className={input} value={verifier} onChange={e => setVerifier(e.target.value)}>
                {options.verifier_backends.map(v => <option key={v.name} value={v.name} title={v.description}>{v.name}</option>)}</select></label>
              <label>Repeats<input type="number" min={1} max={20} className={input} value={repeats} onChange={e => setRepeats(Number(e.target.value))} /></label>
              <label>Seed<input type="number" className={input} value={seed} onChange={e => setSeed(Number(e.target.value))} /></label>
            </div>
            <div className="text-[11px] text-vexa-muted">RAG: {options.rag.available ? 'available' : `not available — ${options.rag.note}`}</div>
            {mode === 'real' && (
              <div className="space-y-2 border-t border-vexa-border pt-3">
                <label className="text-xs">Model (LiteLLM string)<input className={input} value={model} onChange={e => setModel(e.target.value)} /></label>
                <div className="text-[11px] text-vexa-muted">
                  Server key for {options.configured_model.provider}: {options.configured_model.api_key_configured ? 'configured' : 'not configured'}
                  {' '}(the check before starting uses each model's own provider)
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <button className="px-2 py-1 rounded border border-vexa-border hover:border-vexa-accent disabled:opacity-50"
                    disabled={modelTest === 'testing' || !model}
                    onClick={async () => {
                      setModelTest('testing');
                      try {
                        const r = await VexaApi.testModel(model, apiKey || undefined);
                        setModelTest(r.ok ? `ok · ${r.provider} · ${Math.round(r.latency_ms ?? 0)} ms` : `failed · ${r.error}`);
                      } catch (e: any) { setModelTest(`failed · ${e.message}`); }
                    }}>Test model</button>
                  {modelTest && modelTest !== 'testing' && (
                    <span className={modelTest.startsWith('ok') ? 'text-vexa-success' : 'text-vexa-error'} title="one-token call; costs about 1 token">{modelTest}</span>)}
                  {modelTest === 'testing' && <Loader2 className="w-3 h-3 animate-spin" />}
                </div>
                <input className={input} type="password" placeholder="API key for this experiment (optional, not stored)" value={apiKey} onChange={e => setApiKey(e.target.value)} />
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <label>$ / 1M in<input className={input} value={inPrice} onChange={e => setInPrice(e.target.value)} placeholder="n/a" /></label>
                  <label>$ / 1M out<input className={input} value={outPrice} onChange={e => setOutPrice(e.target.value)} placeholder="n/a" /></label>
                  <label>Max $<input className={input} value={maxCost} onChange={e => setMaxCost(e.target.value)} placeholder="none" /></label>
                </div>
                <label className="flex items-center gap-2 text-xs text-vexa-warning">
                  <input type="checkbox" checked={confirmCost} onChange={e => setConfirmCost(e.target.checked)} />I understand this calls a paid API
                </label>
              </div>
            )}
            <div className="flex gap-2">
              <button data-testid="exp-validate" onClick={validate} className="flex-1 py-2 rounded border border-vexa-border hover:bg-black/30 text-xs font-bold">Validate</button>
              <button data-testid="exp-start" onClick={start} disabled={busy || (mode === 'real' && !confirmCost)}
                className="flex-1 py-2 rounded bg-vexa-accent hover:bg-vexa-accent-hover disabled:opacity-50 text-xs font-bold flex items-center justify-center gap-2">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Start
              </button>
            </div>
            {validation && (
              <div className="text-xs space-y-1">
                <div className={validation.valid ? 'text-vexa-success' : 'text-vexa-error'}>
                  {validation.valid ? <CheckCircle2 className="w-3 h-3 inline mr-1" /> : <XCircle className="w-3 h-3 inline mr-1" />}
                  {validation.valid ? `Valid · ${validation.total_trials} trials` : 'Not valid'}
                </div>
                {validation.errors.map((e, i) => <div key={i} className="text-vexa-error">• {e}</div>)}
                {validation.warnings.map((w, i) => <div key={i} className="text-vexa-warning">• {w}</div>)}
              </div>
            )}
          </>)}
        </div>

        <div>
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-xs font-bold uppercase tracking-wider text-vexa-muted">Experiments</h2>
            <button onClick={refresh} className="text-vexa-muted hover:text-white" title="Refresh"><RefreshCw className="w-4 h-4" /></button>
          </div>
          {experiments.length === 0 && <div className="text-xs text-vexa-muted">No experiments yet.</div>}
          <div className="space-y-1">
            {experiments.map(e => {
              const done = e.completed_trials ?? e.run_count;
              const total = e.total_trials ?? done;
              return (
                <button key={e.experiment_id} data-testid="exp-list-item" data-status={e.status} onClick={() => select(e.experiment_id)}
                  className={`w-full text-left p-2 rounded text-xs ${selected === e.experiment_id ? 'bg-vexa-accent/20' : 'hover:bg-vexa-panel'}`}>
                  <div className="font-semibold truncate">{e.name}</div>
                  <div className="text-vexa-muted">{e.status} · {done}/{total} trials · {e.config?.execution_mode}</div>
                  {total > 0 && <div className="h-1 bg-black/40 rounded mt-1"><div className="h-1 bg-vexa-accent rounded" style={{ width: `${(100 * done) / total}%` }} /></div>}
                </button>
              );
            })}
          </div>
        </div>
        {error && <div className="text-xs text-vexa-error break-words">{error}</div>}
      </div>

      {/* Right: detail */}
      <div className="flex-1 p-5 overflow-y-auto space-y-5">
        {!current && <div className="text-sm text-vexa-muted">Configure and start an experiment, or select one to see its results.</div>}
        {current && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">{current.name}</h2>
              <div className="text-xs text-vexa-muted font-mono">{current.experiment_id} · {current.status} · {current.completed_trials ?? 0}/{current.total_trials ?? '?'} trials
                {current.failed_trials ? ` · ${current.failed_trials} failed runs` : ''} · config {current.environment?.config_hash}</div>
              {current.error && <div className="text-xs text-vexa-error">{current.error}</div>}
            </div>
            <div className="flex gap-2">
              {ACTIVE.includes(current.status) && current.active !== false && (
                <button onClick={() => VexaApi.cancelExperiment(current.experiment_id).then(refresh).catch(e => setError(e.message))}
                  className="px-3 py-1.5 text-xs rounded border border-vexa-error text-vexa-error flex items-center gap-1"><Square className="w-3 h-3" />Cancel</button>
              )}
              {!ACTIVE.includes(current.status) && (
                <button data-testid="rerun-experiment" title="New experiment with the same configuration and the same archived prompt versions"
                  onClick={() => VexaApi.rerunExperiment(current.experiment_id, { confirm_real_cost: confirmCost, llm_api_key: apiKey })
                    .then(r => { refresh(); select(r.experiment_id); }).catch(e => setError(e.message))}
                  className="px-3 py-1.5 text-xs rounded border border-vexa-border flex items-center gap-1"><RefreshCw className="w-3 h-3" />Rerun</button>
              )}
              {['cancelled', 'interrupted', 'failed', 'stopped_budget'].includes(current.status) && (
                <button onClick={() => VexaApi.resumeExperiment(current.experiment_id, apiKey).then(refresh).catch(e => setError(e.message))}
                  className="px-3 py-1.5 text-xs rounded border border-vexa-border flex items-center gap-1"><RotateCcw className="w-3 h-3" />Resume missing trials</button>
              )}
              {(['csv', 'json', 'md'] as const).map(f => (
                <button key={f} onClick={() => VexaApi.downloadExport(current.experiment_id, f).catch(e => setError(e.message))}
                  className="px-3 py-1.5 text-xs rounded border border-vexa-border hover:bg-vexa-panel flex items-center gap-1"><Download className="w-3 h-3" />{f.toUpperCase()}</button>
              ))}
            </div>
          </div>
        )}

        {current && summary && summary.conditions.length > 0 && (<>
          {(summary.warnings ?? []).length > 0 && (
            <div data-testid="comparability-warnings" className="bg-vexa-warning/10 border border-vexa-warning/40 rounded-xl p-3 text-xs text-vexa-warning space-y-1">
              <div className="font-bold">Configurations differ — comparisons below are not like-for-like:</div>
              {(summary.warnings ?? []).slice(0, 8).map((w, i) => <div key={i} className="font-mono">• {w}</div>)}
            </div>)}
          <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4 overflow-x-auto">
            <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-3 flex items-center gap-2"><BarChart3 className="w-4 h-4" />Aggregated by condition</h3>
            <table className="text-xs w-full">
              <thead className="text-vexa-muted text-left">
                <tr>{['Architecture', 'Prompt', 'Prompt version', 'Runs', 'Task success', '', 'Hidden tests', 'Regression', 'Verifier false +', 'Latency (s)', 'Debug', 'LLM / tool calls', 'Tokens (runs)', 'Est. cost', 'Failures', 'Consistent'].map((h, i) =>
                  <th key={i} className="font-normal pr-3 pb-2 whitespace-nowrap">{h}</th>)}</tr>
              </thead>
              <tbody className="font-mono">
                {summary.conditions.map(c => (
                  <tr key={`${c.architecture}-${c.prompt_variant}-${c.model}`} className="border-t border-vexa-border/50">
                    <td className="pr-3 py-1.5 text-white">{c.architecture}</td>
                    <td className="pr-3">{c.prompt_variant}</td>
                    <td className={`pr-3 ${c.comparable === false ? 'text-vexa-warning' : 'text-vexa-muted'}`} data-testid="condition-prompt-version"
                      title={`config fingerprints: ${(c.config_fingerprints ?? []).join(', ')}${(c.warnings ?? []).length ? '\n' + (c.warnings ?? []).join('\n') : ''}`}>
                      {(c.prompt_versions ?? []).map(v => v.slice(0, 8)).join(', ') || 'n/a'}{c.comparable === false ? ' ⚠' : ''}</td>
                    <td className="pr-3">{c.runs}</td>
                    <td className="pr-3 whitespace-nowrap"><Rate r={c.task_success} /></td>
                    <td className="pr-3"><SuccessBar c={c} /></td>
                    <td className="pr-3">{pct(c.hidden_pass_rate.mean)}</td>
                    <td className="pr-3"><Rate r={c.regression} /></td>
                    <td className="pr-3"><Rate r={c.verifier_false_positive} /></td>
                    <td className="pr-3 whitespace-nowrap">{num(c.latency_ms.mean, 2, 1000)}{c.latency_ms.sd !== null && c.latency_ms.sd !== undefined ? ` ± ${num(c.latency_ms.sd, 2, 1000)}` : ''}</td>
                    <td className="pr-3">{num(c.debug_iterations.mean, 2)}</td>
                    <td className="pr-3">{num(c.llm_calls.mean, 1)} / {num(c.tool_calls.mean, 1)}</td>
                    <td className="pr-3">{c.total_tokens.runs_with_usage ? `${num(c.total_tokens.mean, 0)} (${c.total_tokens.runs_with_usage})` : 'n/a'}</td>
                    <td className="pr-3" title={c.estimated_cost_usd.label}>{c.estimated_cost_usd.runs_with_cost ? `$${c.estimated_cost_usd.total.toFixed(4)}` : 'n/a'}</td>
                    <td className="pr-3"><Rate r={c.run_failed} /></td>
                    <td>{c.repeatability.tasks_with_repeats ? `${c.repeatability.consistent_tasks}/${c.repeatability.tasks_with_repeats}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {current.config?.execution_mode === 'mock' && <p className="text-[11px] text-vexa-warning mt-2">Mock experiment: agents make no code changes, so task success is 0 by design. Compare coordination cost (latency, calls) instead.</p>}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <Comparisons title="Architecture comparison (Newcombe 95% CI)" items={summary.architecture_comparisons as Comparison[]} label={c => `${c.prompt_variant}:`} />
            <Comparisons title="Prompt-strategy comparison (Newcombe 95% CI)" items={summary.prompt_comparisons ?? []} label={c => `${c.architecture}:`} />
          </div>

          <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-3">Where the time goes (share of agent time)</h3>
            <div className="space-y-2">
              {summary.conditions.map(c => (
                <div key={`${c.architecture}-${c.prompt_variant}-share`} className="flex items-center gap-3">
                  <div className="text-xs w-48 truncate">{c.architecture} · {c.prompt_variant}</div>
                  <div className="flex flex-1 h-3 rounded overflow-hidden bg-black/30">
                    {Object.entries(c.agent_time_share).map(([agent, share], i) => (
                      <div key={agent} title={`${agent}: ${pct(share)}`} style={{ width: `${100 * share}%` }}
                        className={['bg-vexa-accent', 'bg-amber-500', 'bg-purple-500', 'bg-emerald-500', 'bg-pink-500', 'bg-sky-500', 'bg-slate-400', 'bg-orange-400'][i % 8]} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>)}

        {current && (
          <div className="bg-vexa-panel border border-vexa-border rounded-xl p-4 overflow-x-auto">
            <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-3">Individual runs ({runs.length})</h3>
            {runs.length === 0 ? <div className="text-xs text-vexa-muted">{ACTIVE.includes(current.status) ? 'Waiting for the first trial…' : 'No runs.'}</div> : (
              <table className="text-xs w-full font-mono">
                <thead className="text-vexa-muted text-left"><tr>{['Task', 'Architecture', 'Prompt', 'Rep', 'Run status', 'Task success (graded)', 'Hidden', 'Verified (claim)', 'Debug', 's', 'Tokens', 'Guard blocks', ''].map(h => <th key={h} className="font-normal pr-3 pb-1">{h}</th>)}</tr></thead>
                <tbody>
                  {runs.map(r => (
                    <tr key={r.run_id} className="border-t border-vexa-border/50">
                      <td className="pr-3 py-1">{r.task_id}</td>
                      <td className="pr-3">{r.architecture}</td>
                      <td className="pr-3">{r.prompt_variant}</td>
                      <td className="pr-3">{r.repeat_index}</td>
                      <td className={`pr-3 ${r.status === 'failed' ? 'text-vexa-error' : r.status === 'success' ? 'text-vexa-success' : 'text-vexa-warning'}`}>{r.status}</td>
                      <td className={`pr-3 ${r.task_success ? 'text-vexa-success' : 'text-vexa-error'}`}>{String(r.task_success)}</td>
                      <td className="pr-3">{pct(r.hidden_pass_rate)}</td>
                      <td className="pr-3">{String(r.verified)}</td>
                      <td className="pr-3">{r.debug_iterations}</td>
                      <td className="pr-3">{(r.duration_ms / 1000).toFixed(2)}</td>
                      <td className="pr-3">{r.usage_available ? r.total_tokens : 'n/a'}</td>
                      <td className="pr-3">{r.guard_blocked}</td>
                      <td><button onClick={() => onOpenRun(r.run_id)} className="text-vexa-accent flex items-center gap-1">open <ExternalLink className="w-3 h-3" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
