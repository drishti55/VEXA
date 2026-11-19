import { useEffect, useMemo, useRef, useState } from 'react';
import { X, ChevronUp, ChevronDown, AlertCircle, AlertTriangle, Trash2, CheckCircle2, XCircle } from 'lucide-react';
import { VexaApi } from '../api/client';
import type { AgentRunResponse } from '../api/client';
import { useStudio, setState, openRun, ensureRun } from './store';
import type { PanelTabId, TerminalEntry } from './store';
import { fmtMs, fmtTime } from './util';

const TABS: { id: PanelTabId; label: string }[] = [
  { id: 'problems', label: 'Problems' }, { id: 'output', label: 'Output' }, { id: 'debug', label: 'Debug Console' },
  { id: 'terminal', label: 'Terminal' }, { id: 'agentlogs', label: 'Agent Logs' }, { id: 'tests', label: 'Test Results' },
  { id: 'trace', label: 'Execution Trace' },
];

/** The run the panel reports on: the one focused in the editor, else a live one, else the latest in this workspace. */
function usePanelRunId(): string | null {
  return useStudio(s => {
    const id = s.focusRunId ?? s.liveRunIds[s.liveRunIds.length - 1]
      ?? s.recentRuns.find(r => r.workspace_id === s.workspaceId)?.run_id;
    return id ?? null;
  });
}

function usePanelRunFull(): AgentRunResponse | null {
  const id = usePanelRunId();
  const run = useStudio(s => (id ? s.runs[id] ?? null : null));
  useEffect(() => { if (id) ensureRun(id); }, [id]);
  return run;
}

export function usePanelRun(): AgentRunResponse | null { return usePanelRunFull(); }

export interface Problem { severity: 'error' | 'warning'; source: string; text: string; agent?: string | null }

export function problemsOf(run: AgentRunResponse | null): Problem[] {
  if (!run) return [];
  const res = run.result;
  const out: Problem[] = [];
  for (const e of run.errors ?? []) out.push({ severity: 'error', source: 'run', text: e });
  for (const g of res?.guardrail_events ?? []) {
    if (g.decision === 'blocked') out.push({ severity: 'error', source: `guardrail ${g.rule}`, text: `${g.rule_name}: ${g.reason || g.detail}`, agent: g.agent });
    if (g.decision === 'flagged' || g.decision === 'indeterminate') out.push({ severity: 'warning', source: `guardrail ${g.rule}`, text: `${g.rule_name}: ${g.reason || g.detail}`, agent: g.agent });
  }
  for (const f of res?.final_test_result?.failures ?? []) out.push({ severity: 'error', source: 'tests', text: f });
  const v = res?.verification_result;
  for (const f of v?.requirements_failed ?? []) out.push({ severity: 'warning', source: 'verifier', text: `requirement not satisfied: ${f}` });
  return out;
}

export function BottomPanel() {
  const tab = useStudio(s => s.panelTab);
  const run = usePanelRun();
  const problems = useMemo(() => problemsOf(run), [run]);
  const maximized = useStudio(s => s.panelHeight > window.innerHeight * 0.6);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} data-testid="bottom-panel">
      <div className="st-ptabs">
        {TABS.map(t => (
          <button key={t.id} className={`st-ptab${tab === t.id ? ' active' : ''}`} onClick={() => setState({ panelTab: t.id })} data-testid={`panel-tab-${t.id}`}>
            {t.label}{t.id === 'problems' && problems.length > 0 && <span className="st-badge" style={{ marginLeft: 6, background: 'var(--bg-active)', color: 'var(--text)' }}>{problems.length}</span>}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {run && <button className="st-link" style={{ fontSize: 12, marginRight: 8, whiteSpace: 'nowrap' }} onClick={() => openRun(run.run_id)} title="Open this run">run {run.run_id.slice(0, 8)} · {run.status}</button>}
        <button className="st-icon-btn" title={maximized ? 'Restore panel size' : 'Maximize panel'} onClick={() => setState({ panelHeight: maximized ? 240 : Math.round(window.innerHeight * 0.7) })}>
          {maximized ? <ChevronDown size={15} /> : <ChevronUp size={15} />}</button>
        <button className="st-icon-btn" title="Close panel" onClick={() => setState({ panelVisible: false })}><X size={15} /></button>
      </div>
      <div className="st-scroll" style={{ padding: '0 0 4px' }}>
        {tab === 'terminal' ? <Terminal /> : !run ? <NoRun /> : (
          <>
            {tab === 'problems' && <Problems problems={problems} />}
            {tab === 'output' && <OutputLog run={run} />}
            {tab === 'debug' && <DebugConsole run={run} />}
            {tab === 'agentlogs' && <AgentLogs run={run} />}
            {tab === 'tests' && <TestResults run={run} />}
            {tab === 'trace' && <Waterfall run={run} />}
          </>
        )}
      </div>
    </div>
  );
}

function NoRun() {
  return <div className="st-empty st-muted">No agent run yet in this workspace. Start one from the Agent Runs panel, or open a previous run.</div>;
}

function Problems({ problems }: { problems: Problem[] }) {
  if (!problems.length) return <div className="st-empty st-muted">No problems have been detected in this run.</div>;
  return (
    <div>
      {problems.map((p, i) => (
        <div key={i} className="st-row" style={{ paddingLeft: 14, height: 'auto', alignItems: 'flex-start', padding: '3px 14px', whiteSpace: 'normal' }}>
          {p.severity === 'error' ? <AlertCircle size={14} style={{ color: 'var(--err)', flex: 'none', marginTop: 2 }} /> : <AlertTriangle size={14} style={{ color: 'var(--warn)', flex: 'none', marginTop: 2 }} />}
          <span style={{ flex: 1 }}>{p.text}</span>
          <span className="st-faint" style={{ fontSize: 12 }}>{p.source}{p.agent ? ` · ${p.agent}` : ''}</span>
        </div>
      ))}
    </div>
  );
}

function useAutoscroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current?.closest('.st-scroll');
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [dep]);
  return ref;
}

function OutputLog({ run }: { run: AgentRunResponse }) {
  const events = run.result?.events ?? [];
  const ref = useAutoscroll(events.length);
  return (
    <div ref={ref} className="st-mono" style={{ padding: '4px 14px', fontSize: 12, lineHeight: 1.6 }} data-testid="output-log">
      {events.length === 0 && <span className="st-muted">No events yet.</span>}
      {events.map((e, i) => (
        <div key={i} style={{ whiteSpace: 'pre-wrap' }}>
          <span className="st-faint">[{fmtTime(e.timestamp)}]</span>{' '}
          <span style={{ color: 'var(--info)' }}>{e.agent}</span>{' '}
          <span style={{ color: e.event === 'failed' || e.event.endsWith('_failed') ? 'var(--err)' : e.event === 'completed' ? 'var(--ok)' : 'var(--text-strong)' }}>{e.event}</span>
          {e.detail ? ` ${e.detail}` : ''}{e.duration_ms != null ? <span className="st-faint"> ({fmtMs(e.duration_ms)})</span> : null}
        </div>
      ))}
    </div>
  );
}

function DebugConsole({ run }: { run: AgentRunResponse }) {
  const cbs: any[] = (run.result?.trace as any)?.callback_events ?? [];
  const ref = useAutoscroll(cbs.length);
  return (
    <div ref={ref} className="st-mono" style={{ padding: '4px 14px', fontSize: 12, lineHeight: 1.6 }}>
      <div className="st-muted" style={{ fontFamily: 'var(--font-ui)', marginBottom: 4 }}>CrewAI event-bus callbacks (task lifecycle, output-guardrail retries, LLM and tool errors). VEXA has no step debugger; this is the framework's own event stream.</div>
      {cbs.length === 0 && <span className="st-muted">{run.execution_mode === 'mock' ? 'Mock runs do not go through the CrewAI event bus.' : 'No callback events recorded.'}</span>}
      {cbs.map((c, i) => (
        <div key={i} style={{ whiteSpace: 'pre-wrap' }}>
          <span className="st-faint">#{c.seq}</span> <span style={{ color: 'var(--info)' }}>{c.agent}</span> {c.kind}
          {c.error ? <span style={{ color: 'var(--err)' }}> {String(c.error)}</span> : null}
          {c.retry_count ? <span style={{ color: 'var(--warn)' }}> retry={c.retry_count}</span> : null}
        </div>
      ))}
    </div>
  );
}

function AgentLogs({ run }: { run: AgentRunResponse }) {
  const events = run.result?.events ?? [];
  const agents = [...new Set(events.map(e => e.agent))];
  const [agent, setAgent] = useState<string>('');
  const shown = agent ? events.filter(e => e.agent === agent) : events;
  return (
    <div style={{ padding: '4px 14px' }}>
      <select className="st-select" value={agent} onChange={e => setAgent(e.target.value)} style={{ marginBottom: 6 }}>
        <option value="">All agents ({events.length})</option>
        {agents.map(a => <option key={a} value={a}>{a} ({events.filter(e => e.agent === a).length})</option>)}
      </select>
      <div className="st-mono" style={{ fontSize: 12, lineHeight: 1.6 }}>
        {shown.map((e, i) => <div key={i}><span className="st-faint">[{fmtTime(e.timestamp)}]</span> <b>{e.agent}</b> {e.event} {e.detail}</div>)}
      </div>
    </div>
  );
}

function TestResults({ run }: { run: AgentRunResponse }) {
  const t = run.result?.final_test_result;
  const v = run.result?.verification_result;
  return (
    <div style={{ padding: '6px 14px', display: 'grid', gap: 10 }}>
      {!t ? <div className="st-muted">{run.status === 'running' ? 'Tests have not run yet.' : 'This run produced no test result.'}</div> : (
        <div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {t.passed ? <CheckCircle2 size={16} style={{ color: 'var(--ok)' }} /> : <XCircle size={16} style={{ color: 'var(--err)' }} />}
            <b>{t.no_tests ? 'No tests found' : `${t.tests_passed} passed, ${t.tests_failed} failed of ${t.tests_found}`}</b>
            <span className="st-muted">exit code {t.exit_code ?? '—'} · attempts {run.result?.test_attempts ?? 0} · debug iterations {run.debug_iterations}</span>
          </div>
          <div className="st-faint" style={{ fontSize: 12 }}>verdict source: {t.verdict_source} (the sandboxed pytest exit code, never an agent's claim)</div>
          {t.failures.map((f, i) => <pre key={i} className="st-pre" style={{ marginTop: 6 }}>{f}</pre>)}
        </div>
      )}
      {v && (
        <div>
          <b>Verification: {v.verified ? 'verified' : 'not verified'}</b> <span className="st-muted">by {v.backend}{v.llm_claimed_verified != null && v.llm_claimed_verified !== v.verified ? ` (the model claimed ${v.llm_claimed_verified ? 'verified' : 'not verified'}; overridden by evidence)` : ''}</span>
          {v.requirements_satisfied.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--ok)' }}>✓ {r}</div>)}
          {v.requirements_failed.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--err)' }}>✗ {r}</div>)}
        </div>
      )}
    </div>
  );
}

const KIND_COLOR: Record<string, string> = { run: 'var(--text-faint)', agent: 'var(--info)', tool: 'var(--ok)', llm: 'var(--mock)', internal: 'var(--text-muted)' };

/** Span waterfall from the run's recorded OpenTelemetry spans (no synthetic spans). */
export function Waterfall({ run, filters }: { run: AgentRunResponse; filters?: boolean }) {
  const all = run.result?.trace?.spans ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const [kind, setKind] = useState('');
  const [agent, setAgent] = useState('');
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [text, setText] = useState('');
  const isErr = (st: string) => !['ok', 'unset'].includes(String(st).toLowerCase());
  const spans = all.filter(s => (!kind || s.kind === kind) && (!agent || s.attributes?.['vexa.agent'] === agent) && (!errorsOnly || isErr(s.status))
    && (!text || `${s.name} ${JSON.stringify(s.attributes)}`.toLowerCase().includes(text.toLowerCase())));
  const filterBar = filters && (
    <div style={{ display: 'flex', gap: 6, padding: '6px 14px', flexWrap: 'wrap', alignItems: 'center' }}>
      <select className="st-select" value={kind} onChange={e => setKind(e.target.value)}><option value="">all kinds</option>{[...new Set(all.map(s => s.kind))].map(k => <option key={k}>{k}</option>)}</select>
      <select className="st-select" value={agent} onChange={e => setAgent(e.target.value)}><option value="">all agents</option>{[...new Set(all.map(s => s.attributes?.['vexa.agent']).filter(Boolean))].map(k => <option key={k}>{k}</option>)}</select>
      <label style={{ fontSize: 12 }}><input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} /> errors only ({all.filter(s => isErr(s.status)).length})</label>
      <input className="st-input" placeholder="filter by name or attribute" value={text} onChange={e => setText(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
      <span className="st-faint" style={{ fontSize: 12 }}>{spans.length}/{all.length} spans · database operations are not instrumented</span>
    </div>
  );
  if (!all.length) return <div className="st-empty st-muted">No spans recorded yet.</div>;
  if (!spans.length) return <>{filterBar}<div className="st-empty st-muted">No span matches the filters.</div></>;
  const t0 = Math.min(...spans.map(s => s.start_ns));
  const t1 = Math.max(...spans.map(s => s.end_ns || s.start_ns));
  const total = Math.max(1, t1 - t0);
  const byId = new Map(spans.map(s => [s.span_id, s]));
  const depth = (s: typeof spans[number]) => { let d = 0, p = s.parent_span_id; while (p && byId.has(p) && d < 12) { d++; p = byId.get(p)!.parent_span_id; } return d; };
  const ordered = [...spans].sort((a, b) => a.start_ns - b.start_ns);
  const selected = sel ? byId.get(sel) : null;
  return (
    <div style={{ display: 'flex', minHeight: '100%' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {filterBar}
        <div className="st-muted" style={{ fontSize: 12, padding: '4px 14px' }}>{spans.length} spans · {fmtMs(total / 1e6)} · {Object.entries(spans.reduce((a: Record<string, number>, s) => { a[s.kind] = (a[s.kind] ?? 0) + 1; return a; }, {})).map(([k, n]) => `${k} ${n}`).join(' · ')}</div>
        {ordered.map(s => {
          const left = ((s.start_ns - t0) / total) * 100;
          const width = Math.max(0.3, (((s.end_ns || s.start_ns) - s.start_ns) / total) * 100);
          return (
            <div key={s.span_id} className={`st-row${sel === s.span_id ? ' selected' : ''}`} style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 34%) 1fr 70px', gap: 8, padding: '0 14px' }}
              onClick={() => setSel(s.span_id)} data-testid="trace-span">
              <span style={{ paddingLeft: depth(s) * 12, overflow: 'hidden', textOverflow: 'ellipsis' }} title={s.name}>
                <span style={{ color: KIND_COLOR[s.kind] ?? 'var(--text)' }}>{s.kind}</span> {s.name}
              </span>
              <span style={{ position: 'relative', height: 10 }}>
                <span style={{ position: 'absolute', left: `${left}%`, width: `${width}%`, top: 0, bottom: 0, borderRadius: 2,
                  background: s.status === 'error' || s.status === 'ERROR' ? 'var(--err)' : KIND_COLOR[s.kind] ?? 'var(--info)', opacity: .85 }} />
              </span>
              <span className="st-faint" style={{ textAlign: 'right', fontSize: 12 }}>{fmtMs(s.duration_ms)}</span>
            </div>
          );
        })}
      </div>
      {selected && (
        <div style={{ width: 340, flex: 'none', borderLeft: '1px solid var(--border)', padding: 10, fontSize: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center' }}><b style={{ flex: 1 }}>{selected.name}</b><button className="st-icon-btn" onClick={() => setSel(null)}><X size={14} /></button></div>
          <div className="rv-kv" style={{ marginTop: 6 }}>
            <span>kind</span><span>{selected.kind}</span>
            <span>status</span><span>{selected.status}{selected.status_message ? ` — ${selected.status_message}` : ''}</span>
            <span>duration</span><span>{fmtMs(selected.duration_ms)}</span>
            <span>span / parent</span><span className="st-mono">{selected.span_id} / {selected.parent_span_id ?? '—'}</span>
            <span>source</span><span>{selected.source ?? 'vexa'}</span>
          </div>
          <pre className="st-pre" style={{ marginTop: 8 }}>{JSON.stringify(selected.attributes, null, 2)}</pre>
          {(() => {
            const guards = (selected.events ?? []).filter(e => e.name.startsWith('guardrail'));
            return guards.length ? <div style={{ marginTop: 8 }}><b>Guardrail decisions in this span ({guards.length})</b>
              {guards.map((g, i) => <div key={i} className="st-mono" style={{ fontSize: 11.5 }}>{g.name} {g.attributes?.rule ?? ''} {g.attributes?.reason ?? ''}</div>)}</div> : null;
          })()}
          {selected.events?.length ? <pre className="st-pre" style={{ marginTop: 8 }}>{JSON.stringify(selected.events, null, 2)}</pre> : null}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- terminal (sandboxed test runner only)

let termSeq = 0;

function Terminal() {
  const workspaceId = useStudio(s => s.workspaceId);
  const entries = useStudio(s => s.terminal);
  const [cmd, setCmd] = useState('pytest');
  const [history, setHistory] = useState<string[]>([]);
  const [hIdx, setHIdx] = useState(-1);
  const ref = useAutoscroll(entries.length + (entries[entries.length - 1]?.status ?? ''));

  const push = (e: TerminalEntry) => setState(s => ({ terminal: [...s.terminal.slice(-50), e] }));
  const patch = (id: number, p: Partial<TerminalEntry>) => setState(s => ({ terminal: s.terminal.map(x => x.id === id ? { ...x, ...p } : x) }));

  const run = async (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    setHistory(h => [...h, trimmed]); setHIdx(-1);
    const id = ++termSeq;
    const base = { id, command: trimmed, cwd: workspaceId || '(no workspace)', startedAt: new Date().toISOString() };
    if (trimmed === 'clear') { setState({ terminal: [] }); return; }
    const argv = trimmed.split(/\s+/);
    if (argv[0] === 'help') {
      push({ ...base, status: 'done', exitCode: 0, stdout: HELP });
      return;
    }
    const isPytest = argv[0] === 'pytest' || (argv[0] === 'python' && argv[1] === '-m' && argv[2] === 'pytest');
    if (!isPytest) {
      push({ ...base, status: 'error', exitCode: 127, error: `'${argv[0]}' is not available. This terminal only runs the backend's sandboxed test command — there is no general shell, by design. Type 'help'.` });
      return;
    }
    if (!workspaceId) { push({ ...base, status: 'error', error: 'Open a workspace first.' }); return; }
    const rest = argv[0] === 'pytest' ? argv.slice(1) : argv.slice(3);
    const path = rest.find(a => !a.startsWith('-')) ?? '.';
    const extra = rest.filter(a => a !== path);
    push({ ...base, status: 'running' });
    try {
      const r = await VexaApi.runTests(workspaceId, path, extra);
      patch(id, { status: 'done', exitCode: r.exit_code, stdout: r.stdout, stderr: r.stderr, timedOut: r.timed_out, durationMs: r.duration_ms,
        error: r.exit_code == null ? r.error ?? r.message : undefined });
    } catch (e: any) {
      patch(id, { status: 'error', error: e.message });
    }
  };

  useEffect(() => {
    const take = () => { if (pendingCommand) { const c = pendingCommand; pendingCommand = null; run(c); } };
    take();
    document.addEventListener('vexa:terminal-run', take);
    return () => document.removeEventListener('vexa:terminal-run', take);
  }); // re-bound every render so `run` sees the current workspace

  const running = entries.some(e => e.status === 'running');
  return (
    <div ref={ref} className="st-mono" style={{ padding: '4px 14px', fontSize: 12, lineHeight: 1.5 }} data-testid="terminal">
      <div className="st-muted" style={{ fontFamily: 'var(--font-ui)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ flex: 1 }}>Sandboxed command runner — commands run inside the workspace through the backend sandbox ({workspaceId || 'no workspace'}). Only <code>pytest</code> is allowed.</span>
        <button className="st-icon-btn" title="Clear" onClick={() => setState({ terminal: [] })}><Trash2 size={14} /></button>
      </div>
      {entries.map(e => (
        <div key={e.id} style={{ marginBottom: 8 }}>
          <div><span style={{ color: 'var(--ok)' }}>{e.cwd}</span> <span className="st-faint">$</span> <span style={{ color: 'var(--text-strong)' }}>{e.command}</span></div>
          {e.status === 'running' && <div className="st-muted">running…</div>}
          {e.stdout && <pre style={{ margin: 0, whiteSpace: 'pre-wrap', font: 'inherit' }}>{e.stdout}</pre>}
          {e.stderr && <pre style={{ margin: 0, whiteSpace: 'pre-wrap', font: 'inherit', color: 'var(--err)' }}>{e.stderr}</pre>}
          {e.error && <div style={{ color: 'var(--err)' }}>{e.error}</div>}
          {e.status !== 'running' && e.exitCode !== undefined && (
            <div className="st-faint">exit code {e.exitCode ?? '—'}{e.timedOut ? ' (timed out)' : ''}{e.durationMs != null ? ` · ${fmtMs(e.durationMs)}` : ''}</div>
          )}
        </div>
      ))}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: 'var(--ok)' }}>{workspaceId || '~'}</span><span className="st-faint">$</span>
        <input className="st-mono" value={cmd} disabled={running} data-testid="terminal-input"
          onChange={e => setCmd(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') { run(cmd); setCmd(''); }
            if (e.key === 'ArrowUp' && history.length) { const i = hIdx < 0 ? history.length - 1 : Math.max(0, hIdx - 1); setHIdx(i); setCmd(history[i]); e.preventDefault(); }
            if (e.key === 'ArrowDown' && hIdx >= 0) { const i = hIdx + 1; if (i >= history.length) { setHIdx(-1); setCmd(''); } else { setHIdx(i); setCmd(history[i]); } }
          }}
          style={{ flex: 1, background: 'transparent', border: 0, outline: 'none', color: 'var(--text-strong)' }} />
      </div>
    </div>
  );
}

const HELP = `Available commands
  pytest [path] [args]       run the workspace tests in the backend sandbox (same runner the Tester agent uses)
  python -m pytest [path]    same as above
  clear                      clear this terminal
  help                       this message

The sandbox restricts commands, environment and time. A general shell is intentionally not exposed to the browser.`;

// Quick actions (command palette, title bar) queue a command; the terminal runs it once mounted.
let pendingCommand: string | null = null;
export function runInTerminal(command: string) {
  pendingCommand = command;
  setState({ panelVisible: true, panelTab: 'terminal' });
  document.dispatchEvent(new CustomEvent('vexa:terminal-run'));
}
