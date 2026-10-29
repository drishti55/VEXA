import { useState, useEffect, useRef } from 'react';
import { Play, Activity, Server, FileCode, CheckCircle, XCircle, Loader2, GitCommit, RefreshCw, Terminal, LayoutPanelLeft, Code2, MonitorPlay, Settings, Network, Boxes, Timer, FileText, FlaskConical } from 'lucide-react';
import { ApiError, VexaApi } from './api/client';
import type { Workspace, AgentRunResponse, Option } from './api/client';
import { CodeEditor } from './CodeEditor';
import { WebPreview } from './WebPreview';
import { CoordinationView, ReportView, StateView, TraceView } from './RunInsights';
import { ExperimentsPage } from './ExperimentsPage';

type RightTab = 'observability' | 'coordination' | 'state' | 'trace' | 'report' | 'code' | 'preview';

const AGENTS = [
  'RequirementAnalyst',
  'ProjectAnalyst',
  'Planner',
  'Coder',
  'Tester',
  'Debugger',
  'Verifier'
];

const FINISHED = ['completed', 'success', 'partial', 'failed'];

function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>('');
  const [requirement, setRequirement] = useState('');
  const [executionMode, setExecutionMode] = useState<'mock' | 'real'>('mock');

  const [outputPath, setOutputPath] = useState('');
  const [newWorkspaceName, setNewWorkspaceName] = useState('');
  const [showNewWorkspace, setShowNewWorkspace] = useState(false);
  const [isCreatingWorkspace, setIsCreatingWorkspace] = useState(false);
  const [workspaceCreateError, setWorkspaceCreateError] = useState<string | null>(null);
  const [llmModel, setLlmModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [fallbackApiKey, setFallbackApiKey] = useState('');
  
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runState, setRunState] = useState<AgentRunResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>('observability');
  const [page, setPage] = useState<'run' | 'experiments'>('run');
  const [architecture, setArchitecture] = useState('sequential');
  const [promptVariant, setPromptVariant] = useState('baseline');
  const [taskCategory, setTaskCategory] = useState('');
  const [architectures, setArchitectures] = useState<Option[]>([]);
  const [promptVariants, setPromptVariants] = useState<Option[]>([]);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [verifierBackend, setVerifierBackend] = useState('adk_a2a');
  const [toolTransport, setToolTransport] = useState('mcp');
  const [modelTest, setModelTest] = useState<string | null>(null);
  const [recentRuns, setRecentRuns] = useState<AgentRunResponse[]>([]);

  const logsContainerRef = useRef<HTMLDivElement>(null);

  // Initial load
  useEffect(() => {
    VexaApi.getWorkspaces().then(data => {
      setConnected(true);
      setWorkspaces(data.workspaces);
      if (data.workspaces.length > 0) {
        setSelectedWorkspace(data.workspaces[0].workspace_id);
      }
    }).catch(err => { console.error(err); setConnected(false); });
    VexaApi.getArchitectures().then(setArchitectures).catch(console.error);
    VexaApi.getPromptVariants().then(setPromptVariants).catch(console.error);
    VexaApi.listAgentRuns().then(r => setRecentRuns(r.runs)).catch(console.error);
    // Re-open the last viewed run after a page refresh (persisted on the server)
    let last: string | null = null;
    try { last = localStorage.getItem('vexa:lastRun'); } catch { /* storage unavailable */ }
    if (last) openRun(last, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openRun(runId: string, switchPage = true) {
    VexaApi.getAgentRun(runId).then(run => {
      setRunState(run);
      if (run.status === 'running') setActiveRunId(run.run_id);
      if (switchPage) { setPage('run'); setRightTab('observability'); }
      try { localStorage.setItem('vexa:lastRun', runId); } catch { /* ignore */ }
    }).catch(err => { if (switchPage) alert(`Could not open run: ${err.message}`); });
  }

  const testModel = async () => {
    setModelTest('Testing…');
    try {
      const r = await VexaApi.testModel(llmModel || undefined, apiKey || undefined);
      setModelTest(r.ok ? `✓ ${r.model} (${r.provider}) answered in ${Math.round(r.latency_ms ?? 0)} ms`
        : `✗ ${r.model} (${r.provider}): ${r.error}`);
    } catch (err: any) {
      setModelTest(`✗ ${err.message}`);
    }
  };

  // Live updates over server-sent events (falls back to polling)
  useEffect(() => {
    if (!activeRunId) return;
    let latest: AgentRunResponse | null = null;
    const stop = VexaApi.streamRun(
      activeRunId,
      run => { latest = run; setRunState(run); },
      () => {
        // The last live snapshot can predate the final result (usage, verifier, report): load the stored run.
        VexaApi.getAgentRun(activeRunId).then(setRunState).catch(console.error);
        setActiveRunId(null);
        setCancelling(false);
        if (latest?.workspace_id) {
          VexaApi.getFileDiff(latest.workspace_id).then(setDiff).catch(console.error);
        }
      },
    );
    return stop;
  }, [activeRunId]);

  // Auto scroll logs
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [runState?.result?.events]);

  const shownMode = (runState?.execution_mode as string | undefined) ?? executionMode;

  const handleRun = async (confirmGuardrailReview = false) => {
    if (!selectedWorkspace || !requirement) return;
    setIsSubmitting(true);
    setRunState(null);
    setDiff(null);
    try {
      // We pass execution_mode and overrides
      const res = await VexaApi.submitAgentRunAsync({
        confirm_guardrail_review: confirmGuardrailReview || undefined,
        task_category: taskCategory || undefined,
        workspace_id: selectedWorkspace,
        requirement,
        execution_mode: executionMode,
        architecture,
        prompt_variant: promptVariant,
        verifier_backend: verifierBackend,
        tool_transport: toolTransport,
        llm_model: llmModel || undefined,
        llm_api_key: apiKey || undefined,
        llm_fallback_api_key: fallbackApiKey || undefined,
      });
      setActiveRunId(res.run_id);
      try { localStorage.setItem('vexa:lastRun', res.run_id); } catch { /* ignore */ }
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409 && err.detail?.needs_confirmation) {
        // G1 flagged an ambiguous requirement: a human decides, and the decision is recorded on the run.
        const matches = (err.detail.findings ?? []).map((f: any) => `• ${f.rule}: "${f.match}"`).join('\n');
        setIsSubmitting(false);
        if (window.confirm(`Guardrail G1 needs your review.\n\n${err.detail.message}\n\n${matches}\n\nRun anyway?`)) {
          await handleRun(true);
        }
        return;
      }
      alert(`Error starting run: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Mirrors backend/tools/workspace.py validate_workspace_id (the server re-checks).
  const workspaceNameError = (name: string): string | null => {
    if (!name) return null;  // empty = server generates an id
    if (name !== name.trim()) return 'Name cannot start or end with a space.';
    if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}$/.test(name) || name.includes('..'))
      return "Use letters, digits, spaces, '_', '-' or '.'; start with a letter or digit; max 128 characters.";
    if (workspaces.some(w => w.workspace_id === name)) return `A workspace named '${name}' already exists.`;
    return null;
  };
  const nameError = workspaceNameError(newWorkspaceName);

  const handleCreateWorkspace = async () => {
    if (nameError) return;
    setIsCreatingWorkspace(true);
    setWorkspaceCreateError(null);
    try {
      const ws = await VexaApi.createWorkspace(newWorkspaceName || undefined, outputPath || undefined);
      setWorkspaces(prev => [...prev, ws]);
      setSelectedWorkspace(ws.workspace_id);
      setOutputPath('');
      setNewWorkspaceName('');
      setShowNewWorkspace(false);
    } catch (err: any) {
      setWorkspaceCreateError(err.message || 'Failed to create workspace');
    } finally {
      setIsCreatingWorkspace(false);
    }
  };

  // The pipeline is drawn from the architecture's actual dispatch log, so
  // hierarchical revisions, manager decisions and debug loops are visible.
  const pipelineSteps = (): { agent: string; state: string; note?: string }[] => {
    const res = runState?.result;
    const dispatches = (res?.coordination_log ?? []).filter(c => c.kind === 'dispatch');
    const events = res?.events ?? [];
    if (dispatches.length === 0) {
      return AGENTS.map(a => ({ agent: a, state: 'pending', note: architecture === 'sequential' ? undefined : 'order decided at run time' }));
    }
    const outcomes: Record<string, string[]> = {};
    for (const e of events) {
      if (e.event === 'completed' || e.event === 'failed') (outcomes[e.agent] ??= []).push(e.event);
    }
    const seen: Record<string, number> = {};
    const revisions = (res?.coordination_log ?? []).filter(c => c.kind === 'decision' && c.data?.revision).map(c => c.seq);
    return dispatches.map(d => {
      const agent = d.target ?? '?';
      const k = seen[agent] = (seen[agent] ?? 0) + 1;
      const outcome = outcomes[agent]?.[k - 1];
      const state = outcome ?? (runState?.status === 'running' ? 'running' : 'pending');
      const isRevision = revisions.some(seq => seq === d.seq - 1 || seq === d.seq - 2);
      return { agent, state: state === 'completed' ? 'completed' : state, note: `${d.actor}${k > 1 ? ` · #${k}` : ''}${isRevision ? ' · revision' : ''}` };
    });
  };

  return (
    <div className="min-h-screen flex flex-col bg-vexa-bg text-vexa-text font-sans">
      
      {/* Top Bar */}
      <header className="flex items-center justify-between px-6 py-4 bg-vexa-panel border-b border-vexa-border">
        <div className="flex items-center space-x-4">
          <Activity className="w-6 h-6 text-vexa-accent" />
          <h1 className="text-xl font-bold tracking-tight">VEXA</h1>
          <span className="text-xs text-vexa-muted tracking-widest uppercase ml-4 hidden sm:inline-block">
            Architecture-Aware Autonomous Agent System
          </span>
        </div>
        <div className="flex items-center space-x-6 text-sm">
          <nav className="flex rounded overflow-hidden border border-vexa-border">
            <button data-testid="nav-run" onClick={() => setPage('run')} className={`px-3 py-1 text-xs flex items-center gap-1 ${page === 'run' ? 'bg-vexa-accent text-white' : 'text-vexa-muted hover:text-white'}`}><Play className="w-3 h-3" />Run</button>
            <button data-testid="nav-experiments" onClick={() => setPage('experiments')} className={`px-3 py-1 text-xs flex items-center gap-1 ${page === 'experiments' ? 'bg-vexa-accent text-white' : 'text-vexa-muted hover:text-white'}`}><FlaskConical className="w-3 h-3" />Experiments</button>
          </nav>
          <div className="flex items-center space-x-2">
            <span className="text-vexa-muted">Architecture:</span>
            <span className="font-mono bg-black/30 px-2 py-1 rounded">{runState?.architecture ?? architecture}</span>
          </div>
          <div className="flex items-center space-x-2">
            <span className="text-vexa-muted">Mode:</span>
            {/* the opened run's mode (not the form's), like the Architecture badge */}
            <span data-testid="header-mode" className={`font-mono px-2 py-1 rounded flex items-center space-x-1 ${shownMode === 'real' ? 'text-vexa-warning bg-vexa-warning/10' : 'text-vexa-success bg-vexa-success/10'}`}>
              <div className={`w-2 h-2 rounded-full ${shownMode === 'real' ? 'bg-vexa-warning' : 'bg-vexa-success'}`} />
              <span>{shownMode.toUpperCase()}</span>
            </span>
          </div>
          <div className="flex items-center space-x-2">
            <Server className={`w-4 h-4 ${connected === false ? 'text-vexa-error' : 'text-vexa-success'}`} />
            <span className={connected === false ? 'text-vexa-error' : 'text-vexa-success'}>
              {connected === null ? 'Connecting…' : connected ? 'Connected' : 'Backend unreachable'}
            </span>
          </div>
        </div>
      </header>

      {page === 'experiments' ? <ExperimentsPage onOpenRun={id => openRun(id)} /> : (
      <main className="flex-1 flex flex-col lg:flex-row overflow-y-auto lg:overflow-hidden">
        
        {/* Left Column: Input Controls */}
        <div className="w-full lg:w-1/3 p-6 flex flex-col border-r border-vexa-border overflow-y-auto">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-vexa-muted mb-4">Task Specification</h2>
          
          <div className="space-y-4 flex-1">
            <div className="flex flex-col space-y-2">
              <label className="text-sm text-vexa-muted">Workspace</label>
              <div className="flex gap-2">
                <select
                  className="flex-1 min-w-0 bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent transition-colors"
                  data-testid="workspace-select"
                  value={selectedWorkspace}
                  onChange={e => setSelectedWorkspace(e.target.value)}
                  disabled={activeRunId !== null}
                >
                  {(workspaces || []).length === 0 && <option value="">— no workspaces yet —</option>}
                  {(workspaces || []).map(ws => (
                    <option key={ws.workspace_id} value={ws.workspace_id}>{ws.workspace_id}</option>
                  ))}
                </select>
                <button
                  data-testid="new-workspace-toggle"
                  type="button"
                  className={`px-3 rounded text-xs font-semibold border transition-colors ${showNewWorkspace ? 'bg-vexa-accent text-white border-vexa-accent' : 'border-vexa-accent text-vexa-accent bg-vexa-accent/10 hover:bg-vexa-accent/30'}`}
                  onClick={() => { setShowNewWorkspace(v => !v); setWorkspaceCreateError(null); }}
                  disabled={activeRunId !== null}
                  title="Create a new workspace"
                >
                  + New
                </button>
              </div>
            </div>

            {showNewWorkspace && (
              <div data-testid="new-workspace-form" className="flex flex-col space-y-2 border border-vexa-accent/50 rounded p-3 bg-black/10">
                <label className="text-xs font-semibold uppercase tracking-wider text-vexa-muted">New Workspace</label>
                <div className="flex flex-col space-y-1">
                  <label htmlFor="new-workspace-name" className="text-xs text-vexa-muted">Name <span className="text-vexa-muted/50">(optional; a random id is used if empty)</span></label>
                  <input
                    id="new-workspace-name"
                    data-testid="new-workspace-name"
                    type="text"
                    autoFocus
                    maxLength={128}
                    className={`bg-vexa-bg border p-2 rounded font-mono text-xs focus:outline-none transition-colors ${nameError ? 'border-red-400' : 'border-vexa-border focus:border-vexa-accent'}`}
                    placeholder="e.g. my-calculator-app"
                    value={newWorkspaceName}
                    onChange={e => setNewWorkspaceName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleCreateWorkspace(); }}
                    disabled={isCreatingWorkspace}
                  />
                  {nameError && <p data-testid="new-workspace-name-error" className="text-xs text-red-400">{nameError}</p>}
                </div>
                <div className="flex flex-col space-y-1">
                  <label htmlFor="output-path-input" className="text-xs text-vexa-muted">Output Folder <span className="text-vexa-muted/50">(optional; must be under the server's WORKSPACE_ALLOWED_OUTPUT_ROOTS)</span></label>
                  <input
                    id="output-path-input"
                    type="text"
                    className="bg-vexa-bg border border-vexa-border p-2 rounded font-mono text-xs focus:outline-none focus:border-vexa-accent transition-colors"
                    placeholder="e.g. /Users/you/Projects/my-app"
                    value={outputPath}
                    onChange={e => setOutputPath(e.target.value)}
                    disabled={isCreatingWorkspace}
                  />
                </div>
                {workspaceCreateError && (
                  <p data-testid="new-workspace-error" className="text-xs text-red-400">{workspaceCreateError}</p>
                )}
                <div className="flex gap-2">
                  <button
                    id="create-workspace-btn"
                    data-testid="create-workspace"
                    className={`flex-1 py-1.5 rounded text-xs font-semibold flex items-center justify-center space-x-1 transition-colors ${
                      isCreatingWorkspace || nameError
                        ? 'bg-vexa-border text-vexa-muted cursor-not-allowed'
                        : 'bg-vexa-accent/20 hover:bg-vexa-accent/40 border border-vexa-accent text-vexa-accent'
                    }`}
                    onClick={handleCreateWorkspace}
                    disabled={isCreatingWorkspace || nameError !== null}
                  >
                    {isCreatingWorkspace ? (
                      <><Loader2 className="w-3 h-3 animate-spin" /><span>Creating...</span></>
                    ) : (
                      <span>Create workspace</span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="px-3 py-1.5 rounded text-xs border border-vexa-border text-vexa-muted hover:text-white"
                    onClick={() => { setShowNewWorkspace(false); setWorkspaceCreateError(null); }}
                    disabled={isCreatingWorkspace}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {recentRuns.length > 0 && (
              <div className="flex flex-col space-y-2">
                <label className="text-sm text-vexa-muted">Open a previous run</label>
                <select className="bg-vexa-panel border border-vexa-border p-2 rounded text-xs focus:outline-none focus:border-vexa-accent"
                  data-testid="recent-runs" value="" onChange={e => e.target.value && openRun(e.target.value)}>
                  <option value="">— recent runs ({recentRuns.length}) —</option>
                  {recentRuns.slice(0, 50).map(r => (
                    <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 8)} · {r.architecture} · {r.execution_mode} · {r.status}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="flex flex-col space-y-2">
              <label className="text-sm text-vexa-muted">Requirement</label>
              <textarea data-testid="requirement"
                className="bg-vexa-panel border border-vexa-border p-3 rounded h-40 focus:outline-none focus:border-vexa-accent transition-colors resize-none font-mono text-sm"
                placeholder="Describe what you want VEXA to build or modify..."
                value={requirement}
                onChange={e => setRequirement(e.target.value)}
                disabled={activeRunId !== null}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col space-y-2">
                <label className="text-sm text-vexa-muted">Execution Mode</label>
                <select 
                  className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  data-testid="execution-mode"
                  value={executionMode}
                  onChange={e => setExecutionMode(e.target.value as any)}
                  disabled={activeRunId !== null}
                >
                  <option value="mock">Mock (Deterministic)</option>
                  <option value="real">Real (Live LLM)</option>
                </select>
              </div>
              <div className="flex flex-col space-y-2">
                <label className="text-sm text-vexa-muted">Architecture</label>
                <select
                  className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  data-testid="architecture-select"
                  value={architecture}
                  onChange={e => setArchitecture(e.target.value)}
                  disabled={activeRunId !== null}
                  title={architectures.find(a => a.name === architecture)?.description}
                >
                  {(architectures.length ? architectures : [{ name: 'sequential', description: '' }]).map(a => (
                    <option key={a.name} value={a.name}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col space-y-2">
                <label className="text-sm text-vexa-muted">Verifier</label>
                <select className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  value={verifierBackend} onChange={e => setVerifierBackend(e.target.value)} disabled={activeRunId !== null}>
                  <option value="adk_a2a">Google ADK over A2A</option>
                  <option value="crewai">CrewAI (in-process)</option>
                </select>
              </div>
              <div className="flex flex-col space-y-2">
                <label className="text-sm text-vexa-muted">Agent tools</label>
                <select className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  value={toolTransport} onChange={e => setToolTransport(e.target.value)} disabled={activeRunId !== null}>
                  <option value="mcp">via MCP server</option>
                  <option value="direct">direct (no MCP)</option>
                </select>
              </div>
              <div className="flex flex-col space-y-2 col-span-2">
                <label className="text-sm text-vexa-muted">Prompt strategy</label>
                <select
                  className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  value={promptVariant}
                  onChange={e => setPromptVariant(e.target.value)}
                  disabled={activeRunId !== null}
                >
                  {(promptVariants.length ? promptVariants : [{ name: 'baseline', description: '' }]).map(v => (
                    <option key={v.name} value={v.name}>{v.name}{v.description ? ` — ${v.description}` : ''}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col space-y-2 col-span-2">
                <label className="text-sm text-vexa-muted" title="Structured category; the hierarchical mock policy uses it to choose its route">Task category</label>
                <select data-testid="task-category"
                  className="bg-vexa-panel border border-vexa-border p-2 rounded focus:outline-none focus:border-vexa-accent"
                  value={taskCategory} onChange={e => setTaskCategory(e.target.value)} disabled={activeRunId !== null}>
                  <option value="">unspecified</option>
                  {['feature', 'bug_fix', 'refactoring', 'testing', 'performance', 'security', 'configuration', 'error_handling', 'api', 'database', 'bug_fix,feature'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* LLM Configuration Panel */}
            <div className="flex flex-col space-y-3 mt-4 border border-vexa-border rounded p-4 bg-black/10">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-vexa-muted flex items-center space-x-2">
                <Settings className="w-3 h-3" />
                <span>LLM Configuration</span>
              </h3>
              
              <div className="flex flex-col space-y-1">
                <label className="text-xs text-vexa-muted flex justify-between">
                  <span>Model String</span>
                  <span className="text-[10px] text-vexa-muted/50">Overrides .env default</span>
                </label>
                <div className="relative">
                  <input
                    list="models-list"
                    className="w-full bg-vexa-bg border border-vexa-border p-2 rounded font-mono text-xs focus:outline-none focus:border-vexa-accent transition-colors"
                    placeholder="e.g. groq/openai/gpt-oss-120b"
                    data-testid="llm-model"
                    value={llmModel}
                    onChange={e => setLlmModel(e.target.value)}
                    disabled={activeRunId !== null}
                  />
                  <datalist id="models-list">
                    <option value="groq/llama-3.3-70b-versatile">Groq · Llama 3.3 70B (check availability with Test)</option>
                    <option value="groq/openai/gpt-oss-120b">Groq · GPT-OSS 120B</option>
                    <option value="openai/gpt-4o-mini">OpenAI · GPT-4o mini</option>
                    <option value="gemini/gemini-2.0-flash">Google · Gemini 2.0 Flash</option>
                  </datalist>
                </div>
              </div>

              <div className="flex flex-col space-y-1">
                <label className="text-xs text-vexa-muted">Primary API Key</label>
                <input
                  type="password"
                  className="bg-vexa-bg border border-vexa-border p-2 rounded font-mono text-xs focus:outline-none focus:border-vexa-accent transition-colors"
                  placeholder="Leave blank to use .env key"
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  disabled={activeRunId !== null}
                />
              </div>

              <div className="flex items-center gap-2">
                <button type="button" onClick={testModel} disabled={activeRunId !== null}
                  className="px-3 py-1.5 rounded border border-vexa-border text-xs hover:bg-black/30">Test model</button>
                <span className="text-[11px] text-vexa-muted">1-token call; provider is taken from the model prefix</span>
              </div>
              {modelTest && <div className={`text-xs break-words ${modelTest.startsWith('✓') ? 'text-vexa-success' : modelTest.startsWith('✗') ? 'text-vexa-error' : 'text-vexa-muted'}`}>{modelTest}</div>}

              <div className="flex flex-col space-y-1">
                <label className="text-xs text-vexa-muted">Fallback API Key</label>
                <input
                  type="password"
                  className="bg-vexa-bg border border-vexa-border p-2 rounded font-mono text-xs focus:outline-none focus:border-vexa-accent transition-colors"
                  placeholder="Leave blank to use .env key"
                  value={fallbackApiKey}
                  onChange={e => setFallbackApiKey(e.target.value)}
                  disabled={activeRunId !== null}
                />
              </div>
            </div>

          </div>

          <div className="mt-8">
            <button
              className={`w-full py-3 rounded font-bold flex items-center justify-center space-x-2 transition-colors ${
                !selectedWorkspace || !requirement || activeRunId || isSubmitting
                  ? 'bg-vexa-border text-vexa-muted cursor-not-allowed'
                  : 'bg-vexa-accent hover:bg-vexa-accent-hover text-white'
              }`}
              data-testid="run-button"
              onClick={() => handleRun()}
              disabled={!selectedWorkspace || !requirement || activeRunId !== null || isSubmitting}
            >
              {(isSubmitting || activeRunId) ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>VEXA IS RUNNING</span>
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  <span>RUN VEXA</span>
                </>
              )}
            </button>
            {activeRunId && (
              <button
                data-testid="cancel-run"
                className="w-full mt-2 py-2 rounded text-sm font-semibold border border-vexa-error text-vexa-error hover:bg-vexa-error/10 disabled:opacity-50"
                disabled={cancelling}
                title="Stops before the next agent starts; a request already sent to the model is not interrupted"
                onClick={() => {
                  setCancelling(true);
                  VexaApi.cancelAgentRun(activeRunId).catch(err => alert(`Could not cancel: ${err.message}`));
                }}
              >
                {cancelling ? 'Stopping after the current agent…' : 'Stop run'}
              </button>
            )}
          </div>
        </div>

        {/* Right Column: Dynamic Tabs */}
        <div className="w-full lg:w-2/3 flex flex-col bg-black/20 min-h-[600px] lg:min-h-0">
          
          {/* Tabs Bar */}
          <div className="flex border-b border-vexa-border bg-vexa-bg overflow-x-auto">
            {([
              ['observability', 'Overview', LayoutPanelLeft],
              ['coordination', 'Coordination', Network],
              ['state', 'State', Boxes],
              ['trace', 'Trace', Timer],
              ['report', 'Report', FileText],
              ['code', 'Code', Code2],
              ['preview', 'Preview', MonitorPlay],
            ] as const).map(([id, label, Icon]) => (
              <button
                key={id}
                className={`flex-1 min-w-24 py-3 text-xs font-bold uppercase tracking-wider flex items-center justify-center space-x-2 transition-colors ${rightTab === id ? 'text-vexa-accent border-b-2 border-vexa-accent bg-vexa-panel' : 'text-vexa-muted hover:bg-vexa-panel hover:text-white'}`}
                data-testid={`tab-${id}`}
                onClick={() => setRightTab(id)}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
              </button>
            ))}
          </div>

          {(['coordination', 'state', 'trace', 'report'] as RightTab[]).includes(rightTab) && (
            <div className="flex-1 overflow-y-auto p-4">
              {rightTab === 'coordination' && <CoordinationView result={runState?.result} />}
              {rightTab === 'state' && <StateView result={runState?.result} />}
              {rightTab === 'trace' && <TraceView result={runState?.result} />}
              {rightTab === 'report' && <ReportView runId={runState?.run_id ?? null} finished={!!runState && FINISHED.includes(runState.status)} />}
            </div>
          )}

          {rightTab === 'observability' && (
            <div className="flex flex-col flex-1 overflow-hidden">
              {/* Summary Strip */}
              <div className="grid grid-cols-6 border-b border-vexa-border bg-vexa-panel/50 shrink-0">
                <MetricBox testId="run-status" label="STATUS"
                  value={runState ? runState.status.toUpperCase() + (runState.execution_mode === 'mock' ? ' · MOCK' : '') : 'READY'}
                  color={runState?.status === 'failed' ? 'text-vexa-error' : runState?.status === 'partial' ? 'text-vexa-warning' : (runState?.status === 'completed' || runState?.status === 'success') ? 'text-vexa-success' : runState?.status === 'running' ? 'text-vexa-accent' : ''} />
                <MetricBox label="TIME" value={runState ? `${(runState.total_duration_ms / 1000).toFixed(1)}s` : '-'} />
                <MetricBox label="DEBUG ITERS" value={runState?.result?.debug_iterations?.toString() || '0'} />
                <MetricBox label="TOKENS" value={runState?.result?.usage_available ? runState.result.total_tokens.toLocaleString() : 'N/A'} />
                <MetricBox label="COST" value={runState?.result?.estimated_cost_usd != null ? `$${runState.result.estimated_cost_usd.toFixed(4)}` : 'N/A'} />
                <MetricBox label="FILES" value={runState?.result?.files_changed?.length?.toString() || '0'} />
              </div>

              {/* Main Dashboard Area */}
              <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4 p-4 overflow-y-auto">
                
                {/* Agent Pipeline */}
                <div className="bg-vexa-panel border border-vexa-border rounded p-4 flex flex-col">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-4 flex items-center"><Activity className="w-4 h-4 mr-2" /> Agent Pipeline</h3>
                  <div className="flex-1 flex flex-col space-y-1">
                    {pipelineSteps().map(({ agent, state, note }, idx, steps) => {
                      return (
                        <div key={`${agent}-${idx}`} className="flex items-center relative py-2">
                          {/* Vertical line connector */}
                          {idx !== steps.length - 1 && (
                            <div className={`absolute left-3 top-8 bottom-[-8px] w-0.5 ${state === 'completed' ? 'bg-vexa-success' : 'bg-vexa-border'}`} />
                          )}
                          
                          <div className={`z-10 w-6 h-6 rounded-full flex items-center justify-center mr-4 border-2 ${
                            state === 'completed' ? 'bg-vexa-bg border-vexa-success text-vexa-success' :
                            state === 'running' ? 'bg-vexa-accent border-vexa-accent text-white animate-pulse' :
                            state === 'failed' ? 'bg-vexa-bg border-vexa-error text-vexa-error' :
                            'bg-vexa-bg border-vexa-border text-vexa-muted'
                          }`}>
                            {state === 'completed' ? <CheckCircle className="w-4 h-4" /> :
                             state === 'failed' ? <XCircle className="w-4 h-4" /> :
                             state === 'running' ? <RefreshCw className="w-3 h-3 animate-spin" /> :
                             <div className="w-2 h-2 rounded-full bg-vexa-muted" />}
                          </div>
                          
                          <span className={`font-mono text-sm ${state === 'running' ? 'text-white' : state === 'pending' ? 'text-vexa-muted' : ''}`}>
                            {agent}
                          </span>
                          {note && <span className="ml-2 text-[10px] text-vexa-muted">{note}</span>}
                          {state === 'running' && <span className="ml-auto text-xs text-vexa-accent font-bold tracking-wider">RUNNING</span>}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Live Activity Log */}
                <div className="bg-vexa-panel border border-vexa-border rounded p-4 flex flex-col h-96 md:h-auto">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-4 flex items-center"><Terminal className="w-4 h-4 mr-2" /> Live Activity</h3>
                  <div ref={logsContainerRef} className="flex-1 bg-black/40 border border-vexa-border rounded p-3 overflow-y-auto font-mono text-xs">
                    {(!runState || !runState.result?.events || runState.result.events.length === 0) ? (
                      <div className="text-vexa-muted italic">Waiting for execution to begin...</div>
                    ) : (
                      <div className="space-y-2">
                        {runState.result.events.map((e, i) => (
                          <div key={i} className="flex space-x-3 items-start">
                            <span className="text-vexa-muted shrink-0">{new Date(e.timestamp).toLocaleTimeString([], {hour12: false})}</span>
                            <span className={
                              e.event === 'started' || e.event === 'completed' ? 'text-vexa-accent' :
                              e.event === 'tool_failed' ? 'text-vexa-error' :
                              e.event === 'test_started' ? 'text-vexa-warning' :
                              'text-white'
                            }>[{e.agent}]</span>
                            <span className="text-gray-300 break-words">{e.event} {e.detail ? `- ${e.detail}` : ''}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* File Changes */}
                <div className="bg-vexa-panel border border-vexa-border rounded p-4 flex flex-col col-span-1 md:col-span-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-vexa-muted mb-4 flex items-center"><GitCommit className="w-4 h-4 mr-2" /> File Changes & Verification</h3>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <h4 className="text-xs text-vexa-muted">Modified Files:</h4>
                      {(!runState?.result?.files_changed || runState.result.files_changed.length === 0) ? (
                        <div className="text-sm text-vexa-muted font-mono bg-black/40 p-2 rounded">No files changed yet</div>
                      ) : (
                        <ul className="space-y-1">
                          {runState.result.files_changed.map((f, i) => {
                            const pathName = typeof f === 'string' ? f : (f as any).path;
                            return (
                              <li key={i} className="text-sm font-mono flex items-center text-vexa-success">
                                <FileCode className="w-3 h-3 mr-2" /> {pathName}
                              </li>
                            );
                          })}
                        </ul>
                      )}

                      {diff && (
                        <div className="mt-4">
                          <h4 className="text-xs text-vexa-muted mb-2">Final Diff:</h4>
                          <pre className="bg-black/40 border border-vexa-border p-3 rounded text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-60">
                            {diff || "No git diff available."}
                          </pre>
                        </div>
                      )}
                    </div>

                    <div>
                      <h4 className="text-xs text-vexa-muted mb-2">Errors / Verification:</h4>
                      {(!runState?.result?.errors || runState.result.errors.length === 0) ? (
                        <div className="text-sm text-vexa-success flex items-center font-mono bg-black/40 p-2 rounded">
                          <CheckCircle className="w-4 h-4 mr-2" /> No errors reported
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {runState.result.errors.map((err, i) => (
                            <div key={i} className="text-xs font-mono bg-vexa-error/10 text-vexa-error border border-vexa-error/20 p-2 rounded break-words max-h-60 overflow-y-auto">
                              {err}
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {runState?.status === 'success' && (
                         <div className="mt-4 bg-vexa-success/10 border border-vexa-success/30 p-3 rounded flex items-center text-vexa-success">
                           <CheckCircle className="w-5 h-5 mr-3" />
                           <span className="font-bold">VERIFIED · TESTS PASS (sandbox)</span>
                         </div>
                      )}
                      {runState?.status === 'partial' && (
                         <div className="mt-4 bg-vexa-warning/10 border border-vexa-warning/30 p-3 rounded text-vexa-warning text-xs">
                           <span className="font-bold">PARTIAL · </span>
                           {runState.execution_mode === 'mock' && !(runState.result?.files_changed?.length)
                             ? 'Mock run: scripted agents changed no code, so the requirement was not implemented.'
                             : runState.result?.final_test_result?.no_tests
                             ? 'No tests were collected, so the change is not test-verified.'
                             : runState.result?.verification_result?.verified === false
                               ? 'Tests pass, but the Verifier found unmet requirements.'
                               : 'Tests and verification disagree; see the report.'}
                         </div>
                      )}
                    </div>
                  </div>
                </div>

              </div>
            </div>
          )}

          {rightTab === 'code' && (
            <div className="flex-1 overflow-hidden">
              <CodeEditor workspaceId={selectedWorkspace} />
            </div>
          )}

          {rightTab === 'preview' && (
            <div className="flex-1 overflow-hidden">
              <WebPreview workspaceId={selectedWorkspace} />
            </div>
          )}

        </div>
      </main>
      )}
    </div>
  );
}

function MetricBox({ label, value, color = '', testId }: { label: string, value: string, color?: string, testId?: string }) {
  return (
    <div className="p-3 border-r border-vexa-border last:border-r-0 flex flex-col justify-center">
      <div className="text-[10px] font-bold text-vexa-muted mb-1">{label}</div>
      <div data-testid={testId} className={`font-mono text-sm tracking-tight ${color}`}>{value}</div>
    </div>
  );
}

export default App;
