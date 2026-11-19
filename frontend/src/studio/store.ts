// VEXA Studio state: a tiny external store (useSyncExternalStore), no extra dependency.
// The backend is the source of truth: this only caches what the API returned plus UI layout.

import { useMemo, useSyncExternalStore } from 'react';
import { VexaApi } from '../api/client';
import type { AgentRunResponse, FileEntry } from '../api/client';

export type ActivityId =
  | 'explorer' | 'search' | 'scm' | 'run' | 'extensions'
  | 'agents' | 'experiments' | 'evaluation' | 'benchmarks' | 'monitoring' | 'settings';

export type PanelTabId = 'problems' | 'output' | 'debug' | 'terminal' | 'agentlogs' | 'tests' | 'trace';

export type Tab =
  | { id: string; kind: 'welcome'; title: string }
  | { id: string; kind: 'file'; title: string; path: string; preview?: boolean }
  | { id: string; kind: 'run'; title: string; runId: string }
  | { id: string; kind: 'experiments'; title: string }
  | { id: string; kind: 'preview'; title: string }
  | { id: string; kind: 'agent'; title: string; name: string }
  | { id: string; kind: 'source'; title: string; path: string; line?: number }
  | { id: string; kind: 'extension'; title: string; extId: string }
  | { id: string; kind: 'guardrails'; title: string; focus?: string }
  | { id: string; kind: 'case'; title: string; caseId: string }
  | { id: string; kind: 'benchmarks'; title: string }
  | { id: string; kind: 'evaluation'; title: string; agent?: string }
  | { id: string; kind: 'dashboard'; title: string }
  | { id: string; kind: 'compare'; title: string; a: string; b: string };

export interface Buffer {
  content: string;      // current editor text
  saved: string;        // last text known to be on disk
  loaded: boolean;
  error?: string;
  externalChange?: boolean; // changed on disk (e.g. by an agent) while the user had unsaved edits
}

export interface Toast { id: number; kind: 'info' | 'error' | 'warn'; text: string }
export interface Notification extends Toast { at: string; runId?: string }
export interface EditorPrefs { fontSize: number; minimap: boolean; wordWrap: boolean }

export interface TerminalEntry { id: number; command: string; cwd: string; startedAt: string;
  status: 'running' | 'done' | 'error'; exitCode?: number | null; stdout?: string; stderr?: string;
  timedOut?: boolean; durationMs?: number; error?: string }

export type StudioMode = 'ide' | 'reports';
/** Tab kinds that belong to Reports mode (everything else is IDE work: files, previews, welcome). */
export const REPORT_KINDS: ReadonlySet<Tab['kind']> = new Set(['dashboard', 'evaluation', 'benchmarks', 'case', 'experiments',
  'guardrails', 'compare', 'run', 'agent', 'extension', 'source']);

export interface StudioState {
  mode: StudioMode;
  rightTab: 'runs' | 'preview';
  previewNonce: number;               // bumped when workspace files change (save, agent write, explorer op)
  theme: 'dark' | 'light';
  connected: boolean | null;
  workspaces: string[];
  workspaceId: string;
  files: FileEntry[];
  filesLoading: boolean;
  filesError: string | null;
  agentTouched: Record<string, string>; // path -> agent that last wrote it (from the run's file provenance)
  tabs: Tab[];
  activeTabId: string | null;
  buffers: Record<string, Buffer>;
  activity: ActivityId;
  sidebarVisible: boolean;
  sidebarWidth: number;
  panelVisible: boolean;
  panelHeight: number;
  panelTab: PanelTabId;
  rightVisible: boolean;
  rightWidth: number;
  runs: Record<string, AgentRunResponse>;
  focusRunId: string | null;          // run shown in the bottom panel / status bar
  liveRunIds: string[];               // runs with an open SSE subscription
  recentRuns: AgentRunResponse[];
  paletteOpen: false | 'commands' | 'files' | 'goto' | 'search';
  terminal: TerminalEntry[];
  toasts: Toast[];
  notifications: Notification[];      // session history of toasts, newest first
  unreadNotifications: number;
  editorPrefs: EditorPrefs;
  cursor: { line: number; col: number } | null;
}

const PERSIST_KEY = 'vexa-studio:layout:v1';
type Persisted = Pick<StudioState, 'theme' | 'workspaceId' | 'activity' | 'sidebarVisible' | 'sidebarWidth' |
  'panelVisible' | 'panelHeight' | 'panelTab' | 'rightVisible' | 'rightWidth' | 'editorPrefs' | 'mode' | 'rightTab'> & { openFiles?: string[] };

function loadPersisted(): Partial<Persisted> {
  try { return JSON.parse(localStorage.getItem(PERSIST_KEY) || '{}'); } catch { return {}; }
}

const persisted = loadPersisted();

let state: StudioState = {
  mode: persisted.mode ?? 'ide',
  rightTab: persisted.rightTab ?? 'runs',
  previewNonce: 0,
  theme: persisted.theme ?? 'dark',
  connected: null,
  workspaces: [],
  workspaceId: persisted.workspaceId ?? '',
  files: [],
  filesLoading: false,
  filesError: null,
  agentTouched: {},
  tabs: [{ id: 'welcome', kind: 'welcome', title: 'Welcome' }],
  activeTabId: 'welcome',
  buffers: {},
  activity: persisted.activity ?? 'explorer',
  sidebarVisible: persisted.sidebarVisible ?? true,
  sidebarWidth: persisted.sidebarWidth ?? 280,
  panelVisible: persisted.panelVisible ?? true,
  panelHeight: persisted.panelHeight ?? 240,
  panelTab: persisted.panelTab ?? 'output',
  rightVisible: persisted.rightVisible ?? true,
  rightWidth: persisted.rightWidth ?? 360,
  runs: {},
  focusRunId: null,
  liveRunIds: [],
  recentRuns: [],
  paletteOpen: false,
  terminal: [],
  toasts: [],
  notifications: [],
  unreadNotifications: 0,
  editorPrefs: { fontSize: 13, minimap: true, wordWrap: false, ...(persisted.editorPrefs ?? {}) },
  cursor: null,
};

const listeners = new Set<() => void>();

export function getState(): StudioState { return state; }

export function setState(patch: Partial<StudioState> | ((s: StudioState) => Partial<StudioState>)) {
  const p = typeof patch === 'function' ? patch(state) : patch;
  state = { ...state, ...p };
  listeners.forEach(l => l());
  schedulePersist();
}

let persistTimer: ReturnType<typeof setTimeout> | undefined;
function schedulePersist() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    const s = state;
    const data: Persisted = {
      theme: s.theme, workspaceId: s.workspaceId, activity: s.activity, sidebarVisible: s.sidebarVisible,
      sidebarWidth: s.sidebarWidth, panelVisible: s.panelVisible, panelHeight: s.panelHeight, panelTab: s.panelTab,
      rightVisible: s.rightVisible, rightWidth: s.rightWidth, editorPrefs: s.editorPrefs, mode: s.mode, rightTab: s.rightTab,
      openFiles: s.tabs.filter(t => t.kind === 'file').map(t => (t as any).path),
    };
    try { localStorage.setItem(PERSIST_KEY, JSON.stringify(data)); } catch { /* private mode */ }
  }, 300);
}

function subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; }

export function useStudio<T>(selector: (s: StudioState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state));
}

/** Snapshots of the runs that have an open SSE subscription (stable across unrelated store updates). */
export function useLiveRuns(): AgentRunResponse[] {
  const ids = useStudio(s => s.liveRunIds);
  const runs = useStudio(s => s.runs);
  return useMemo(() => ids.map(id => runs[id]).filter(Boolean), [ids, runs]);
}

// ---------------------------------------------------------------- toasts

let toastSeq = 0;
export function toast(text: string, kind: Toast['kind'] = 'info', runId?: string) {
  const id = ++toastSeq;
  const n: Notification = { id, kind, text, at: new Date().toISOString(), runId };
  setState(s => ({ toasts: [...s.toasts, { id, kind, text }], notifications: [n, ...s.notifications].slice(0, 100), unreadNotifications: s.unreadNotifications + 1 }));
  setTimeout(() => setState(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), kind === 'error' ? 8000 : 4000);
}

// ---------------------------------------------------------------- workspace & files

export async function loadWorkspaces() {
  try {
    const { workspaces } = await VexaApi.getWorkspaces();
    const ids = workspaces.map(w => w.workspace_id).sort((a, b) => a.localeCompare(b));
    setState(s => ({ connected: true, workspaces: ids, workspaceId: ids.includes(s.workspaceId) ? s.workspaceId : '' }));
    if (getState().workspaceId) await refreshFiles();
    restoreOpenFiles();
  } catch {
    setState({ connected: false });
  }
}

let restored = false;
function restoreOpenFiles() {
  if (restored) return;
  restored = true;
  const paths = persisted.openFiles ?? [];
  if (!getState().workspaceId) return;
  for (const p of paths) if (getState().files.some(f => f.path === p && !f.is_dir)) openFile(p, { preview: false, focus: false });
}

export async function refreshFiles() {
  const ws = state.workspaceId;
  if (!ws) { setState({ files: [], filesError: null }); return; }
  setState({ filesLoading: true });
  try {
    const res = await VexaApi.listFiles(ws);
    if (ws !== state.workspaceId) return;
    const files = Array.isArray(res.data) ? res.data : [];
    // explorer ops (create/rename/delete) and agent writes change the listing: reload the live preview
    const sig = (fs: FileEntry[]) => fs.map(f => `${f.path}:${(f as any).size_bytes ?? ''}`).join('|');
    const changed = sig(files) !== sig(state.files);
    setState({ files, filesError: null, filesLoading: false });
    if (changed) bumpPreview();
  } catch (e: any) {
    setState({ filesError: e.message, filesLoading: false });
  }
}

export function dirtyPaths(s: StudioState = state): string[] {
  return Object.entries(s.buffers).filter(([, b]) => b.loaded && b.content !== b.saved).map(([p]) => p);
}

export function switchWorkspace(id: string) {
  if (id === state.workspaceId) return;
  const dirty = dirtyPaths();
  if (dirty.length && !window.confirm(`Discard unsaved changes in ${dirty.length} file(s)?\n\n${dirty.join('\n')}`)) return;
  setState(s => {
    const tabs = s.tabs.filter(t => t.kind !== 'file' && t.kind !== 'preview');
    return { workspaceId: id, files: [], buffers: {}, agentTouched: {}, tabs,
      activeTabId: tabs.some(t => t.id === s.activeTabId) ? s.activeTabId : tabs[0]?.id ?? null };
  });
  refreshFiles();
}

// ---------------------------------------------------------------- tabs & buffers

export const fileTabId = (path: string) => `file:${path}`;

export async function loadBuffer(path: string, force = false) {
  const ws = state.workspaceId;
  const existing = state.buffers[path];
  if (existing?.loaded && !force) return;
  try {
    const res = await VexaApi.readFile(ws, path);
    if (ws !== state.workspaceId) return;
    const text: string = res.data?.content ?? '';
    setState(s => {
      const cur = s.buffers[path];
      const dirty = cur?.loaded && cur.content !== cur.saved;
      if (dirty && force) {
        // never overwrite the user's unsaved edits: flag the conflict instead
        return cur.saved === text ? {} : { buffers: { ...s.buffers, [path]: { ...cur, externalChange: true } } };
      }
      return { buffers: { ...s.buffers, [path]: { content: text, saved: text, loaded: true } } };
    });
  } catch (e: any) {
    setState(s => ({ buffers: { ...s.buffers, [path]: { content: '', saved: '', loaded: true, error: e.message } } }));
  }
}

export function openFile(path: string, opts: { preview?: boolean; focus?: boolean } = {}) {
  const preview = opts.preview ?? true;
  const id = fileTabId(path);
  setState(s => {
    let tabs = s.tabs;
    const existing = tabs.find(t => t.id === id);
    if (existing) {
      if (!preview && existing.kind === 'file' && existing.preview) tabs = tabs.map(t => t.id === id ? { ...t, preview: false } as Tab : t);
    } else {
      const title = path.split('/').pop() || path;
      const tab: Tab = { id, kind: 'file', title, path, preview };
      // like VS Code: a single-click "preview" tab is replaced by the next preview, unless it was edited
      const prevIdx = tabs.findIndex(t => t.kind === 'file' && t.preview &&
        !(s.buffers[t.path]?.loaded && s.buffers[t.path].content !== s.buffers[t.path].saved));
      if (preview && prevIdx >= 0) tabs = tabs.map((t, i) => i === prevIdx ? tab : t);
      else {
        const at = tabs.findIndex(t => t.id === s.activeTabId);
        tabs = [...tabs.slice(0, at + 1), tab, ...tabs.slice(at + 1)];
      }
    }
    const focus = opts.focus !== false;
    return { tabs, activeTabId: focus ? id : s.activeTabId ?? id, ...(focus && s.mode === 'reports' ? { mode: 'ide' as const } : {}) };
  });
  loadBuffer(path);
}

export function openTab(tab: Tab) {
  // a non-report tab (file, preview, welcome) opened from Reports mode is IDE work: switch back
  const mode = state.mode === 'reports' && !REPORT_KINDS.has(tab.kind) ? { mode: 'ide' as const } : {};
  setState(s => s.tabs.some(t => t.id === tab.id)
    ? { activeTabId: tab.id, ...mode }
    : { tabs: [...s.tabs, tab], activeTabId: tab.id, ...mode });
}

export function setMode(mode: StudioMode) {
  setState({ mode });
  if (mode === 'reports') {
    const active = state.tabs.find(t => t.id === state.activeTabId);
    if (!active || !REPORT_KINDS.has(active.kind)) {
      const lastReport = [...state.tabs].reverse().find(t => REPORT_KINDS.has(t.kind));
      if (lastReport) setState({ activeTabId: lastReport.id }); else openDashboard();
    }
  }
}

export const bumpPreview = () => setState(s => ({ previewNonce: s.previewNonce + 1 }));

export function closeTab(id: string, force = false) {
  const tab = state.tabs.find(t => t.id === id);
  if (!tab) return;
  if (tab.kind === 'file' && !force) {
    const b = state.buffers[tab.path];
    if (b?.loaded && b.content !== b.saved && !window.confirm(`'${tab.title}' has unsaved changes. Close without saving?`)) return;
  }
  setState(s => {
    const idx = s.tabs.findIndex(t => t.id === id);
    const tabs = s.tabs.filter(t => t.id !== id);
    const buffers = { ...s.buffers };
    if (tab.kind === 'file') delete buffers[tab.path];
    const activeTabId = s.activeTabId === id ? (tabs[Math.min(idx, tabs.length - 1)]?.id ?? null) : s.activeTabId;
    return { tabs, buffers, activeTabId };
  });
}

export function updateBuffer(path: string, content: string) {
  setState(s => {
    const b = s.buffers[path];
    if (!b) return {};
    // editing pins a preview tab
    const tabs = s.tabs.map(t => t.kind === 'file' && t.path === path && t.preview ? { ...t, preview: false } : t);
    return { tabs, buffers: { ...s.buffers, [path]: { ...b, content } } };
  });
}

export async function saveFile(path: string) {
  const b = state.buffers[path];
  if (!b || !b.loaded || b.error) return;
  const ws = state.workspaceId;
  const content = b.content;
  try {
    await VexaApi.writeFile(ws, path, content);
    setState(s => ({ buffers: { ...s.buffers, [path]: { ...s.buffers[path], saved: content, externalChange: false } } }));
    bumpPreview();
    if (!state.files.some(f => f.path === path)) refreshFiles();
  } catch (e: any) {
    toast(`Could not save ${path}: ${e.message}`, 'error');
  }
}

export async function saveAll() {
  for (const p of dirtyPaths()) await saveFile(p);
}

export function renamePathInState(src: string, dst: string) {
  setState(s => {
    const remap = (p: string) => p === src ? dst : p.startsWith(src + '/') ? dst + p.slice(src.length) : p;
    const buffers: Record<string, Buffer> = {};
    for (const [p, b] of Object.entries(s.buffers)) buffers[remap(p)] = b;
    const tabs = s.tabs.map(t => {
      if (t.kind !== 'file') return t;
      const np = remap(t.path);
      return np === t.path ? t : { ...t, path: np, id: fileTabId(np), title: np.split('/').pop() || np };
    });
    const active = s.tabs.find(t => t.id === s.activeTabId);
    const activeTabId = active?.kind === 'file' ? fileTabId(remap(active.path)) : s.activeTabId;
    return { buffers, tabs, activeTabId };
  });
}

export function removePathFromState(path: string) {
  const affected = state.tabs.filter(t => t.kind === 'file' && (t.path === path || t.path.startsWith(path + '/')));
  affected.forEach(t => closeTab(t.id, true));
}

// ---------------------------------------------------------------- runs (live over SSE)

const unsubscribers: Record<string, () => void> = {};

export async function loadRecentRuns() {
  try {
    const r = await VexaApi.listAgentRuns();
    setState({ recentRuns: r.runs });
    // a run started from another tab/process that is still running: follow it live too
    r.runs.filter(x => x.status === 'running').forEach(x => watchRun(x.run_id));
  } catch { /* status bar shows the disconnect */ }
}

function onSnapshot(run: AgentRunResponse) {
  const prev = state.runs[run.run_id];
  setState(s => ({ runs: { ...s.runs, [run.run_id]: run } }));
  // Real file changes as they happen: refresh the tree and reload open, unmodified files the run touched.
  if (run.workspace_id !== state.workspaceId) return;
  const now = new Set(run.result?.files_changed ?? []);
  const before = new Set(prev?.result?.files_changed ?? []);
  const provenance: Record<string, any> = (run.result as any)?.file_provenance ?? (run.result?.trace as any)?.file_provenance ?? {};
  const touched: Record<string, string> = {};
  // file_provenance: path -> list of writes [{agent, tool, span_id, at_ms}], newest last
  now.forEach(p => {
    const writes = provenance[p];
    const last = Array.isArray(writes) ? writes[writes.length - 1] : writes;
    touched[p] = last?.agent ?? 'unknown agent';
  });
  // Explorer "A" markers follow live runs only (opening an old run must not decorate today's files).
  const live = run.status === 'running' || prev?.status === 'running';
  if (live && Object.keys(touched).length) setState(s => ({ agentTouched: { ...s.agentTouched, ...touched } }));
  const changed = [...now].filter(p => !before.has(p));
  const finished = run.status !== 'running' && prev?.status === 'running';
  const writes = (p: any) => Object.values(p ?? {}).reduce((n: number, w: any) => n + (Array.isArray(w) ? w.length : 1), 0);
  const prevProv = (prev?.result as any)?.file_provenance ?? (prev?.result?.trace as any)?.file_provenance;
  if (changed.length || finished || writes(provenance) !== writes(prevProv)) bumpPreview();
  if (changed.length || finished) {
    refreshFiles();
    const reload = finished ? [...now] : changed;
    reload.forEach(p => { if (state.buffers[p]) loadBuffer(p, true); });
  }
}

export function watchRun(runId: string) {
  if (unsubscribers[runId]) return;
  setState(s => ({ liveRunIds: [...s.liveRunIds, runId] }));
  unsubscribers[runId] = VexaApi.streamRun(runId, onSnapshot, () => {
    delete unsubscribers[runId];
    setState(s => ({ liveRunIds: s.liveRunIds.filter(r => r !== runId) }));
    // the last live snapshot can predate the final result (usage, verifier, report): load the stored run
    VexaApi.getAgentRun(runId).then(r => { onSnapshot(r); loadRecentRuns(); notifyFinished(r); }).catch(() => {});
  });
}

function notifyFinished(r: AgentRunResponse) {
  const blocked = (r.result?.guardrail_events ?? []).filter(g => g.decision === 'blocked').length;
  if (r.status === 'failed') toast(`Run ${r.run_id.slice(0, 8)} failed${r.errors[0] ? `: ${r.errors[0].slice(0, 140)}` : ''}`, 'error', r.run_id);
  else toast(`Run ${r.run_id.slice(0, 8)} finished: ${r.status}`, 'info', r.run_id);
  if (blocked) toast(`Guardrails blocked ${blocked} action(s) in run ${r.run_id.slice(0, 8)}`, 'warn', r.run_id);
}

const inflight = new Set<string>();
/** Load the full run (events, spans, state) when only a list summary is known. */
export async function ensureRun(runId: string) {
  if (state.runs[runId] || inflight.has(runId)) return;
  inflight.add(runId);
  try { onSnapshot(await VexaApi.getAgentRun(runId)); } catch { /* shown as missing by the caller */ } finally { inflight.delete(runId); }
}

export async function openRun(runId: string) {
  setState({ focusRunId: runId });
  openTab({ id: `run:${runId}`, kind: 'run', title: `Run ${runId.slice(0, 8)}`, runId });
  if (!state.runs[runId]) {
    try { onSnapshot(await VexaApi.getAgentRun(runId)); }
    catch (e: any) { toast(`Could not open run: ${e.message}`, 'error'); return; }
  }
  if (state.runs[runId]?.status === 'running') watchRun(runId);
}

export function setTheme(theme: 'dark' | 'light') {
  document.documentElement.dataset.theme = theme;
  setState({ theme });
}

// ---------------------------------------------------------------- inspection tabs

export const openAgent = (name: string) => openTab({ id: `agent:${name}`, kind: 'agent', title: name, name });
export const openSource = (path: string, line?: number) => {
  const id = `source:${path}`;
  const existing = state.tabs.find(t => t.id === id);
  if (existing) setState(s => ({ activeTabId: id, tabs: s.tabs.map(t => t.id === id ? { ...t, line } as Tab : t) }));
  else openTab({ id, kind: 'source', title: path.split('/').pop() || path, path, line });
  if (line) setTimeout(() => document.dispatchEvent(new CustomEvent('vexa:reveal-source', { detail: { path, line } })), 0);
};
export const openExtension = (extId: string, name: string) => openTab({ id: `ext:${extId}`, kind: 'extension', title: name, extId });
export const openGuardrails = (focus?: string) => {
  openTab({ id: 'guardrails', kind: 'guardrails', title: 'Guardrails' });
  if (focus) setState(s => ({ tabs: s.tabs.map(t => t.id === 'guardrails' ? { ...t, focus } as Tab : t) }));
};
export const openCase = (caseId: string) => openTab({ id: `case:${caseId}`, kind: 'case', title: caseId, caseId });
export const openBenchmarks = () => openTab({ id: 'benchmarks', kind: 'benchmarks', title: 'Benchmarks' });
export const openEvaluation = (agent?: string) => {
  openTab({ id: 'evaluation', kind: 'evaluation', title: 'Evaluation', agent });
  setState(s => ({ tabs: s.tabs.map(t => t.id === 'evaluation' ? { ...t, agent } as Tab : t) }));
};
export const openDashboard = () => openTab({ id: 'dashboard', kind: 'dashboard', title: 'Dashboard' });
export const openCompare = (a: string, b: string) => openTab({ id: `cmp:${a}:${b}`, kind: 'compare', title: `${a.slice(0, 6)} ↔ ${b.slice(0, 6)}`, a, b });
