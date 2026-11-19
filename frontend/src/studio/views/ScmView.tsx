import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, GitCommit } from 'lucide-react';
import { VexaApi } from '../../api/client';
import { useStudio, openFile } from '../store';
import { FileIcon } from '../util';

const CODE_LABEL: Record<string, [string, string]> = {
  M: ['M', 'var(--warn)'], A: ['A', 'var(--ok)'], D: ['D', 'var(--err)'], R: ['R', 'var(--info)'], '??': ['U', 'var(--ok)'], U: ['C', 'var(--err)'],
};

/** Source Control: read-only git status / log of the workspace (backend git tools never write). */
export function ScmView() {
  const workspaceId = useStudio(s => s.workspaceId);
  const liveRunIds = useStudio(s => s.liveRunIds);
  const [status, setStatus] = useState<{ is_git_repo: boolean; output?: string } | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState({ changes: true, log: true });

  const load = async () => {
    if (!workspaceId) return;
    setError(null);
    try {
      const [s, l] = await Promise.all([VexaApi.gitStatus(workspaceId), VexaApi.gitLog(workspaceId, 30)]);
      setStatus(s);
      setLog((l.output ?? '').split('\n').filter(Boolean));
    } catch (e: any) { setError(e.message); }
  };
  // refresh when a run finishes (agents change files)
  useEffect(() => { load(); }, [workspaceId, liveRunIds.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const changes = (status?.output ?? '').split('\n').filter(Boolean).map(l => {
    const code = l.slice(0, 2).trim() || l.slice(0, 2);
    let path = l.slice(3);
    if (path.includes(' -> ')) path = path.split(' -> ')[1];
    return { code, path: path.replace(/^"|"$/g, '') };
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="st-head">
        <span className="title">Source Control</span>
        <button className="st-icon-btn" title="Refresh" onClick={load} disabled={!workspaceId}><RefreshCw size={14} /></button>
      </div>
      {!workspaceId && <div className="st-empty"><p>Open a workspace to see its git status and history.</p></div>}
      {error && <div className="st-empty st-error">{error}</div>}
      {workspaceId && status && !status.is_git_repo && (
        <div className="st-empty"><p>This workspace is not a git repository, so there is no change history to show.</p>
          <p className="st-muted">VEXA's git tools are read-only by design (agents cannot commit). Run diffs are still available in each run's report.</p></div>
      )}
      {workspaceId && status?.is_git_repo && (
        <div className="st-scroll">
          <div className="st-section" onClick={() => setOpen(o => ({ ...o, changes: !o.changes }))}>
            {open.changes ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span style={{ flex: 1 }}>CHANGES</span>
            <span className="st-badge">{changes.length}</span>
          </div>
          {open.changes && changes.length === 0 && <div className="st-empty st-muted">Working tree clean.</div>}
          {open.changes && changes.map(c => {
            const [label, color] = CODE_LABEL[c.code] ?? CODE_LABEL[c.code[0]] ?? [c.code, 'var(--text-muted)'];
            return (
              <div key={c.path} className="st-row" style={{ paddingLeft: 20 }} title={c.path}
                onClick={() => c.code !== 'D' && !c.path.endsWith('/') && openFile(c.path)}>
                <FileIcon path={c.path} />
                <span className="name">{c.path.split('/').pop()} <span className="st-faint">{c.path.includes('/') ? c.path.slice(0, c.path.lastIndexOf('/')) : ''}</span></span>
                <span className="deco" style={{ color }}>{label}</span>
              </div>
            );
          })}
          <div className="st-section" style={{ marginTop: 6 }} onClick={() => setOpen(o => ({ ...o, log: !o.log }))}>
            {open.log ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span style={{ flex: 1 }}>COMMITS</span>
          </div>
          {open.log && log.length === 0 && <div className="st-empty st-muted">No commits yet.</div>}
          {open.log && log.map(l => (
            <div key={l} className="st-row" style={{ paddingLeft: 20 }} title={l}>
              <GitCommit size={14} style={{ flex: 'none' }} />
              <span className="st-mono st-faint">{l.slice(0, 7)}</span><span className="name">{l.slice(8)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
