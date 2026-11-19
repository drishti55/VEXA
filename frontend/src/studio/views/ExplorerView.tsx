import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, FilePlus, FolderPlus, RefreshCw, ChevronsDownUp, Folder, FolderOpen, Search, X, Bot } from 'lucide-react';
import type { FileEntry } from '../../api/client';
import { VexaApi } from '../../api/client';
import {
  useStudio, openFile, refreshFiles, toast, renamePathInState, removePathFromState,
  fileTabId, openRun, ensureRun,
} from '../store';
import { FileIcon, timeAgo, StatusDot, runRequirement, runStartedAt } from '../util';
import { ConfirmDialog, InlineInput, useContextMenu } from '../common';
import { WorkspacePicker, newWorkspace } from './WorkspacePicker';

interface Node { name: string; path: string; isDir: boolean; children: Node[] }

function buildTree(files: FileEntry[]): Node[] {
  const root: Node = { name: '', path: '', isDir: true, children: [] };
  const dirs = new Map<string, Node>([['', root]]);
  const ensureDir = (path: string): Node => {
    const hit = dirs.get(path);
    if (hit) return hit;
    const i = path.lastIndexOf('/');
    const parent = ensureDir(i < 0 ? '' : path.slice(0, i));
    const node: Node = { name: path.slice(i + 1), path, isDir: true, children: [] };
    parent.children.push(node);
    dirs.set(path, node);
    return node;
  };
  for (const f of files) {
    if (f.is_dir) { ensureDir(f.path); continue; }
    const i = f.path.lastIndexOf('/');
    ensureDir(i < 0 ? '' : f.path.slice(0, i)).children.push({ name: f.path.slice(i + 1), path: f.path, isDir: false, children: [] });
  }
  const sort = (n: Node) => {
    n.children.sort((a, b) => (a.isDir === b.isDir ? a.name.localeCompare(b.name, undefined, { numeric: true }) : a.isDir ? -1 : 1));
    n.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

// Mirrors the backend's name rules loosely; the server re-checks every path.
function nameError(name: string, siblings: string[]): string | null {
  if (!name.trim()) return null;
  if (/[\\:*?"<>|]/.test(name) || name.includes('..') || name.startsWith('/')) return 'Invalid name.';
  if (name.split('/').some(p => p === '.git')) return '.git cannot be modified from the editor.';
  if (siblings.includes(name.split('/')[0])) return `A file or folder '${name}' already exists at this location.`;
  return null;
}

type Pending = { kind: 'new-file' | 'new-folder'; parent: string } | { kind: 'rename'; path: string } | null;

export function ExplorerView() {
  const workspaceId = useStudio(s => s.workspaceId);
  const files = useStudio(s => s.files);
  const filesError = useStudio(s => s.filesError);
  const filesLoading = useStudio(s => s.filesLoading);
  const buffers = useStudio(s => s.buffers);
  const agentTouched = useStudio(s => s.agentTouched);
  const activeTabId = useStudio(s => s.activeTabId);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ path: string; isDir: boolean } | null>(null);
  const [filter, setFilter] = useState('');
  const [showFilter, setShowFilter] = useState(false);
  const [sections, setSections] = useState({ files: true, timeline: false });
  const menu = useContextMenu();

  const tree = useMemo(() => buildTree(files), [files]);
  const dirty = useMemo(() => new Set(Object.entries(buffers).filter(([, b]) => b.loaded && b.content !== b.saved).map(([p]) => p)), [buffers]);
  const filtered = useMemo(() => {
    if (!filter.trim()) return null;
    const q = filter.toLowerCase();
    return files.filter(f => !f.is_dir && f.path.toLowerCase().includes(q)).slice(0, 300);
  }, [files, filter]);

  if (!workspaceId) return <NoWorkspace />;

  const toggle = (path: string) => setExpanded(e => { const n = new Set(e); if (n.has(path)) n.delete(path); else n.add(path); return n; });
  const parentOf = (path: string, isDir: boolean) => isDir ? path : path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
  const siblingsOf = (parent: string) => {
    const list = parent ? (findNode(tree, parent)?.children ?? []) : tree;
    return list.map(n => n.name);
  };

  const startNew = (kind: 'new-file' | 'new-folder', parent: string) => {
    if (parent) setExpanded(e => new Set(e).add(parent));
    setPending({ kind, parent });
  };

  const commitNew = async (kind: 'new-file' | 'new-folder', parent: string, name: string) => {
    setPending(null);
    const path = parent ? `${parent}/${name}` : name;
    try {
      if (kind === 'new-folder') await VexaApi.mkdir(workspaceId, path);
      else await VexaApi.writeFile(workspaceId, path, '');
      await refreshFiles();
      if (kind === 'new-file') openFile(path, { preview: false });
      setSelected(path);
    } catch (e: any) { toast(e.message, 'error'); }
  };

  const commitRename = async (path: string, name: string) => {
    setPending(null);
    const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
    const dst = parent ? `${parent}/${name}` : name;
    if (dst === path) return;
    try {
      await VexaApi.rename(workspaceId, path, dst);
      renamePathInState(path, dst);
      await refreshFiles();
      setSelected(dst);
    } catch (e: any) { toast(e.message, 'error'); }
  };

  const doDelete = async (path: string, isDir: boolean) => {
    try {
      if (isDir) await VexaApi.deleteDir(workspaceId, path); else await VexaApi.deleteFile(workspaceId, path);
      removePathFromState(path);
      await refreshFiles();
    } catch (e: any) { toast(e.message, 'error'); }
  };

  const itemMenu = (e: React.MouseEvent, path: string, isDir: boolean) => {
    setSelected(path);
    menu.open(e, [
      ...(isDir ? [] : [{ label: 'Open', onClick: () => openFile(path, { preview: false }) }, 'sep' as const]),
      { label: 'New File…', onClick: () => startNew('new-file', parentOf(path, isDir)) },
      { label: 'New Folder…', onClick: () => startNew('new-folder', parentOf(path, isDir)) },
      'sep',
      { label: 'Copy Relative Path', onClick: () => navigator.clipboard?.writeText(path) },
      'sep',
      { label: 'Rename…', shortcut: 'F2', onClick: () => setPending({ kind: 'rename', path }) },
      { label: 'Delete', shortcut: '⌫', danger: true, onClick: () => setConfirmDelete({ path, isDir }) },
    ]);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!selected || pending) return;
    const node = findNode(tree, selected);
    if (e.key === 'F2') { e.preventDefault(); setPending({ kind: 'rename', path: selected }); }
    if (e.key === 'Delete' || (e.key === 'Backspace' && e.metaKey)) { e.preventDefault(); setConfirmDelete({ path: selected, isDir: !!node?.isDir }); }
    if (e.key === 'Enter' && node && !node.isDir) openFile(node.path, { preview: false });
  };

  const newRow = (parent: string, depth: number) => pending && pending.kind !== 'rename' && pending.parent === parent && (
    <div className="st-row" style={{ paddingLeft: 8 + depth * 12 }}>
      <span style={{ width: 16 }} />
      {pending.kind === 'new-folder' ? <Folder size={15} /> : <FileIcon path="new" />}
      <InlineInput initial="" validate={v => nameError(v, siblingsOf(parent))}
        onCommit={v => commitNew(pending.kind as any, parent, v)} onCancel={() => setPending(null)} />
    </div>
  );

  const renderNode = (n: Node, depth: number): React.ReactNode => {
    const open = expanded.has(n.path);
    const isActive = activeTabId === fileTabId(n.path);
    const touchedBy = agentTouched[n.path];
    const childTouched = n.isDir && Object.keys(agentTouched).some(p => p.startsWith(n.path + '/'));
    const childDirty = n.isDir && [...dirty].some(p => p.startsWith(n.path + '/'));
    return (
      <div key={n.path}>
        <div className={`st-row${selected === n.path ? ' focused' : ''}${isActive ? ' selected' : ''}`}
          style={{ paddingLeft: 8 + depth * 12 }} data-testid="explorer-item" data-path={n.path} title={n.path}
          onClick={() => { setSelected(n.path); if (n.isDir) toggle(n.path); else openFile(n.path, { preview: true }); }}
          onDoubleClick={() => { if (!n.isDir) openFile(n.path, { preview: false }); }}
          onContextMenu={e => itemMenu(e, n.path, n.isDir)}>
          {n.isDir ? (open ? <ChevronDown size={16} /> : <ChevronRight size={16} />) : <span style={{ width: 16, flex: 'none' }} />}
          {n.isDir ? (open ? <FolderOpen size={15} style={{ color: '#c09553', flex: 'none' }} /> : <Folder size={15} style={{ color: '#c09553', flex: 'none' }} />) : <FileIcon path={n.path} />}
          {pending?.kind === 'rename' && pending.path === n.path ? (
            <InlineInput initial={n.name} selectStem={!n.isDir}
              validate={v => v === n.name ? null : nameError(v, siblingsOf(parentOf(n.path, false)).filter(x => x !== n.name))}
              onCommit={v => commitRename(n.path, v)} onCancel={() => setPending(null)} />
          ) : (
            <span className="name" style={{ color: touchedBy || childTouched ? 'var(--run)' : undefined }}>{n.name}</span>
          )}
          {dirty.has(n.path) || childDirty ? <span className="dot" title="Unsaved changes" style={{ background: 'var(--text-muted)', width: 7, height: 7 }} /> : null}
          {touchedBy && <span className="deco" title={`Changed by ${touchedBy} in the current run`} style={{ color: 'var(--run)' }}>A</span>}
        </div>
        {n.isDir && open && (
          <>
            {newRow(n.path, depth + 1)}
            {n.children.map(c => renderNode(c, depth + 1))}
          </>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} onKeyDown={onKey} tabIndex={-1}>
      <div className="st-head">
        <span className="title">Explorer</span>
        <button className="st-icon-btn" title="Filter files" onClick={() => setShowFilter(v => !v)}><Search size={15} /></button>
      </div>
      <WorkspacePicker />
      <div className="st-section" onClick={() => setSections(s => ({ ...s, files: !s.files }))}
        onContextMenu={e => menu.open(e, [
          { label: 'New File…', onClick: () => startNew('new-file', '') },
          { label: 'New Folder…', onClick: () => startNew('new-folder', '') },
          'sep', { label: 'Refresh', onClick: refreshFiles },
        ])}>
        {sections.files ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span style={{ flex: 1, textTransform: 'uppercase', overflow: 'hidden', textOverflow: 'ellipsis' }}>{workspaceId}</span>
        <span onClick={e => e.stopPropagation()} style={{ display: 'flex' }}>
          <button className="st-icon-btn" title="New File…" data-testid="explorer-new-file" onClick={() => startNew('new-file', selectedDir(selected, tree))}><FilePlus size={15} /></button>
          <button className="st-icon-btn" title="New Folder…" onClick={() => startNew('new-folder', selectedDir(selected, tree))}><FolderPlus size={15} /></button>
          <button className="st-icon-btn" title="Refresh Explorer" onClick={refreshFiles}><RefreshCw size={14} className={filesLoading ? 'spin' : ''} /></button>
          <button className="st-icon-btn" title="Collapse Folders" onClick={() => setExpanded(new Set())}><ChevronsDownUp size={15} /></button>
        </span>
      </div>
      {showFilter && (
        <div style={{ padding: '4px 8px', display: 'flex', gap: 4 }}>
          <input className="st-input" autoFocus placeholder="Filter files by path" value={filter} style={{ flex: 1 }}
            onChange={e => setFilter(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') { setFilter(''); setShowFilter(false); } }} />
          {filter && <button className="st-icon-btn" onClick={() => setFilter('')}><X size={14} /></button>}
        </div>
      )}
      {sections.files && (
        <div className="st-scroll" data-testid="explorer-tree" onContextMenu={e => menu.open(e, [
          { label: 'New File…', onClick: () => startNew('new-file', '') },
          { label: 'New Folder…', onClick: () => startNew('new-folder', '') },
        ])}>
          {filesError && <div className="st-empty st-error">Could not list files: {filesError}</div>}
          {!filesError && files.length === 0 && !filesLoading && !pending && (
            <div className="st-empty st-muted">This workspace is empty. Create a file, or start an agent run to generate one.</div>
          )}
          {filtered ? filtered.map(f => (
            <div key={f.path} className="st-row" style={{ paddingLeft: 12 }} onClick={() => openFile(f.path)} title={f.path}>
              <FileIcon path={f.path} /><span className="name">{f.path}</span>
            </div>
          )) : (
            <>
              {newRow('', 0)}
              {tree.map(n => renderNode(n, 0))}
            </>
          )}
        </div>
      )}
      {!sections.files && <div style={{ flex: 1 }} />}
      <TimelineSection open={sections.timeline} onToggle={() => setSections(s => ({ ...s, timeline: !s.timeline }))} />
      {menu.node}
      {confirmDelete && (
        <ConfirmDialog title={`Delete ${confirmDelete.isDir ? 'folder' : 'file'}?`} danger confirmLabel="Delete"
          message={<>Are you sure you want to permanently delete <b>{confirmDelete.path}</b>{confirmDelete.isDir ? ' and everything in it' : ''}? This cannot be undone.</>}
          onConfirm={() => doDelete(confirmDelete.path, confirmDelete.isDir)} onClose={() => setConfirmDelete(null)} />
      )}
    </div>
  );
}

function findNode(nodes: Node[], path: string): Node | undefined {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.isDir && path.startsWith(n.path + '/')) return findNode(n.children, path);
  }
  return undefined;
}

function selectedDir(selected: string | null, tree: Node[]): string {
  if (!selected) return '';
  const n = findNode(tree, selected);
  if (n?.isDir) return n.path;
  return selected.includes('/') ? selected.slice(0, selected.lastIndexOf('/')) : '';
}

/** Timeline: runs (from the registry) that changed the file in the active editor. */
function TimelineSection({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const activeTab = useStudio(s => s.tabs.find(t => t.id === s.activeTabId));
  const recentRuns = useStudio(s => s.recentRuns);
  const runs = useStudio(s => s.runs);
  const workspaceId = useStudio(s => s.workspaceId);
  const path = activeTab?.kind === 'file' ? activeTab.path : null;
  const wsRuns = useMemo(() => recentRuns.filter(r => r.workspace_id === workspaceId).slice(0, 25), [recentRuns, workspaceId]);
  useEffect(() => { if (open) wsRuns.forEach(r => ensureRun(r.run_id)); }, [open, wsRuns]);
  const loading = open && wsRuns.some(r => !runs[r.run_id]);
  const entries = path ? wsRuns.map(r => runs[r.run_id]).filter(r => r && (r.result?.files_changed ?? []).includes(path)) : [];
  return (
    <div style={{ borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', maxHeight: open ? '40%' : undefined }}>
      <div className="st-section" onClick={onToggle}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span style={{ flex: 1 }}>TIMELINE</span>
      </div>
      {open && (
        <div className="st-scroll">
          {!path && <div className="st-empty st-muted">Open a file to see which agent runs changed it.</div>}
          {path && loading && <div className="st-empty st-muted">Loading run history…</div>}
          {path && !loading && entries.length === 0 && <div className="st-empty st-muted">No recorded agent run changed {path.split('/').pop()}.</div>}
          {entries.map(r => (
            <div key={r.run_id} className="st-row" style={{ paddingLeft: 16, height: 'auto', padding: '3px 8px 3px 16px' }} onClick={() => openRun(r.run_id)}>
              <Bot size={14} style={{ flex: 'none' }} />
              <span className="name">{runRequirement(r).slice(0, 60)}</span>
              <StatusDot status={r.status} />
              <span className="st-faint" style={{ fontSize: 11 }}>{timeAgo(runStartedAt(r))}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NoWorkspace() {
  const workspaces = useStudio(s => s.workspaces);
  const connected = useStudio(s => s.connected);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="st-head"><span className="title">Explorer</span></div>
      <div className="st-section"><ChevronDown size={16} />NO WORKSPACE OPENED</div>
      <div className="st-empty">
        {connected === false ? (
          <p className="st-error">The VEXA backend is not reachable, so workspaces cannot be listed. Start it with
            <code className="st-mono"> python -m uvicorn backend.main:app</code>.</p>
        ) : (
          <>
            <p>You have not yet opened a workspace.</p>
            <WorkspacePicker asButton />
            <p style={{ marginTop: 14 }}>A workspace is the project folder VEXA's agents read, edit and test. {workspaces.length} workspace(s) exist on this backend.</p>
            <button className="st-btn block" onClick={newWorkspace}>New Workspace…</button>
          </>
        )}
      </div>
    </div>
  );
}
