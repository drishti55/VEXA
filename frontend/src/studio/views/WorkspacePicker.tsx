import { useState } from 'react';
import { ChevronDown, FolderGit2, Plus } from 'lucide-react';
import { VexaApi } from '../../api/client';
import { useStudio, switchWorkspace, loadWorkspaces, toast } from '../store';
import { Dialog, useContextMenu } from '../common';

// Mirrors backend/tools/workspace.py validate_workspace_id (the server re-checks).
function workspaceNameError(name: string, existing: string[]): string | null {
  if (!name) return null; // empty = server generates an id
  if (name !== name.trim()) return 'Name cannot start or end with a space.';
  if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}$/.test(name) || name.includes('..'))
    return "Use letters, digits, spaces, '_', '-' or '.'; start with a letter or digit; max 128 characters.";
  if (existing.includes(name)) return `A workspace named '${name}' already exists.`;
  return null;
}

export function NewWorkspaceDialog({ onClose }: { onClose: () => void }) {
  const workspaces = useStudio(s => s.workspaces);
  const [name, setName] = useState('');
  const [outputPath, setOutputPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameErr = workspaceNameError(name, workspaces);
  const create = async () => {
    if (nameErr) return;
    setBusy(true); setError(null);
    try {
      const ws = await VexaApi.createWorkspace(name || undefined, outputPath || undefined);
      await loadWorkspaces();
      switchWorkspace(ws.workspace_id);
      toast(`Workspace '${ws.workspace_id}' created`);
      onClose();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog title="New Workspace" onClose={onClose}>
      <label className="st-muted" style={{ fontSize: 12 }}>Name (optional — a UUID is generated if empty)</label>
      <input className="st-input" autoFocus value={name} onChange={e => setName(e.target.value)} data-testid="new-workspace-name"
        onKeyDown={e => { if (e.key === 'Enter') create(); }} style={{ width: '100%', boxSizing: 'border-box', margin: '4px 0 10px' }} />
      <label className="st-muted" style={{ fontSize: 12 }}>Output path on the backend host (optional, absolute)</label>
      <input className="st-input" value={outputPath} onChange={e => setOutputPath(e.target.value)} placeholder="/path/to/project"
        style={{ width: '100%', boxSizing: 'border-box', margin: '4px 0 10px' }} />
      {(nameErr || error) && <div className="st-error" style={{ marginBottom: 10 }}>{nameErr || error}</div>}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="st-btn secondary" onClick={onClose}>Cancel</button>
        <button className="st-btn" disabled={busy || !!nameErr} onClick={create} data-testid="new-workspace-create">{busy ? 'Creating…' : 'Create'}</button>
      </div>
    </Dialog>
  );
}

export const newWorkspace = () => document.dispatchEvent(new CustomEvent('vexa:new-workspace'));

/** Workspace switcher. The New Workspace dialog is mounted once by Studio and opened with newWorkspace(). */
export function WorkspacePicker({ asButton }: { asButton?: boolean }) {
  const workspaces = useStudio(s => s.workspaces);
  const workspaceId = useStudio(s => s.workspaceId);
  const menu = useContextMenu();
  const openMenu = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    menu.open({ ...e, clientX: r.left, clientY: r.bottom + 2, preventDefault: () => {}, stopPropagation: () => {} } as any, [
      ...workspaces.map(w => ({ label: (w === workspaceId ? '✓ ' : '   ') + w, onClick: () => switchWorkspace(w) })),
      ...(workspaces.length ? ['sep' as const] : []),
      { label: 'New Workspace…', onClick: () => newWorkspace() },
    ]);
  };
  return (
    <>
      {asButton ? (
        <button className="st-btn block" onClick={openMenu} disabled={!workspaces.length} data-testid="open-workspace">Open Workspace</button>
      ) : (
        <div style={{ padding: '0 8px 6px', display: 'flex', gap: 4 }}>
          <button className="st-btn secondary" style={{ flex: 1, justifyContent: 'flex-start', minWidth: 0 }} onClick={openMenu} data-testid="workspace-switcher" title="Switch workspace">
            <FolderGit2 size={14} style={{ flex: 'none' }} />
            <span style={{ flex: 1, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{workspaceId}</span>
            <ChevronDown size={14} />
          </button>
          <button className="st-icon-btn" style={{ height: 28, width: 28 }} title="New Workspace…" onClick={() => newWorkspace()}><Plus size={16} /></button>
        </div>
      )}
      {menu.node}
    </>
  );
}
