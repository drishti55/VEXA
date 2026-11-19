import { X, Bot, FlaskConical, Globe, FilePlus, FolderOpen, FolderPlus, Play, Sparkles, FileCode2, Blocks, ShieldCheck, ListChecks, Gauge, LayoutDashboard, GitCompare } from 'lucide-react';
import { AgentPage } from './pages/AgentPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { BenchmarksPage, CasePage } from './pages/BenchmarkPages';
import { GuardrailsPage, ExtensionPage, SourcePage } from './pages/InspectPages';
import { DashboardPage, ComparePage } from './pages/DashboardPages';
import { useEffect, useState } from 'react';
import { useStudio, setState, closeTab, openRun, getState, openTab } from './store';
import type { Tab } from './store';
import { FileIcon, StatusDot, timeAgo, runRequirement, runStartedAt } from './util';
import { FileEditor } from './editor/FileEditor';
import { RunView } from './run/RunView';
import { ExperimentsPage } from '../ExperimentsPage';
import { WebPreview } from '../WebPreview';
import { useContextMenu } from './common';
import { newWorkspace } from './views/WorkspacePicker';
import { openExperimentsTab } from './views/OtherViews';
import { VexaApi } from '../api/client';
import type { Option } from '../api/client';

function TabIcon({ tab }: { tab: Tab }) {
  if (tab.kind === 'file') return <FileIcon path={tab.path} size={14} />;
  if (tab.kind === 'run') return <Bot size={14} style={{ flex: 'none', color: 'var(--run)' }} />;
  if (tab.kind === 'experiments') return <FlaskConical size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'preview') return <Globe size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'agent') return <Bot size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'source') return <FileCode2 size={14} style={{ flex: 'none', color: 'var(--text-muted)' }} />;
  if (tab.kind === 'extension') return <Blocks size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'guardrails') return <ShieldCheck size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'case' || tab.kind === 'benchmarks') return <ListChecks size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'evaluation') return <Gauge size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'dashboard') return <LayoutDashboard size={14} style={{ flex: 'none' }} />;
  if (tab.kind === 'compare') return <GitCompare size={14} style={{ flex: 'none' }} />;
  return <Sparkles size={14} style={{ flex: 'none', color: 'var(--link)' }} />;
}

export function EditorArea({ filter }: { filter?: (t: Tab) => boolean } = {}) {
  const allTabs = useStudio(s => s.tabs);
  const tabs = filter ? allTabs.filter(filter) : allTabs;
  const activeTabId = useStudio(s => s.activeTabId);
  const buffers = useStudio(s => s.buffers);
  const runs = useStudio(s => s.runs);
  const workspaceId = useStudio(s => s.workspaceId);
  const menu = useContextMenu();
  const active = tabs.find(t => t.id === activeTabId) ?? null;

  const tabMenu = (e: React.MouseEvent, t: Tab) => menu.open(e, [
    { label: 'Close', shortcut: '⌥W', onClick: () => closeTab(t.id) },
    { label: 'Close Others', onClick: () => tabs.filter(x => x.id !== t.id).forEach(x => closeTab(x.id)) },
    { label: 'Close All', onClick: () => [...tabs].forEach(x => closeTab(x.id)) },
    ...(t.kind === 'file' ? ['sep' as const, { label: 'Copy Relative Path', onClick: () => navigator.clipboard?.writeText(t.path) }] : []),
  ]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="st-tabs" role="tablist">
        {tabs.map(t => {
          const b = t.kind === 'file' ? buffers[t.path] : undefined;
          const dirty = !!b && b.loaded && b.content !== b.saved;
          const run = t.kind === 'run' ? runs[t.runId] : undefined;
          return (
            <button key={t.id} role="tab" aria-selected={t.id === activeTabId} data-testid="editor-tab" data-tab={t.id}
              className={`st-tab${t.id === activeTabId ? ' active' : ''}${t.kind === 'file' && t.preview ? ' preview' : ''}`}
              onClick={() => { setState({ activeTabId: t.id }); if (t.kind === 'run') setState({ focusRunId: t.runId }); }}
              onDoubleClick={() => t.kind === 'file' && t.preview && setState(s => ({ tabs: s.tabs.map(x => x.id === t.id ? { ...x, preview: false } as Tab : x) }))}
              onAuxClick={e => { if (e.button === 1) closeTab(t.id); }}
              onContextMenu={e => tabMenu(e, t)} title={t.kind === 'file' ? t.path : t.title}>
              <TabIcon tab={t} />
              <span className="label">{t.title}</span>
              {run && <StatusDot status={run.status} pulse={run.status === 'running'} />}
              <span className={`close${dirty ? ' dirty' : ''}`} onClick={e => { e.stopPropagation(); closeTab(t.id); }} title={dirty ? 'Unsaved changes — close' : 'Close'}>
                {dirty ? <span className="dot" style={{ background: 'var(--text)' }} /> : <X size={14} />}
              </span>
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {!active && (filter ? <ReportsEmpty /> : <EmptyEditor />)}
        {active?.kind === 'welcome' && <Welcome />}
        {active?.kind === 'file' && <FileEditor path={active.path} />}
        {active?.kind === 'run' && <RunView runId={active.runId} />}
        {active?.kind === 'experiments' && <div className="legacy st-scroll" style={{ height: '100%', padding: 16, boxSizing: 'border-box' }}><ExperimentsPage onOpenRun={id => openRun(id)} /></div>}
        {active?.kind === 'agent' && <AgentPage key={active.name} name={active.name} />}
        {active?.kind === 'source' && <SourcePage key={active.path} path={active.path} line={active.line} />}
        {active?.kind === 'extension' && <ExtensionPage key={active.extId} extId={active.extId} />}
        {active?.kind === 'guardrails' && <GuardrailsPage focus={active.focus} />}
        {active?.kind === 'case' && <CasePage key={active.caseId} caseId={active.caseId} />}
        {active?.kind === 'benchmarks' && <BenchmarksPage />}
        {active?.kind === 'evaluation' && <EvaluationPage agent={active.agent} />}
        {active?.kind === 'dashboard' && <DashboardPage />}
        {active?.kind === 'compare' && <ComparePage key={active.id} a={active.a} b={active.b} />}
        {active?.kind === 'preview' && (workspaceId ? <div className="legacy" style={{ height: '100%' }}><WebPreview workspaceId={workspaceId} /></div> : <div className="st-empty st-muted">Open a workspace to preview it.</div>)}
      </div>
      {menu.node}
    </div>
  );
}

function ReportsEmpty() {
  return <div className="st-empty st-muted" style={{ height: '100%', display: 'grid', placeItems: 'center' }}>Pick a report or evaluation on the left.</div>;
}

function EmptyEditor() {
  return (
    <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-faint)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '8px 18px', fontSize: 13 }}>
        <span>Show All Commands</span><span className="st-mono">⇧⌘P</span>
        <span>Go to File</span><span className="st-mono">⌘P</span>
        <span>Toggle Panel</span><span className="st-mono">⌘J</span>
        <span>Toggle Agent Runs</span><span className="st-mono">⌥⌘B</span>
      </div>
    </div>
  );
}

function WelcomeLink({ icon, label, onClick, disabled }: { icon: React.ReactNode; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="st-link" onClick={onClick} disabled={disabled} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, padding: '5px 0', opacity: disabled ? .5 : 1 }}>
      <span style={{ color: 'var(--link)' }}>{icon}</span>{label}
    </button>
  );
}

function Welcome() {
  const recentRuns = useStudio(s => s.recentRuns);
  const workspaces = useStudio(s => s.workspaces);
  const workspaceId = useStudio(s => s.workspaceId);
  const [archs, setArchs] = useState<Option[]>([]);
  useEffect(() => { VexaApi.getArchitectures().then(setArchs).catch(() => {}); }, []);
  return (
    <div className="st-scroll" style={{ height: '100%' }} data-testid="welcome">
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '56px 40px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 48 }}>
        <div>
          <h1 style={{ fontSize: 32, fontWeight: 600, margin: '0 0 4px', color: 'var(--text-strong)' }}>VEXA Studio</h1>
          <div className="st-muted" style={{ marginBottom: 26 }}>Architecture-aware multi-agent software engineering</div>
          <h2 style={{ fontSize: 19, fontWeight: 500, margin: '0 0 8px', color: 'var(--text-strong)' }}>Start</h2>
          <WelcomeLink icon={<FilePlus size={18} />} label="New File…" disabled={!workspaceId} onClick={newFileInExplorer} />
          <WelcomeLink icon={<FolderOpen size={18} />} label="Open Workspace…" disabled={!workspaces.length} onClick={() => setState({ paletteOpen: 'commands', activity: 'explorer', sidebarVisible: true })} />
          <WelcomeLink icon={<FolderPlus size={18} />} label="New Workspace…" onClick={newWorkspace} />
          <WelcomeLink icon={<Play size={18} />} label="Start Agent Run…" disabled={!workspaceId} onClick={focusComposer} />
          <WelcomeLink icon={<FlaskConical size={18} />} label="Open Experiments" onClick={openExperimentsTab} />
          <WelcomeLink icon={<Globe size={18} />} label="Preview Workspace" disabled={!workspaceId} onClick={() => openTab({ id: 'preview', kind: 'preview', title: 'Preview' })} />
          <h2 style={{ fontSize: 19, fontWeight: 500, margin: '26px 0 8px', color: 'var(--text-strong)' }}>Recent runs</h2>
          {recentRuns.length === 0 && <div className="st-muted">No runs recorded yet.</div>}
          {recentRuns.slice(0, 7).map(r => (
            <div key={r.run_id} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '3px 0', minWidth: 0 }}>
              <button className="st-link" onClick={() => openRun(r.run_id)} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280, fontSize: 14 }} title={runRequirement(r)}>
                {runRequirement(r)}
              </button>
              <span className="st-muted" style={{ whiteSpace: 'nowrap', fontSize: 13 }}>{r.workspace_id} · {timeAgo(runStartedAt(r))}</span>
            </div>
          ))}
        </div>
        <div style={{ paddingTop: 64 }}>
          <h2 style={{ fontSize: 19, fontWeight: 500, margin: '0 0 12px', color: 'var(--text-strong)' }}>Orchestration architectures</h2>
          {archs.length === 0 && <div className="st-muted">Architectures are listed once the backend is reachable.</div>}
          {archs.map(a => (
            <div key={a.name} style={{ background: 'var(--bg-inset)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px', marginBottom: 10 }}>
              <div style={{ fontWeight: 600, color: 'var(--text-strong)', marginBottom: 3 }}>{a.name}</div>
              <div className="st-muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{a.description}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export const newFileInExplorer = () => {
  setState({ activity: 'explorer', sidebarVisible: true });
  setTimeout(() => document.querySelector<HTMLButtonElement>('[data-testid=explorer-new-file]')?.click(), 0);
};
export const focusComposer = () => { setState({ rightVisible: true }); setTimeout(() => document.querySelector<HTMLElement>('[data-testid=requirement]')?.focus(), 0); };
export const closeActiveTab = () => { const id = getState().activeTabId; if (id) closeTab(id); };
