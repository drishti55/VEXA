import { useMemo, useState } from 'react';
import { CaseSensitive, ChevronDown, ChevronRight } from 'lucide-react';
import { VexaApi } from '../../api/client';
import type { SearchMatch } from '../../api/client';
import { useStudio, openFile } from '../store';
import { FileIcon } from '../util';

/** Workspace text search (POST /workspaces/{id}/search — literal/regex search done by the backend). */
export function SearchView() {
  const workspaceId = useStudio(s => s.workspaceId);
  const [query, setQuery] = useState('');
  const [glob, setGlob] = useState('*');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [result, setResult] = useState<{ matches: SearchMatch[]; truncated: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const m = new Map<string, SearchMatch[]>();
    for (const x of result?.matches ?? []) m.set(x.file, [...(m.get(x.file) ?? []), x]);
    return [...m.entries()];
  }, [result]);

  const run = async () => {
    if (!query.trim() || !workspaceId) return;
    setBusy(true); setError(null);
    try { setResult(await VexaApi.searchCode(workspaceId, query, caseSensitive, glob || '*')); setCollapsed(new Set()); }
    catch (e: any) { setError(e.message); setResult(null); }
    finally { setBusy(false); }
  };

  const jump = (m: SearchMatch) => {
    openFile(m.file, { preview: true });
    // the editor picks this up when the model is ready
    document.dispatchEvent(new CustomEvent('vexa:reveal', { detail: { path: m.file, line: m.line_number, query, caseSensitive } }));
  };

  const highlight = (line: string) => {
    const idx = caseSensitive ? line.indexOf(query) : line.toLowerCase().indexOf(query.toLowerCase());
    const trimmed = line.trimStart();
    const off = line.length - trimmed.length;
    if (idx < 0) return trimmed;
    const a = idx - off;
    return <>{trimmed.slice(0, Math.max(0, a))}<mark style={{ background: 'color-mix(in srgb, var(--warn) 40%, transparent)', color: 'inherit' }}>{trimmed.slice(Math.max(0, a), a + query.length)}</mark>{trimmed.slice(a + query.length)}</>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="st-head"><span className="title">Search</span></div>
      {!workspaceId ? <div className="st-empty st-muted">Open a workspace to search its files.</div> : (
        <>
          <div style={{ padding: '0 8px 8px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ position: 'relative' }}>
              <input className="st-input" placeholder="Search" value={query} autoFocus data-testid="search-input"
                style={{ width: '100%', boxSizing: 'border-box', paddingRight: 30 }}
                onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') run(); }} />
              <button className="st-icon-btn" title="Match Case" onClick={() => setCaseSensitive(v => !v)}
                style={{ position: 'absolute', right: 2, top: 2, height: 22, width: 22, color: caseSensitive ? 'var(--text-strong)' : undefined,
                  background: caseSensitive ? 'var(--bg-active)' : undefined }}><CaseSensitive size={16} /></button>
            </div>
            <input className="st-input" placeholder="files to include (glob, e.g. *.py)" value={glob} onChange={e => setGlob(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') run(); }} />
          </div>
          <div className="st-scroll">
            {busy && <div className="st-empty st-muted">Searching…</div>}
            {error && <div className="st-empty st-error">{error}</div>}
            {result && !busy && (
              <div className="st-muted" style={{ padding: '0 14px 6px', fontSize: 12 }}>
                {result.matches.length} result{result.matches.length === 1 ? '' : 's'} in {grouped.length} file{grouped.length === 1 ? '' : 's'}
                {result.truncated && ' — results truncated by the backend limit'}
              </div>
            )}
            {grouped.map(([file, ms]) => (
              <div key={file}>
                <div className="st-row" style={{ paddingLeft: 6 }} onClick={() => setCollapsed(c => { const n = new Set(c); if (n.has(file)) n.delete(file); else n.add(file); return n; })}>
                  {collapsed.has(file) ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                  <FileIcon path={file} />
                  <span className="name">{file.split('/').pop()} <span className="st-faint">{file.includes('/') ? file.slice(0, file.lastIndexOf('/')) : ''}</span></span>
                  <span className="st-badge" style={{ background: 'var(--bg-active)', color: 'var(--text)' }}>{ms.length}</span>
                </div>
                {!collapsed.has(file) && ms.map(m => (
                  <div key={m.line_number} className="st-row" style={{ paddingLeft: 40 }} onClick={() => jump(m)} title={`${file}:${m.line_number}`}>
                    <span className="name st-mono" style={{ fontSize: 12 }}>{highlight(m.matched_line)}</span>
                    <span className="st-faint" style={{ fontSize: 11 }}>{m.line_number}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
