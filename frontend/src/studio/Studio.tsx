import { useEffect, useRef, useState } from 'react';
import {
  Files, Search, GitBranch, Bug, Blocks, Bot, FlaskConical, Gauge, ListChecks, Activity, Settings, ArrowLeft, ArrowRight,
  PanelLeft, PanelBottom, PanelRight, Code2, BarChart3, CircleX, TriangleAlert, Bell, Radio, Database, Cpu, Network, Plug, Moon, Sun, Info,
} from 'lucide-react';
import './studio.css';
import { useStudio, useLiveRuns, setState, getState, loadWorkspaces, loadRecentRuns, saveFile, saveAll, setTheme, closeTab, setMode, REPORT_KINDS } from './store';
import type { Tab } from './store';
import { ReportsNav } from './views/ReportsNav';
import type { ActivityId } from './store';
import { ExplorerView } from './views/ExplorerView';
import { SearchView } from './views/SearchView';
import { ScmView } from './views/ScmView';
import { RunDebugView, ExperimentsView, BenchmarksView, MonitoringView, AgentsView, EvaluationView, ExtensionsView } from './views/OtherViews';
import { NewWorkspaceDialog } from './views/WorkspacePicker';
import { SettingsView, NotificationList } from './views/SettingsView';
import { EditorArea } from './EditorArea';
import { BottomPanel, usePanelRun, problemsOf } from './BottomPanel';
import { RunPanel } from './RunPanel';
import { CommandPalette } from './CommandPalette';
import { VexaApi } from '../api/client';
import type { SystemStatus } from '../api/client';

const ACTIVITIES: { id: ActivityId; label: string; icon: React.ReactNode }[] = [
  { id: 'explorer', label: 'Explorer (⇧⌘E)', icon: <Files size={22} strokeWidth={1.6} /> },
  { id: 'search', label: 'Search (⇧⌘F)', icon: <Search size={22} strokeWidth={1.6} /> },
  { id: 'scm', label: 'Source Control', icon: <GitBranch size={22} strokeWidth={1.6} /> },
  { id: 'run', label: 'Run and Debug', icon: <Bug size={22} strokeWidth={1.6} /> },
  { id: 'extensions', label: 'Extensions', icon: <Blocks size={22} strokeWidth={1.6} /> },
  { id: 'agents', label: 'Agents', icon: <Bot size={22} strokeWidth={1.6} /> },
  { id: 'experiments', label: 'Experiments', icon: <FlaskConical size={22} strokeWidth={1.6} /> },
  { id: 'evaluation', label: 'Evaluation', icon: <Gauge size={22} strokeWidth={1.6} /> },
  { id: 'benchmarks', label: 'Benchmarks', icon: <ListChecks size={22} strokeWidth={1.6} /> },
  { id: 'monitoring', label: 'Monitoring', icon: <Activity size={22} strokeWidth={1.6} /> },
];

function Sidebar() {
  const activity = useStudio(s => s.activity);
  switch (activity) {
    case 'explorer': return <ExplorerView />;
    case 'search': return <SearchView />;
    case 'scm': return <ScmView />;
    case 'run': return <RunDebugView />;
    case 'experiments': return <ExperimentsView />;
    case 'benchmarks': return <BenchmarksView />;
    case 'monitoring': return <MonitoringView />;
    case 'agents': return <AgentsView />;
    case 'extensions': return <ExtensionsView />;
    case 'evaluation': return <EvaluationView />;
    case 'settings': return <SettingsView />;
  }
}

function ActivityBar() {
  const activity = useStudio(s => s.activity);
  const sidebarVisible = useStudio(s => s.sidebarVisible);
  const liveCount = useStudio(s => s.liveRunIds.length);
  const click = (id: ActivityId) => setState(s => s.activity === id && s.sidebarVisible ? { sidebarVisible: false } : { activity: id, sidebarVisible: true });
  return (
    <div className="st-activity" role="tablist" aria-label="Activity bar">
      {ACTIVITIES.map(a => (
        <button key={a.id} className={`st-act${activity === a.id && sidebarVisible ? ' active' : ''}`} title={a.label} aria-label={a.label}
          onClick={() => click(a.id)} data-testid={`activity-${a.id}`}>
          {a.icon}
          {a.id === 'run' && liveCount > 0 && <span className="st-badge badge">{liveCount}</span>}
        </button>
      ))}
      <span style={{ flex: 1 }} />
      <button className={`st-act${activity === 'settings' && sidebarVisible ? ' active' : ''}`} title="Settings (⌘,)" aria-label="Settings"
        onClick={() => click('settings')} data-testid="activity-settings"><Settings size={22} strokeWidth={1.6} /></button>
    </div>
  );
}

function ModeSwitch() {
  const mode = useStudio(s => s.mode);
  const btn = (id: 'ide' | 'reports', label: string, icon: React.ReactNode, hint: string) => (
    <button role="tab" aria-selected={mode === id} data-testid={`mode-${id}`} title={hint} onClick={() => setMode(id)}
      style={{ display: 'flex', alignItems: 'center', gap: 5, border: 0, borderRadius: 4, padding: '2px 9px', font: 'inherit', fontSize: 12, cursor: 'pointer',
        background: mode === id ? 'var(--bg-active)' : 'transparent', color: mode === id ? 'var(--text-strong)' : 'var(--text-muted)' }}>{icon}{label}</button>
  );
  return (
    <span role="tablist" aria-label="Mode" style={{ display: 'flex', gap: 2, padding: 2, borderRadius: 6, border: '1px solid var(--border)', WebkitAppRegion: 'no-drag' } as any}>
      {btn('ide', 'IDE', <Code2 size={13} />, 'IDE: files, editor, agent runs, live preview (⌃⌘1)')}
      {btn('reports', 'Reports', <BarChart3 size={13} />, 'Reports: dashboards, experiments, benchmarks, agent evaluations (⌃⌘2)')}
    </span>
  );
}

function TitleBar() {
  const mode = useStudio(s => s.mode);
  const workspaceId = useStudio(s => s.workspaceId);
  const sidebar = useStudio(s => s.sidebarVisible);
  const panel = useStudio(s => s.panelVisible);
  const right = useStudio(s => s.rightVisible);
  const toggleStyle = (on: boolean) => ({ color: on ? 'var(--text-strong)' : 'var(--text-faint)' });
  return (
    <div className="st-titlebar">
      <span style={{ fontWeight: 700, letterSpacing: '.04em', color: 'var(--text-strong)', paddingLeft: 4, width: 120 }}>VEXA <span className="st-faint" style={{ fontWeight: 500 }}>Studio</span></span>
      <ModeSwitch />
      <span style={{ flex: 1 }} />
      <button className="st-icon-btn" title="Go Back" onClick={() => cycleTabs(-1)}><ArrowLeft size={16} /></button>
      <button className="st-icon-btn" title="Go Forward" onClick={() => cycleTabs(1)}><ArrowRight size={16} /></button>
      <button className="st-command" onClick={() => setState({ paletteOpen: 'files' })} data-testid="command-center">
        <Search size={14} /><span style={{ flex: 1, textAlign: 'left' }}>{workspaceId || 'Search'}</span><span className="st-faint st-mono">⌘P</span>
      </button>
      <span style={{ flex: 1 }} />
      {mode === 'ide' && <span style={{ display: 'flex', gap: 2, WebkitAppRegion: 'no-drag' } as any}>
        <button className="st-icon-btn" title="Toggle Primary Side Bar (⌘B)" style={toggleStyle(sidebar)} onClick={() => setState(s => ({ sidebarVisible: !s.sidebarVisible }))}><PanelLeft size={16} /></button>
        <button className="st-icon-btn" title="Toggle Panel (⌘J)" style={toggleStyle(panel)} onClick={() => setState(s => ({ panelVisible: !s.panelVisible }))}><PanelBottom size={16} /></button>
        <button className="st-icon-btn" title="Toggle Agent Runs (⌥⌘B)" style={toggleStyle(right)} onClick={() => setState(s => ({ rightVisible: !s.rightVisible }))} data-testid="toggle-runs"><PanelRight size={16} /></button>
      </span>}
    </div>
  );
}

function cycleTabs(dir: number) {
  const s = getState();
  const i = s.tabs.findIndex(t => t.id === s.activeTabId);
  if (s.tabs.length < 2 || i < 0) return;
  setState({ activeTabId: s.tabs[(i + dir + s.tabs.length) % s.tabs.length].id });
}

function StatusBar() {
  const connected = useStudio(s => s.connected);
  const live = useLiveRuns();
  const cursor = useStudio(s => (s.tabs.find(t => t.id === s.activeTabId)?.kind === 'file' ? s.cursor : null));
  const theme = useStudio(s => s.theme);
  const unread = useStudio(s => s.unreadNotifications);
  const [bellOpen, setBellOpen] = useState(false);
  const run = usePanelRun();
  const problems = problemsOf(run);
  const [sys, setSys] = useState<SystemStatus | null>(null);
  useEffect(() => {
    const load = () => VexaApi.systemStatus().then(s => { setSys(s); setState({ connected: true }); }).catch(() => { setSys(null); setState({ connected: false }); });
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, []);
  const errors = problems.filter(p => p.severity === 'error').length;
  const warnings = problems.length - errors;
  const showMonitoring = () => setState({ activity: 'monitoring', sidebarVisible: true });
  const color = (ok: boolean | null) => ok === null ? 'var(--text-faint)' : ok ? 'var(--ok)' : 'var(--err)';
  return (
    <div className="st-statusbar" data-testid="status-bar">
      <button className="st-sitem" onClick={showMonitoring} title={connected === false ? 'Backend unreachable' : 'Backend connected'} data-testid="status-backend">
        <Plug size={13} style={{ color: color(connected) }} />{connected === false ? 'Backend offline' : connected ? 'VEXA backend' : 'Connecting…'}
      </button>
      <button className="st-sitem" onClick={() => setState({ panelVisible: true, panelTab: 'problems' })} title="Problems in the selected run">
        <CircleX size={13} />{errors}<TriangleAlert size={13} style={{ marginLeft: 4 }} />{warnings}
      </button>
      {live.length > 0 && live.map(r => (
        <button key={r.run_id} className="st-sitem" style={{ color: 'var(--run)' }} onClick={() => setState({ panelVisible: true, panelTab: 'output', focusRunId: r.run_id })}>
          <Radio size={13} className="pulse" />{r.architecture} · {r.result?.current_agent || 'starting'}
        </button>
      ))}
      <span style={{ flex: 1 }} />
      {cursor && <span className="st-sitem" style={{ cursor: 'default' }}>Ln {cursor.line}, Col {cursor.col}</span>}
      {sys && (
        <>
          <button className="st-sitem" onClick={showMonitoring} title={`Database: ${sys.database.status}`}><Database size={13} style={{ color: color(sys.database.status === 'ok') }} />{sys.database.runs ?? '?'} runs</button>
          <button className="st-sitem" onClick={showMonitoring} title={`LLM: ${sys.llm.status} (reachability not probed)`}>
            <Cpu size={13} style={{ color: sys.llm.status === 'configured' ? 'var(--ok)' : 'var(--text-faint)' }} />{sys.llm.status === 'configured' ? sys.llm.model : 'no LLM key'}
          </button>
          <button className="st-sitem" onClick={showMonitoring} title={`A2A verifier: ${sys.a2a.status}${sys.a2a.note ? ` — ${sys.a2a.note}` : ''}`}>
            <Network size={13} style={{ color: sys.a2a.status === 'running' ? 'var(--ok)' : 'var(--text-faint)' }} />A2A {sys.a2a.status.replace('_', ' ')}
          </button>
          <button className="st-sitem" onClick={showMonitoring} title={`MCP: ${sys.mcp.lifecycle}`}>MCP {sys.mcp.status === 'available' ? 'on demand' : 'unavailable'}</button>
        </>
      )}
      <button className="st-sitem" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Toggle theme">{theme === 'dark' ? <Moon size={13} /> : <Sun size={13} />}</button>
      <button className="st-sitem" title="Notifications" onClick={() => setBellOpen(o => !o)} data-testid="status-bell">
        <Bell size={13} />{unread > 0 && <span data-testid="bell-unread">{unread}</span>}
      </button>
      {bellOpen && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 55 }} onClick={() => setBellOpen(false)} />
          <div style={{ position: 'fixed', right: 8, bottom: 28, zIndex: 56, width: 380, maxWidth: 'calc(100vw - 16px)', maxHeight: '50vh', overflow: 'auto',
            background: 'var(--bg-panel)', border: '1px solid var(--border-strong)', borderRadius: 6, padding: '8px 12px', boxShadow: '0 6px 18px rgba(0,0,0,.35)' }}>
            <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>Notifications</div>
            <NotificationList compact />
          </div>
        </>
      )}
    </div>
  );
}

function Toasts() {
  const toasts = useStudio(s => s.toasts);
  return (
    <div style={{ position: 'fixed', right: 12, bottom: 32, zIndex: 60, display: 'flex', flexDirection: 'column', gap: 6, width: 380, maxWidth: 'calc(100vw - 24px)' }} aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} role="status" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-strong)', borderRadius: 6, padding: '10px 12px',
          boxShadow: '0 6px 18px rgba(0,0,0,.35)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          {t.kind === 'error' ? <CircleX size={15} style={{ color: 'var(--err)', flex: 'none' }} /> : t.kind === 'warn' ? <TriangleAlert size={15} style={{ color: 'var(--warn)', flex: 'none' }} /> : <Info size={15} style={{ color: 'var(--info)', flex: 'none' }} />}
          <span style={{ flex: 1, lineHeight: 1.45 }}>{t.text}</span>
        </div>
      ))}
    </div>
  );
}

/** Drag handle. `axis` x resizes a width, y a height; `invert` for handles on the left/top edge of the resized pane. */
function Splitter({ axis, value, set, min, max, invert }: { axis: 'x' | 'y'; value: number; set: (v: number) => void; min: number; max: number; invert?: boolean }) {
  const [drag, setDrag] = useState(false);
  const start = useRef<{ p: number; v: number } | null>(null);
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      if (!start.current) return;
      const d = (axis === 'x' ? e.clientX : e.clientY) - start.current.p;
      set(Math.round(Math.min(max, Math.max(min, start.current.v + (invert ? -d : d)))));
    };
    const up = () => setDrag(false);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); document.body.style.cursor = ''; document.body.style.userSelect = ''; };
  }, [drag, axis, set, min, max, invert]);
  return <div className={`${axis === 'x' ? 'st-splitter-v' : 'st-splitter-h'}${drag ? ' drag' : ''}`} role="separator"
    onPointerDown={e => { start.current = { p: axis === 'x' ? e.clientX : e.clientY, v: value }; setDrag(true); }}
    onDoubleClick={() => set(axis === 'x' ? (invert ? 360 : 280) : 240)} />;
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      const k = e.key.toLowerCase();
      const s = getState();
      if (mod && e.shiftKey && k === 'p') { e.preventDefault(); setState({ paletteOpen: 'commands' }); return; }
      if (mod && !e.shiftKey && k === 'p') { e.preventDefault(); setState({ paletteOpen: 'files' }); return; }
      if (mod && e.altKey && k === 'b') { e.preventDefault(); setState({ rightVisible: !s.rightVisible }); return; }
      if (mod && !e.shiftKey && k === 'b') { e.preventDefault(); setState({ sidebarVisible: !s.sidebarVisible }); return; }
      if (mod && k === 'j') { e.preventDefault(); setState({ panelVisible: !s.panelVisible }); return; }
      if (e.ctrlKey && e.key === '`') { e.preventDefault(); setState({ panelVisible: true, panelTab: 'terminal' }); return; }
      if (e.ctrlKey && e.metaKey && (e.key === '1' || e.key === '2')) { e.preventDefault(); setMode(e.key === '1' ? 'ide' : 'reports'); return; }
      if (mod && !e.shiftKey && e.key === ',') { e.preventDefault(); setState({ activity: 'settings', sidebarVisible: true }); return; }
      if (mod && e.shiftKey && k === 'e') { e.preventDefault(); setState({ activity: 'explorer', sidebarVisible: true }); return; }
      if (mod && e.shiftKey && k === 'f') { e.preventDefault(); setState({ activity: 'search', sidebarVisible: true }); return; }
      if (mod && e.altKey && k === 's') { e.preventDefault(); saveAll(); return; }
      if (e.altKey && k === 'w') { e.preventDefault(); if (s.activeTabId) closeTab(s.activeTabId); return; }
      if (mod && k === 's') {
        // Monaco handles ⌘S itself when focused; this covers focus elsewhere (e.g. explorer)
        e.preventDefault();
        const t = s.tabs.find(x => x.id === s.activeTabId);
        if (t?.kind === 'file') saveFile(t.path);
      }
    };
    window.addEventListener('keydown', onKey);
    const beforeUnload = (e: BeforeUnloadEvent) => { if (Object.values(getState().buffers).some(b => b.loaded && b.content !== b.saved)) { e.preventDefault(); } };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('beforeunload', beforeUnload); };
  }, []);
}

const isReportTab = (t: Tab) => REPORT_KINDS.has(t.kind);

export function Studio() {
  // one primitive per selector: useSyncExternalStore needs referentially stable snapshots
  const s = {
    sv: useStudio(x => x.sidebarVisible), sw: useStudio(x => x.sidebarWidth),
    pv: useStudio(x => x.panelVisible), ph: useStudio(x => x.panelHeight),
    rv: useStudio(x => x.rightVisible), rw: useStudio(x => x.rightWidth),
  };
  const mode = useStudio(x => x.mode);
  const [creatingWs, setCreatingWs] = useState(false);
  useShortcuts();
  useEffect(() => {
    document.body.classList.add('studio');
    document.documentElement.dataset.theme = getState().theme;
    loadWorkspaces();
    loadRecentRuns();
    const h = () => setCreatingWs(true);
    document.addEventListener('vexa:new-workspace', h);
    return () => document.removeEventListener('vexa:new-workspace', h);
  }, []);
  return (
    <div className="st-root studio">
      <TitleBar />
      {mode === 'reports' ? (
      <div className="st-body" data-testid="reports-mode">
        <div className="st-card st-left"><div className="st-sidebar" style={{ width: s.sw }}><ReportsNav /></div></div>
        <Splitter axis="x" value={s.sw} set={v => setState({ sidebarWidth: v })} min={220} max={640} />
        <div className="st-center"><div className="st-card" style={{ flex: 1 }}><EditorArea filter={isReportTab} /></div></div>
      </div>
      ) : (
      <div className="st-body">
        <div className="st-card st-left" style={{ flexDirection: 'row' }}>
          <ActivityBar />
          {s.sv && <div className="st-sidebar" style={{ width: s.sw, borderLeft: '1px solid var(--border)' }}><Sidebar /></div>}
        </div>
        {s.sv && <Splitter axis="x" value={s.sw} set={v => setState({ sidebarWidth: v })} min={180} max={640} />}
        <div className="st-center">
          <div className="st-card" style={{ flex: 1 }}><EditorArea /></div>
          {s.pv && <Splitter axis="y" value={s.ph} set={v => setState({ panelHeight: v })} min={100} max={Math.round(window.innerHeight * 0.8)} invert />}
          {s.pv && <div className="st-card" style={{ height: s.ph, flex: 'none' }}><BottomPanel /></div>}
        </div>
        {s.rv && <Splitter axis="x" value={s.rw} set={v => setState({ rightWidth: v })} min={260} max={720} invert />}
        {s.rv && <div className="st-card" style={{ width: s.rw, flex: 'none' }}><RunPanel /></div>}
      </div>
      )}
      <StatusBar />
      <CommandPalette />
      <Toasts />
      {creatingWs && <NewWorkspaceDialog onClose={() => setCreatingWs(false)} />}
    </div>
  );
}
