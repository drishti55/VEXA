import { useEffect, useState } from 'react';
import { RefreshCw, X, ArrowUp, Bot, Filter, Settings2, Loader2 } from 'lucide-react';
import { ApiError, VexaApi } from '../api/client';
import type { Option } from '../api/client';
import { useStudio, useLiveRuns, setState, loadRecentRuns, openRun, watchRun, toast, getState, dirtyPaths, saveAll } from './store';
import { StatusDot, timeAgo, runRequirement, runStartedAt } from './util';
import { ConfirmDialog } from './common';
import { LivePreview } from './views/LivePreview';
import { ModelKeySettings } from './views/SettingsView';
import { useLlmCredentials, modelForKey } from './llmCredentials';

interface Options { architectures: Option[]; promptVariants: Option[] }

export function RunPanel() {
  const recentRuns = useStudio(s => s.recentRuns);
  const workspaceId = useStudio(s => s.workspaceId);
  const runs = useStudio(s => s.runs);
  const rightTab = useStudio(s => s.rightTab);
  const [onlyThisWs, setOnlyThisWs] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [opts, setOpts] = useState<Options>({ architectures: [], promptVariants: [] });

  useEffect(() => {
    loadRecentRuns();
    Promise.all([VexaApi.getArchitectures(), VexaApi.getPromptVariants()])
      .then(([architectures, promptVariants]) => setOpts({ architectures, promptVariants })).catch(() => {});
  }, []);

  // live snapshots are newer than the listing
  const list = recentRuns.map(r => runs[r.run_id] ?? r).filter(r => !onlyThisWs || !workspaceId || r.workspace_id === workspaceId);
  const shown = showAll ? list : list.slice(0, 12);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} data-testid="run-panel">
      <div className="st-head" style={{ paddingLeft: 8 }}>
        <span className="title" style={{ display: 'flex', alignItems: 'center', gap: 4 }} role="tablist">
          {([['runs', 'Agent Runs'], ['preview', 'Live Preview']] as const).map(([id, label]) => (
            <button key={id} role="tab" aria-selected={rightTab === id} data-testid={`right-tab-${id}`} onClick={() => setState({ rightTab: id })}
              style={{ background: rightTab === id ? 'var(--bg-active)' : 'transparent', color: rightTab === id ? 'var(--text-strong)' : 'var(--text-muted)',
                border: 0, borderRadius: 5, padding: '2px 8px', font: 'inherit', fontWeight: 600, cursor: 'pointer' }}>{label}</button>
          ))}
        </span>
        <button className="st-icon-btn" title="Close panel" onClick={() => setState({ rightVisible: false })}><X size={15} /></button>
      </div>
      {rightTab === 'preview' ? <LivePreview /> : <>
      <div className="st-section" style={{ paddingLeft: 12, cursor: 'default' }}>
        <span style={{ flex: 1, fontSize: 13 }}>Sessions</span>
        <button className="st-icon-btn" title="Refresh" onClick={loadRecentRuns}><RefreshCw size={14} /></button>
        <button className="st-icon-btn" title={onlyThisWs ? 'Showing this workspace only — click to show all' : 'Showing all workspaces — click to filter'}
          onClick={() => setOnlyThisWs(v => !v)} style={{ color: onlyThisWs ? 'var(--text-strong)' : undefined }}><Filter size={14} /></button>
      </div>
      <div className="st-scroll" style={{ padding: '2px 0' }}>
        {shown.length === 0 && <div className="st-empty st-muted">No runs {onlyThisWs && workspaceId ? `in ${workspaceId} ` : ''}yet. Describe a change below to start one.</div>}
        {shown.map(r => (
          <div key={r.run_id} className="st-row" style={{ height: 'auto', alignItems: 'flex-start', padding: '6px 12px' }}
            onClick={() => openRun(r.run_id)} data-testid="session-row" title={runRequirement(r)}>
            <span style={{ paddingTop: 5 }}><StatusDot status={r.status} pulse={r.status === 'running'} /></span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-strong)' }}>{runRequirement(r)}</div>
              <div className="st-faint" style={{ fontSize: 11.5, display: 'flex', gap: 6, alignItems: 'center' }}>
                <Bot size={11} />{r.architecture} · <span style={{ color: r.execution_mode === 'mock' ? 'var(--mock)' : undefined }}>{r.execution_mode}</span> · {timeAgo(runStartedAt(r))}
                {!onlyThisWs && <> · {r.workspace_id}</>}
              </div>
            </div>
          </div>
        ))}
        {list.length > 12 && (
          <div className="st-row" style={{ padding: '4px 12px' }} onClick={() => setShowAll(v => !v)}>
            <span className="name st-muted" style={{ fontWeight: 600 }}>{showAll ? 'Less' : 'More'}</span>
            <span className="st-faint">{showAll ? '' : list.length - 12}</span>
          </div>
        )}
      </div>
      </>}
      <Composer opts={opts} />
    </div>
  );
}

function Composer({ opts }: { opts: Options }) {
  const workspaceId = useStudio(s => s.workspaceId);
  const liveRuns = useLiveRuns();
  const [requirement, setRequirement] = useState('');
  const [architecture, setArchitecture] = useState('sequential');
  const [mode, setMode] = useState<'mock' | 'real'>('mock');
  const [promptVariant, setPromptVariant] = useState('baseline');
  const [verifier, setVerifier] = useState(import.meta.env.VITE_DEFAULT_VERIFIER || 'adk_a2a');
  const [transport, setTransport] = useState(import.meta.env.VITE_DEFAULT_TOOL_TRANSPORT || 'mcp');
  const cred = useLlmCredentials();               // model + key from Settings (kept in this browser only)
  const apiKey = cred.apiKey;
  const model = modelForKey(cred.apiKey, cred.model);
  const [serverLlm, setServerLlm] = useState<{ configured: boolean; model?: string } | null>(null);
  useEffect(() => { VexaApi.systemStatus().then(s => setServerLlm({ configured: s.llm.status === 'configured', model: s.llm.model })).catch(() => {}); }, []);
  const needsKey = mode === 'real' && serverLlm !== null && !serverLlm.configured && !apiKey;
  const [category, setCategory] = useState('');
  const [showConfig, setShowConfig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [g1, setG1] = useState<{ message: string; findings: any[] } | null>(null);
  const [unsaved, setUnsaved] = useState<string[] | null>(null);

  const busyInWs = liveRuns.find(r => r.workspace_id === workspaceId && r.status === 'running');

  const submit = async (confirmReview = false, skipUnsavedCheck = false) => {
    if (!workspaceId || !requirement.trim()) return;
    const dirty = dirtyPaths();
    if (dirty.length && !skipUnsavedCheck) { setUnsaved(dirty); return; }
    setBusy(true);
    try {
      const res = await VexaApi.submitAgentRunAsync({
        workspace_id: workspaceId, requirement, execution_mode: mode, architecture, prompt_variant: promptVariant,
        verifier_backend: verifier, tool_transport: transport, task_category: category || undefined,
        llm_model: mode === 'real' ? model || undefined : undefined, llm_api_key: mode === 'real' ? apiKey || undefined : undefined,
        confirm_guardrail_review: confirmReview || undefined,
      });
      setRequirement('');
      watchRun(res.run_id);
      await openRun(res.run_id);
      loadRecentRuns();
      setState({ panelVisible: true, panelTab: getState().panelTab === 'terminal' ? 'output' : getState().panelTab });
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409 && err.detail?.needs_confirmation) {
        setG1({ message: err.detail.message, findings: err.detail.findings ?? [] });
      } else toast(`Could not start run: ${err.message}`, 'error');
    } finally { setBusy(false); }
  };

  const chip = (label: string, value: string, set: (v: string) => void, options: { name: string; description?: string }[], testId: string) => (
    <label className="st-pill" style={{ height: 22, cursor: 'pointer', position: 'relative' }} title={options.find(o => o.name === value)?.description}>
      {label}: <b style={{ color: 'var(--text)' }}>{value}</b>
      <select data-testid={testId} value={value} onChange={e => set(e.target.value)} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}>
        {options.map(o => <option key={o.name} value={o.name}>{o.name}</option>)}
      </select>
    </label>
  );

  return (
    <div style={{ padding: 10, flex: 'none' }}>
      {busyInWs && (
        <div className="st-muted" style={{ fontSize: 12, marginBottom: 6, padding: '6px 8px', border: '1px solid var(--border)', borderRadius: 6 }}>
          <Loader2 size={12} className="spin" style={{ verticalAlign: -2 }} /> Run {busyInWs.run_id.slice(0, 8)} is working in this workspace{busyInWs.result?.current_agent ? ` — ${busyInWs.result.current_agent}` : ''}.{' '}
          <button className="st-link" onClick={() => openRun(busyInWs.run_id)}>Watch</button>
        </div>
      )}
      <div style={{ border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--bg-panel)' }}>
        {showConfig && (
          <div style={{ padding: 10, borderBottom: '1px solid var(--border)', display: 'grid', gap: 6, fontSize: 12 }}>
            <label>Verifier <select className="st-select" value={verifier} onChange={e => setVerifier(e.target.value)} style={{ width: '100%' }}>
              <option value="adk_a2a">Google ADK over A2A</option><option value="crewai">CrewAI (in-process)</option></select></label>
            <label>Agent tools <select className="st-select" value={transport} onChange={e => setTransport(e.target.value)} style={{ width: '100%' }}>
              <option value="mcp">MCP servers</option><option value="direct">Direct (in-process)</option></select></label>
            <label>Task category (optional) <input className="st-input" value={category} onChange={e => setCategory(e.target.value)} placeholder="e.g. bugfix" style={{ width: '100%', boxSizing: 'border-box' }} /></label>
            {mode === 'real' && (
              <>
                <ModelKeySettings compact serverKey={serverLlm?.configured} serverModel={serverLlm?.model} />
              </>
            )}
          </div>
        )}
        {needsKey && !showConfig && (
          <div data-testid="needs-api-key" style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ flex: 1 }}>Real mode needs an LLM API key — the server has none.</span>
            <button className="st-btn" style={{ height: 22 }} data-testid="add-api-key" onClick={() => setShowConfig(true)}>Add API key</button>
          </div>
        )}
        {mode === 'real' && apiKey && !showConfig && (
          <div className="st-faint" data-testid="key-in-use" style={{ padding: '6px 10px 0', fontSize: 11.5 }}>Using your API key · {model || 'server default model'}</div>
        )}
        <textarea className="st-textarea" data-testid="requirement" rows={3} value={requirement}
          placeholder={workspaceId ? `Describe a change for the agents to make in ${workspaceId}…` : 'Open a workspace first'}
          disabled={!workspaceId}
          onChange={e => setRequirement(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}
          style={{ width: '100%', boxSizing: 'border-box', border: 0, background: 'transparent', padding: '10px 12px' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 8px 8px', flexWrap: 'wrap' }}>
          {chip('arch', architecture, setArchitecture, opts.architectures.length ? opts.architectures : [{ name: architecture }], 'architecture-select')}
          {chip('mode', mode, v => setMode(v as 'mock' | 'real'), [{ name: 'mock', description: 'Scripted agents, no LLM: tests the pipeline, not the agents' }, { name: 'real', description: 'Calls the configured model (billed by your provider)' }], 'execution-mode')}
          {chip('prompt', promptVariant, setPromptVariant, opts.promptVariants.length ? opts.promptVariants : [{ name: promptVariant }], 'prompt-select')}
          <button className="st-icon-btn" title="More run options" onClick={() => setShowConfig(v => !v)} style={{ color: showConfig ? 'var(--text-strong)' : undefined }}><Settings2 size={14} /></button>
          <span style={{ flex: 1 }} />
          <button className="st-icon-btn" data-testid="run-button" title="Start run (⌘↵)" disabled={!workspaceId || !requirement.trim() || busy}
            onClick={() => submit()} style={{ background: requirement.trim() && workspaceId ? 'var(--accent)' : undefined, color: requirement.trim() && workspaceId ? '#fff' : undefined }}>
            {busy ? <Loader2 size={14} className="spin" /> : <ArrowUp size={15} />}
          </button>
        </div>
      </div>
      <div className="st-faint" style={{ fontSize: 11.5, marginTop: 6 }}>
        {mode === 'mock' ? 'Mock: scripted agents, real tools/sandbox/guardrails/tracing. Results say nothing about model quality.' : 'Real: billed model calls. Use Test model first.'}
      </div>
      {g1 && (
        <ConfirmDialog title="Guardrail G1 needs your review" confirmLabel="Run anyway"
          message={<><p style={{ marginTop: 0 }}>{g1.message}</p>{g1.findings.map((f, i) => <div key={i} className="st-mono">• {f.rule}: “{f.match}”</div>)}<p className="st-muted">Your decision is recorded on the run.</p></>}
          onConfirm={() => submit(true, true)} onClose={() => setG1(null)} />
      )}
      {unsaved && (
        <ConfirmDialog title="Unsaved changes" confirmLabel="Save all and run"
          message={<>Agents work on the files on disk. {unsaved.length} file(s) have unsaved edits: <div className="st-mono" style={{ marginTop: 6 }}>{unsaved.join(', ')}</div></>}
          onConfirm={async () => { await saveAll(); submit(false, true); }} onClose={() => setUnsaved(null)} />
      )}
    </div>
  );
}
