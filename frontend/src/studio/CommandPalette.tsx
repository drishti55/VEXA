import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useStudio, setState, getState, openFile, saveAll, setTheme, switchWorkspace, openRun, closeTab, openTab, refreshFiles, openAgent, openCase, openGuardrails, openSource, openDashboard, openBenchmarks, openEvaluation, setMode } from './store';
import { apiGet } from '../api/client';
import { FileIcon, runRequirement } from './util';
import { runInTerminal } from './BottomPanel';
import { newWorkspace } from './views/WorkspacePicker';
import { openExperimentsTab } from './views/OtherViews';
import { focusComposer, newFileInExplorer } from './EditorArea';

interface Cmd { id: string; label: string; detail?: string; keys?: string; run: () => void }

export function commands(): Cmd[] {
  const s = getState();
  const act = (activity: typeof s.activity) => () => setState({ activity, sidebarVisible: true });
  const base: Cmd[] = [
    { id: 'mode.ide', label: 'Mode: IDE (files, editor, agent runs, live preview)', keys: '⌃⌘1', run: () => setMode('ide') },
    { id: 'mode.reports', label: 'Mode: Reports (dashboards, experiments, benchmarks, evaluations)', keys: '⌃⌘2', run: () => setMode('reports') },
    { id: 'view.preview', label: 'View: Show Live Preview', run: () => { setMode('ide'); setState({ rightVisible: true, rightTab: 'preview' }); } },
    { id: 'view.explorer', label: 'View: Show Explorer', keys: '⇧⌘E', run: act('explorer') },
    { id: 'view.search', label: 'View: Show Search', keys: '⇧⌘F', run: act('search') },
    { id: 'view.scm', label: 'View: Show Source Control', run: act('scm') },
    { id: 'view.monitoring', label: 'View: Show Monitoring', run: act('monitoring') },
    { id: 'view.sidebar', label: 'View: Toggle Primary Side Bar', keys: '⌘B', run: () => setState(x => ({ sidebarVisible: !x.sidebarVisible })) },
    { id: 'view.panel', label: 'View: Toggle Panel', keys: '⌘J', run: () => setState(x => ({ panelVisible: !x.panelVisible })) },
    { id: 'view.runs', label: 'View: Toggle Agent Runs Panel', keys: '⌥⌘B', run: () => setState(x => ({ rightVisible: !x.rightVisible })) },
    { id: 'view.terminal', label: 'View: Show Terminal', keys: '⌃`', run: () => setState({ panelVisible: true, panelTab: 'terminal' }) },
    { id: 'view.problems', label: 'View: Show Problems', run: () => setState({ panelVisible: true, panelTab: 'problems' }) },
    { id: 'theme.toggle', label: `Preferences: Switch to ${s.theme === 'dark' ? 'Light' : 'Dark'} Theme`, run: () => setTheme(s.theme === 'dark' ? 'light' : 'dark') },
    { id: 'file.new', label: 'File: New File…', run: newFileInExplorer },
    { id: 'file.saveAll', label: 'File: Save All', keys: '⌥⌘S', run: saveAll },
    { id: 'file.refresh', label: 'File: Refresh Explorer', run: refreshFiles },
    { id: 'editor.close', label: 'View: Close Editor', keys: '⌥W', run: () => { const id = getState().activeTabId; if (id) closeTab(id); } },
    { id: 'ws.new', label: 'Workspace: New Workspace…', run: newWorkspace },
    { id: 'ws.preview', label: 'Workspace: Preview in Browser Pane', run: () => openTab({ id: 'preview', kind: 'preview', title: 'Preview' }) },
    { id: 'run.start', label: 'Agents: Start Agent Run…', run: focusComposer },
    { id: 'run.tests', label: 'Tests: Run Tests in Workspace Sandbox', run: () => runInTerminal('pytest') },
    { id: 'exp.open', label: 'Experiments: Open Experiments', run: openExperimentsTab },
    { id: 'dash', label: 'View: Open Dashboard', run: openDashboard },
    { id: 'bench', label: 'Benchmarks: Overview and Architecture Comparison', run: openBenchmarks },
    { id: 'eval', label: 'Evaluation: Agent Criteria, Models and Failures', run: () => openEvaluation() },
    { id: 'guard', label: 'Guardrails: Open G1–G10 Inspector', run: () => openGuardrails() },
    { id: 'search.global', label: 'Search: Runs, Cases, Agents, Guardrails, Source (#)', run: () => setTimeout(() => setState({ paletteOpen: 'search' }), 0) },
    { id: 'welcome', label: 'Help: Welcome', run: () => openTab({ id: 'welcome', kind: 'welcome', title: 'Welcome' }) },
    { id: 'classic', label: 'Help: Open Classic Dashboard', run: () => { window.location.href = '/?classic'; } },
  ];
  const ws: Cmd[] = s.workspaces.map(w => ({ id: `ws:${w}`, label: `Workspace: Open ${w}`, detail: w === s.workspaceId ? 'current' : undefined, run: () => switchWorkspace(w) }));
  const runs: Cmd[] = s.recentRuns.slice(0, 30).map(r => ({ id: `run:${r.run_id}`, label: `Run: ${runRequirement(r).slice(0, 70)}`, detail: `${r.status} · ${r.architecture} · ${r.workspace_id}`, run: () => openRun(r.run_id) }));
  return [...base, ...ws, ...runs];
}

function fuzzy(text: string, q: string): number {
  if (!q) return 1;
  const t = text.toLowerCase(); const query = q.toLowerCase();
  const idx = t.indexOf(query);
  if (idx >= 0) return 100 - idx;
  let ti = 0, score = 0;
  for (const ch of query) { const f = t.indexOf(ch, ti); if (f < 0) return 0; score += f === ti ? 2 : 1; ti = f + 1; }
  return score;
}

export function CommandPalette() {
  const mode = useStudio(s => s.paletteOpen);
  const files = useStudio(s => s.files);
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (mode) { setQ(mode === 'commands' ? '>' : mode === 'goto' ? ':' : mode === 'search' ? '#' : ''); setSel(0); setTimeout(() => inputRef.current?.focus(), 0); } }, [mode]);
  const [remote, setRemote] = useState<Cmd[] | null>(null);
  useEffect(() => {
    if (!q.startsWith('#') || q.slice(1).trim().length < 2) { setRemote(null); return; }
    const term = q.slice(1).trim();
    const id = setTimeout(() => {
      apiGet<any>(`/search?q=${encodeURIComponent(term)}&limit=60`).then(d => setRemote(d.results.map((h: any) => ({
        id: `${h.type}:${h.id}`, label: `${h.type}: ${h.title}`, detail: h.detail,
        run: () => h.type === 'run' ? openRun(h.id) : h.type === 'case' ? openCase(h.id) : h.type === 'agent' ? openAgent(h.id)
          : h.type === 'guardrail' ? openGuardrails(h.id) : openSource(h.id),
      })))).catch(e => setRemote([{ id: 'err', label: `Search failed: ${e.message}`, run: () => {} }]));
    }, 200);
    return () => clearTimeout(id);
  }, [q]);

  const items = useMemo<Cmd[]>(() => {
    if (q.startsWith('#')) return remote ?? [{ id: 'hint', label: q.length > 2 ? 'Searching…' : 'Type at least 2 characters to search runs, cases, agents, guardrails and source', run: () => {} }];
    if (q.startsWith('>')) {
      const query = q.slice(1).trim();
      return commands().map(c => ({ c, s: fuzzy(c.label, query) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s).map(x => x.c).slice(0, 60);
    }
    if (q.startsWith(':')) {
      const line = parseInt(q.slice(1), 10);
      const active = getState().tabs.find(t => t.id === getState().activeTabId);
      if (active?.kind !== 'file') return [{ id: 'noop', label: 'Open a file to go to a line', run: () => {} }];
      return [{ id: 'goto', label: isNaN(line) ? 'Type a line number' : `Go to line ${line}`, detail: active.path,
        run: () => !isNaN(line) && document.dispatchEvent(new CustomEvent('vexa:reveal', { detail: { path: active.path, line } })) }];
    }
    return files.filter(f => !f.is_dir).map(f => ({ f, s: fuzzy(f.path, q) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 60)
      .map(({ f }) => ({ id: f.path, label: f.path.split('/').pop()!, detail: f.path, run: () => openFile(f.path, { preview: false }) }));
  }, [q, files, remote]);

  if (!mode) return null;
  const close = () => setState({ paletteOpen: false });
  const choose = (c?: Cmd) => { if (!c) return; close(); c.run(); };
  const fileMode = !q.startsWith('>') && !q.startsWith(':') && !q.startsWith('#');
  return (
    <div className="st-overlay" style={{ background: 'transparent' }} onMouseDown={e => { if (e.target === e.currentTarget) close(); }}>
      <div className="st-palette" data-testid="command-palette">
        <div style={{ padding: 6 }}>
          <input ref={inputRef} className="st-input" value={q} placeholder="Search files by name (> commands, : line, # runs/cases/agents/source)"
            onChange={e => { setQ(e.target.value); setSel(0); }}
            onKeyDown={e => {
              if (e.key === 'Escape') close();
              if (e.key === 'ArrowDown') { e.preventDefault(); setSel(i => Math.min(items.length - 1, i + 1)); }
              if (e.key === 'ArrowUp') { e.preventDefault(); setSel(i => Math.max(0, i - 1)); }
              if (e.key === 'Enter') choose(items[sel]);
            }} />
        </div>
        <div className="st-palette-list">
          {items.length === 0 && <div className="st-empty st-muted">{fileMode && !getState().workspaceId ? 'Open a workspace to search its files.' : 'No matching results'}</div>}
          {items.map((c, i) => (
            <div key={c.id} className={`st-palette-item${i === sel ? ' active' : ''}`} onMouseEnter={() => setSel(i)} onClick={() => choose(c)}>
              {fileMode ? <FileIcon path={c.detail ?? c.label} /> : <ChevronRight size={14} className="st-faint" />}
              <span style={{ whiteSpace: 'nowrap' }}>{c.label}</span>
              {c.detail && <span className="st-faint" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{c.detail}</span>}
              {c.keys && <span className="st-faint st-mono" style={{ marginLeft: 'auto' }}>{c.keys}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
