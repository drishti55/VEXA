// Shared building blocks for VEXA Studio's inspection pages.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { RefreshCw, FileCode2 } from 'lucide-react';
import { apiGet } from '../api/client';
import { openSource } from './store';

export function useApi<T>(path: string | null): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    apiGet<T>(path).then(d => { if (alive) { setData(d); setError(null); } })
      .catch(e => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [path, tick]);
  const reload = useCallback(() => setTick(t => t + 1), []);
  return { data, error, loading, reload };
}

/** Loading / error / empty states for a page body. */
export function Load<T>({ q, children, empty }: { q: { data: T | null; error: string | null; loading: boolean; reload: () => void };
  children: (d: T) => ReactNode; empty?: (d: T) => boolean }) {
  if (q.error) return <div className="st-empty"><p className="st-error">Could not load: {q.error}</p><button className="st-btn secondary" onClick={q.reload}>Retry</button></div>;
  if (!q.data) return <div className="st-empty st-muted">Loading…</div>;
  if (empty?.(q.data)) return <div className="st-empty st-muted">Nothing recorded yet.</div>;
  return <>{children(q.data)}</>;
}

export function Page({ title, subtitle, actions, children, onReload, testId }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode;
  children: ReactNode; onReload?: () => void; testId?: string }) {
  return (
    <div className="st-scroll" style={{ height: '100%' }} data-testid={testId}>
      <div style={{ maxWidth: 1240, margin: '0 auto', padding: '18px 24px 40px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text-strong)' }}>{title}</h1>
            {subtitle && <div className="st-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{subtitle}</div>}
          </div>
          {actions}
          {onReload && <button className="st-icon-btn" title="Refresh" onClick={onReload}><RefreshCw size={15} /></button>}
        </div>
        {children}
      </div>
    </div>
  );
}

export function Sec({ title, hint, children, right }: { title: string; hint?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <section style={{ marginTop: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8, borderBottom: '1px solid var(--border)', paddingBottom: 6 }}>
        <h2 style={{ margin: 0, fontSize: 12, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-strong)' }}>{title}</h2>
        {hint && <span className="st-faint" style={{ fontSize: 12, flex: 1 }}>{hint}</span>}
        {right}
      </div>
      {children}
    </section>
  );
}

export function Stats({ items }: { items: { label: string; value: ReactNode; hint?: string; tone?: 'ok' | 'err' | 'warn' }[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
      {items.map(i => (
        <div key={i.label} title={i.hint} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px', background: 'var(--bg-inset)' }}>
          <div className="st-muted" style={{ fontSize: 11.5 }}>{i.label}</div>
          <div style={{ fontSize: 20, fontWeight: 600, marginTop: 2, color: i.tone ? `var(--${i.tone})` : 'var(--text-strong)', fontVariantNumeric: 'tabular-nums' }}>{i.value}</div>
          {i.hint && <div className="st-faint" style={{ fontSize: 11, marginTop: 2, lineHeight: 1.35 }}>{i.hint}</div>}
        </div>
      ))}
    </div>
  );
}

export const pct = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`);
export const num = (v: number | null | undefined, digits = 0) => (v == null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: digits }));

export interface Rate { k: number; n: number; rate: number | null; ci95: [number | null, number | null] }

/** Rate as a single-hue bar with a 95% CI whisker; the number is always printed as text. */
export function RateBar({ r, width = 140, invert }: { r: Rate | null | undefined; width?: number; invert?: boolean }) {
  if (!r || !r.n) return <span className="st-faint">no data</span>;
  const [lo, hi] = r.ci95;
  const tip = `${r.k}/${r.n} = ${pct(r.rate, 1)} · 95% CI ${pct(lo, 0)}–${pct(hi, 0)}${invert ? ' (lower is better)' : ''}`;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }} title={tip}>
      <svg width={width} height={12} role="img" aria-label={tip} style={{ flex: 'none' }}>
        <rect x={0} y={4} width={width} height={4} rx={2} fill="var(--bg-active)" />
        <rect x={0} y={3} width={Math.max(2, (r.rate ?? 0) * width)} height={6} rx={3} fill="var(--accent)" />
        {lo != null && hi != null && <line x1={lo * width} x2={hi * width} y1={6} y2={6} stroke="var(--text-strong)" strokeWidth={1} opacity={0.7} />}
        {lo != null && <line x1={lo * width} x2={lo * width} y1={2} y2={10} stroke="var(--text-strong)" strokeWidth={1} opacity={0.7} />}
        {hi != null && <line x1={hi * width} x2={hi * width} y1={2} y2={10} stroke="var(--text-strong)" strokeWidth={1} opacity={0.7} />}
        <title>{tip}</title>
      </svg>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{pct(r.rate)} <span className="st-faint">({r.k}/{r.n})</span></span>
    </span>
  );
}

/** Single-series trend (score per day); each point has its own tooltip. */
export function Spark({ points, width = 120, height = 26, asPct = true }: { points: { date: string; score: number; n: number }[]; width?: number; height?: number; asPct?: boolean }) {
  if (points.length < 2) return <span className="st-faint" style={{ fontSize: 11.5 }}>{points.length === 1 ? `1 day (${points[0].date})` : 'no trend'}</span>;
  const max = asPct ? 1 : Math.max(...points.map(p => p.score), 1e-9);
  const xs = (i: number) => 4 + (i * (width - 8)) / (points.length - 1);
  const ys = (v: number) => height - 4 - (v / max) * (height - 8);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${xs(i).toFixed(1)},${ys(p.score).toFixed(1)}`).join(' ');
  return (
    <svg width={width} height={height} role="img" aria-label={`trend over ${points.length} days`}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => (
        <g key={p.date}>
          <circle cx={xs(i)} cy={ys(p.score)} r={8} fill="transparent" />
          <circle cx={xs(i)} cy={ys(p.score)} r={2.5} fill="var(--accent)" stroke="var(--bg-panel)" strokeWidth={1.5} />
          <title>{`${p.date}: ${asPct ? pct(p.score) : num(p.score, 2)} (n=${p.n})`}</title>
        </g>
      ))}
    </svg>
  );
}

export function SourceLink({ src, label }: { src: { path: string; line?: number | null } | null | undefined; label?: string }) {
  if (!src) return <span className="st-faint">source n/a</span>;
  return (
    <button className="st-link st-mono" style={{ fontSize: 12 }} onClick={() => openSource(src.path, src.line ?? undefined)} title={`Open ${src.path}${src.line ? `:${src.line}` : ''}`}>
      <FileCode2 size={12} /> {label ?? `${src.path}${src.line ? `:${src.line}` : ''}`}
    </button>
  );
}

export function Table({ head, rows, testId }: { head: ReactNode[]; rows: ReactNode[][]; testId?: string }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table data-testid={testId} style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead><tr>{head.map((h, i) => <th key={i} style={{ textAlign: 'left', fontWeight: 500, color: 'var(--text-muted)', padding: '4px 10px 4px 0', whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>{r.map((c, j) => <td key={j} style={{ padding: '5px 10px 5px 0', verticalAlign: 'top' }}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export function ModeTabs({ mode, set, note }: { mode: 'real' | 'mock'; set: (m: 'real' | 'mock') => void; note?: boolean }) {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      {(['real', 'mock'] as const).map(m => (
        <button key={m} className={`st-pill ${mode === m ? (m === 'mock' ? 'mock' : 'run') : ''}`} style={{ cursor: 'pointer', height: 22 }} onClick={() => set(m)} data-testid={`mode-${m}`}>
          {m === 'real' ? 'Real models' : 'Mock (scripted)'}
        </button>
      ))}
      {note && mode === 'mock' && <span className="st-faint" style={{ fontSize: 11.5 }}>scripted agents — measures the pipeline, not the agents</span>}
    </span>
  );
}
