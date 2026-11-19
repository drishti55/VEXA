import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { FileIcon } from '../util';

export interface CodeChange { path: string; change?: string; lines_added?: number; lines_removed?: number; diff?: string }

/** Unified diffs recorded on a run (RunResult.code_changes), rendered per file. */
export function DiffView({ changes }: { changes: CodeChange[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set(changes.length <= 3 ? changes.map(c => c.path) : []));
  return (
    <div data-testid="diff-view" style={{ display: 'grid', gap: 6, marginTop: 6 }}>
      {changes.map(c => (
        <div key={c.path} style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          <div className="st-row" style={{ padding: '0 8px', height: 28, background: 'var(--bg-inset)' }}
            onClick={() => setOpen(o => { const n = new Set(o); if (n.has(c.path)) n.delete(c.path); else n.add(c.path); return n; })}>
            {open.has(c.path) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <FileIcon path={c.path} /><span className="name st-mono" style={{ fontSize: 12 }}>{c.path}</span>
            {c.change && <span className="st-pill">{c.change}</span>}
            <span style={{ color: 'var(--ok)', fontSize: 12 }}>+{c.lines_added ?? 0}</span>
            <span style={{ color: 'var(--err)', fontSize: 12 }}>−{c.lines_removed ?? 0}</span>
          </div>
          {open.has(c.path) && (
            <pre className="st-mono" style={{ margin: 0, fontSize: 12, lineHeight: 1.5, maxHeight: 420, overflow: 'auto', padding: '4px 0' }}>
              {(c.diff || '(no diff text recorded)').split('\n').map((l, i) => {
                const bg = l.startsWith('+') && !l.startsWith('+++') ? 'color-mix(in srgb, var(--ok) 14%, transparent)'
                  : l.startsWith('-') && !l.startsWith('---') ? 'color-mix(in srgb, var(--err) 14%, transparent)' : undefined;
                const color = l.startsWith('@@') ? 'var(--info)' : l.startsWith('+++') || l.startsWith('---') ? 'var(--text-faint)' : undefined;
                return <div key={i} style={{ background: bg, color, padding: '0 10px', whiteSpace: 'pre' }}>{l || ' '}</div>;
              })}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
