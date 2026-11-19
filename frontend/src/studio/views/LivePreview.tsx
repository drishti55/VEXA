import { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, ExternalLink, Monitor, Tablet, Smartphone } from 'lucide-react';
import { API_BASE_URL, VexaApi } from '../../api/client';
import type { FileEntry } from '../../api/client';
import { useStudio } from '../store';

const VIEWPORTS = [
  { id: 'full', label: 'Responsive', width: null, icon: <Monitor size={14} /> },
  { id: 'tablet', label: 'Tablet (768 px)', width: 768, icon: <Tablet size={14} /> },
  { id: 'phone', label: 'Phone (390 px)', width: 390, icon: <Smartphone size={14} /> },
] as const;

/** The shallowest index.html in a listing ('' = workspace root), or null when the project has no web page. */
function entryPage(files: FileEntry[]): string | null {
  const pages = files.filter(f => !f.is_dir && (f.path === 'index.html' || f.path.endsWith('/index.html')) && !f.path.includes('node_modules/'))
    .map(f => f.path).sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b));
  return pages[0] ?? null;
}

/**
 * Live web view of a workspace, served by the backend (`/workspaces/{id}/serve/...`). It reloads on its own
 * when the open workspace's files change: a save in the editor, an explorer operation, or an agent's write.
 */
export function LivePreview() {
  const current = useStudio(s => s.workspaceId);
  const workspaces = useStudio(s => s.workspaces);
  const currentFiles = useStudio(s => s.files);
  const nonce = useStudio(s => s.previewNonce);
  const [picked, setPicked] = useState<string | null>(null);   // null = follow the open workspace
  const ws = picked ?? current;
  const [otherFiles, setOtherFiles] = useState<{ ws: string; files: FileEntry[] | null; error?: string } | null>(null);
  const [viewport, setViewport] = useState<(typeof VIEWPORTS)[number]['id']>('full');
  const [auto, setAuto] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [lastReload, setLastReload] = useState<Date | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // the open workspace's listing is already in the store; any other workspace is listed on demand
  useEffect(() => {
    if (!ws || ws === current) return;
    let alive = true;
    VexaApi.listFiles(ws)
      .then(r => alive && setOtherFiles({ ws, files: Array.isArray(r?.data) ? r.data : [] }))
      .catch(e => alive && setOtherFiles({ ws, files: null, error: e.message }));
    return () => { alive = false; };
  }, [ws, current, reloadKey]);

  const files = ws === current ? currentFiles : otherFiles?.ws === ws ? otherFiles.files : null;
  const page = useMemo(() => (files ? entryPage(files) : undefined), [files]);

  // auto-reload (debounced: an agent often writes several files in a row)
  useEffect(() => {
    if (!auto || nonce === 0 || ws !== current) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setReloadKey(k => k + 1); setLastReload(new Date()); }, 400);
    return () => clearTimeout(timer.current);
  }, [nonce, auto, ws, current]);

  const url = ws && page ? `${API_BASE_URL}/workspaces/${encodeURIComponent(ws)}/serve/${page === 'index.html' ? '' : page.split('/').map(encodeURIComponent).join('/')}` : null;
  const width = VIEWPORTS.find(v => v.id === viewport)?.width ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }} data-testid="live-preview">
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', borderBottom: '1px solid var(--border)', flex: 'none' }}>
        <select className="st-select" style={{ flex: 1, minWidth: 0, height: 24 }} value={ws} data-testid="preview-workspace"
          onChange={e => setPicked(e.target.value === current ? null : e.target.value)} title="Workspace to preview">
          {!ws && <option value="">No workspace</option>}
          {workspaces.map(w => <option key={w} value={w}>{w}{w === current ? ' (open)' : ''}</option>)}
        </select>
        <button className="st-icon-btn" title="Reload" onClick={() => { setReloadKey(k => k + 1); setLastReload(new Date()); }} data-testid="preview-reload"><RefreshCw size={14} /></button>
        <button className="st-icon-btn" title="Open in a new browser tab" disabled={!url} onClick={() => url && window.open(url, '_blank', 'noopener')}><ExternalLink size={14} /></button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '3px 8px', borderBottom: '1px solid var(--border)', flex: 'none', fontSize: 11.5 }}>
        {VIEWPORTS.map(v => (
          <button key={v.id} className="st-icon-btn" title={v.label} onClick={() => setViewport(v.id)}
            style={{ color: viewport === v.id ? 'var(--text-strong)' : 'var(--text-faint)', background: viewport === v.id ? 'var(--bg-active)' : undefined }}>{v.icon}</button>
        ))}
        <span className="st-faint st-mono" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginLeft: 6 }} title={url ?? ''}>{page ?? ''}</span>
        <label className="st-faint" style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}
          title={ws === current ? 'Reload when files in this workspace change' : 'Auto-reload follows the open workspace only'}>
          <input type="checkbox" checked={auto} disabled={ws !== current} onChange={e => setAuto(e.target.checked)} data-testid="preview-auto" />auto-reload
        </label>
      </div>
      <div style={{ flex: 1, minHeight: 0, background: 'var(--bg-inset)', display: 'flex', justifyContent: 'center', overflow: 'auto' }}>
        {!ws ? <Msg>Open a workspace to preview it.</Msg>
          : files === null && otherFiles?.error ? <Msg>Could not list {ws}: {otherFiles.error}</Msg>
          : page === undefined ? <Msg>Checking for a web page…</Msg>
          : page === null ? <Msg testId="preview-unavailable">No index.html in {ws} — this project has no web page to preview.</Msg>
          : (
            <iframe key={`${ws}:${reloadKey}`} src={url!} title={`Preview of ${ws}`} data-testid="preview-frame"
              // No allow-same-origin: generated code runs in an opaque origin and cannot call the VEXA API
              // (the server also sends a CSP sandbox header).
              sandbox="allow-scripts allow-forms allow-modals"
              style={{ border: 0, background: '#fff', height: '100%', width: width ? `${width}px` : '100%', maxWidth: '100%', flex: 'none',
                boxShadow: width ? '0 0 0 1px var(--border-strong)' : undefined }} />
          )}
      </div>
      {lastReload && ws === current && <div className="st-faint" style={{ fontSize: 11, padding: '2px 8px', borderTop: '1px solid var(--border)' }}>reloaded {lastReload.toLocaleTimeString()}</div>}
    </div>
  );
}

function Msg({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return <div className="st-empty st-muted" style={{ alignSelf: 'center', textAlign: 'center', padding: 20 }} data-testid={testId}>{children}</div>;
}
