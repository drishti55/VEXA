import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface MenuItem { label: string; onClick?: () => void; shortcut?: string; disabled?: boolean; danger?: boolean }
export type MenuEntry = MenuItem | 'sep';

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuEntry[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y });
  useLayoutEffect(() => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ x: Math.min(x, window.innerWidth - r.width - 8), y: Math.min(y, window.innerHeight - r.height - 8) });
  }, [x, y]);
  useEffect(() => {
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('mousedown', down);
    window.addEventListener('keydown', key);
    window.addEventListener('blur', onClose);
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key); window.removeEventListener('blur', onClose); };
  }, [onClose]);
  return (
    <div ref={ref} className="st-menu" role="menu" style={{ left: pos.x, top: pos.y }}>
      {items.map((it, i) => it === 'sep' ? <hr key={i} /> : (
        <button key={i} role="menuitem" disabled={it.disabled} style={it.danger ? { color: 'var(--err)' } : undefined}
          onClick={() => { onClose(); it.onClick?.(); }}>
          <span>{it.label}</span>{it.shortcut && <span className="st-faint">{it.shortcut}</span>}
        </button>
      ))}
    </div>
  );
}

export function useContextMenu() {
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuEntry[] } | null>(null);
  const open = (e: React.MouseEvent, items: MenuEntry[]) => { e.preventDefault(); e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY, items }); };
  const node = menu ? <ContextMenu {...menu} onClose={() => setMenu(null)} /> : null;
  return { open, node };
}

export function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
  return (
    <div className="st-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="st-dialog" role="dialog" aria-label={title}>
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({ title, message, confirmLabel = 'OK', danger, onConfirm, onClose }:
  { title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog title={title} onClose={onClose}>
      <div style={{ marginBottom: 16, lineHeight: 1.5 }}>{message}</div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="st-btn secondary" onClick={onClose}>Cancel</button>
        <button className={`st-btn${danger ? ' danger' : ''}`} autoFocus data-testid="confirm-ok"
          onClick={() => { onClose(); onConfirm(); }}>{confirmLabel}</button>
      </div>
    </Dialog>
  );
}

/** Inline text input used for create / rename rows in trees. Enter commits, Escape or blur cancels. */
export function InlineInput({ initial, onCommit, onCancel, validate, selectStem }:
  { initial: string; onCommit: (v: string) => void; onCancel: () => void; validate?: (v: string) => string | null; selectStem?: boolean }) {
  const [v, setV] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const dot = initial.lastIndexOf('.');
    el.setSelectionRange(0, selectStem && dot > 0 ? dot : initial.length);
  }, [initial, selectStem]);
  const err = validate?.(v) ?? null;
  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <input ref={ref} className="st-input" value={v} style={{ width: '100%', height: 20, padding: '0 4px', boxSizing: 'border-box',
        borderColor: err ? 'var(--err)' : undefined }}
        onChange={e => setV(e.target.value)}
        onKeyDown={e => {
          e.stopPropagation();
          if (e.key === 'Enter' && v.trim() && !err) onCommit(v.trim());
          if (e.key === 'Escape') onCancel();
        }}
        onBlur={onCancel} />
      {err && <div style={{ position: 'absolute', top: 21, left: 0, right: 0, zIndex: 5, padding: '3px 6px', fontSize: 12,
        background: 'var(--bg-panel)', border: '1px solid var(--err)', color: 'var(--text)' }}>{err}</div>}
    </div>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="st-empty st-muted">{label}</div>;
}
