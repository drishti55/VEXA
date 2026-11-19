import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import type { OnMount } from '@monaco-editor/react';
import { ShieldCheck, Blocks, ArrowRight, Lock } from 'lucide-react';
import { useApi, Load, Page, Sec, Stats, Table, ModeTabs, SourceLink, num } from '../kit';
import { openRun, openAgent, openExtension, useStudio } from '../store';
import { languageFor, timeAgo } from '../util';
import { defineThemes } from '../editor/FileEditor';

const DECISION_TONE: Record<string, string> = { allowed: 'ok', sanitized: 'run', flagged: 'warn', blocked: 'err', indeterminate: '' };

export function GuardrailsPage({ focus }: { focus?: string }) {
  const q = useApi<any>('/guardrails');
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  const [sel, setSel] = useState<string | null>(focus ?? null);
  useEffect(() => { if (focus) setSel(focus); }, [focus]);
  const [decision, setDecision] = useState('');
  const ev = useApi<any>(`/guardrails/events?mode=${mode}${sel ? `&rule=${sel}` : ''}${decision ? `&decision=${decision}` : ''}&limit=300`);
  return (
    <Page testId="guardrails-page" title="Guardrails G1–G10" onReload={() => { q.reload(); ev.reload(); }}
      subtitle={q.data ? <>Implementation version <span className="st-mono">{q.data.version}</span> (hash of backend/guardrails.py) · <SourceLink src={{ path: q.data.module, line: 1 }} /></> : undefined}
      actions={<ModeTabs mode={mode} set={setMode} note />}>
      <Load q={q}>{g => (
        <>
          <div style={{ fontSize: 12.5, padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-inset)' }}>
            <b>Limits (from the module):</b> {g.limits}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 8, marginTop: 12 }} data-testid="guardrail-cards">
            {g.guardrails.map((x: any) => {
              const s = x.stats[mode];
              return (
                <button key={x.id} className={`rv-agent${sel === x.id ? ' sel' : ''}`} onClick={() => setSel(v => v === x.id ? null : x.id)} data-testid="guardrail-card" data-id={x.id}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <ShieldCheck size={14} /><b style={{ color: 'var(--text-strong)' }}>{x.id}</b><span style={{ flex: 1 }}>{x.name}</span>
                    <span className={`st-pill ${x.enforcement === 'heuristic' ? 'warn' : 'ok'}`}>{x.enforcement}</span>
                  </div>
                  <div className="st-muted" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.4 }}>{x.purpose}</div>
                  <div style={{ fontSize: 12, marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <span className="st-faint">stage {x.stages.join(', ')}</span>
                    {s.total === 0 ? <span className="st-faint">· no {mode} decisions</span> :
                      Object.entries(s.decisions).map(([d, n]) => <span key={d} className={`st-pill ${DECISION_TONE[d] ?? ''}`}>{d} {n as number}</span>)}
                    {s.retries > 0 && <span className="st-pill warn">retries {s.retries}</span>}
                  </div>
                </button>
              );
            })}
          </div>
          {sel && (() => {
            const x = g.guardrails.find((y: any) => y.id === sel);
            const s = x.stats[mode];
            return (
              <Sec title={`${x.id} — ${x.name}`} hint={x.enforcement_note}>
                <div className="rv-kv" style={{ gridTemplateColumns: '140px 1fr' }}>
                  <span>Purpose</span><span>{x.purpose}</span>
                  <span>Enforcement</span><span>{x.enforcement === 'heuristic' ? 'Heuristic detection (a signal, not a security boundary)' : 'Deterministic enforcement'} — {x.enforcement_note}</span>
                  <span>Rules</span><span>{x.rules.map((r: any) => <span key={r.kind} className="st-pill" style={{ marginRight: 4 }}>{r.kind} · {r.stage}</span>)}</span>
                  <span>Implementation</span><span>{x.implementation.map((i: any) => <div key={i.name}><SourceLink src={i.source} label={i.name} /></div>)}</span>
                  <span>Agents ({mode})</span><span>{Object.entries(s.agents).map(([a, n]) => <span key={a} style={{ marginRight: 10 }}>{a !== 'runtime' ? <button className="st-link" onClick={() => openAgent(a)}>{a}</button> : a} {n as number}</span>) || '—'}</span>
                  <span>Not evaluated</span><span>{s.not_evaluated} (decision “indeterminate”: the check could not produce a verdict)</span>
                  <span>Trend</span><span>{s.trend.length ? s.trend.map((t: any) => `${t.date}: ${Object.entries(t).filter(([k]) => k !== 'date').map(([k, v]) => `${k} ${v}`).join(', ')}`).join(' · ') : '—'}</span>
                </div>
              </Sec>
            );
          })()}
        </>
      )}</Load>
      <Sec title={`Decisions${sel ? ` — ${sel}` : ''}`} hint="every recorded decision, newest first"
        right={<select className="st-select" value={decision} onChange={e => setDecision(e.target.value)}>
          <option value="">all decisions</option>{['allowed', 'sanitized', 'flagged', 'blocked', 'indeterminate'].map(d => <option key={d}>{d}</option>)}</select>}>
        <Load q={ev}>{d => (
          <>
            <div className="st-faint" style={{ fontSize: 12, marginBottom: 6 }}>{d.total} decision(s){d.total > d.events.length ? `, showing ${d.events.length}` : ''}</div>
            <Table testId="guardrail-events" head={['when', 'rule', 'decision', 'action', 'agent', 'tool', 'reason', 'enforced by', 'version', 'run']}
              rows={d.events.map((e: any) => [
                <span title={e.at}>{timeAgo(e.at)}</span>, <b>{e.rule}</b>, <span className={`st-pill ${DECISION_TONE[e.decision] ?? ''}`}>{e.decision}</span>, e.action,
                e.agent ?? 'runtime', e.tool ? <span className="st-mono">{e.tool}</span> : '—', <span style={{ fontSize: 12 }}>{e.reason || e.detail}</span>,
                <span className="st-faint" style={{ fontSize: 11.5 }}>{e.enforced_by ?? e.detector ?? '—'}</span>, <span className="st-mono st-faint" style={{ fontSize: 11 }}>{e.version ?? '—'}</span>,
                <button className="st-link st-mono" onClick={() => openRun(e.run_id)}>{e.run_id.slice(0, 8)}</button>,
              ])} />
          </>
        )}</Load>
      </Sec>
    </Page>
  );
}

export function ExtensionPage({ extId }: { extId: string }) {
  const q = useApi<any>(`/extensions/${encodeURIComponent(extId)}`);
  const all = useApi<any>('/extensions');
  const nameOf = (id: string) => all.data?.extensions.find((e: any) => e.id === id)?.name ?? id;
  const [fileOpen, setFileOpen] = useState<string | null>(null);
  return (
    <Load q={q}>{x => (
      <Page testId="extension-page" onReload={q.reload}
        title={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Blocks size={20} />{x.name}</span>}
        subtitle={<>{x.purpose || 'No module docstring.'}<div className="st-faint" style={{ fontSize: 12, marginTop: 4 }}>{x.paths.join(', ')} · version {x.version} (content hash) · {x.status}{x.modules_loaded ? ` (${x.modules_loaded} modules)` : ''}</div></>}>
        <Stats items={[
          { label: 'Files', value: x.files }, { label: 'Lines', value: num(x.lines) }, { label: 'Endpoints', value: x.endpoints.length },
          { label: 'Data models', value: x.data_models.length }, { label: 'Related tests', value: x.tests.reduce((a: number, t: any) => a + t.tests, 0), hint: `${x.tests.length} test file(s)` },
          ...(x.runtime_evidence ? [{ label: 'Runtime evidence', value: x.runtime_evidence.count != null ? num(x.runtime_evidence.count) : Object.keys(x.runtime_evidence.by ?? {}).length,
            hint: x.runtime_evidence.label + (x.runtime_evidence.avg_ms != null ? ` · avg ${num(x.runtime_evidence.avg_ms, 1)} ms` : '') + (x.runtime_evidence.errors != null ? ` · ${x.runtime_evidence.errors} errors` : '') +
              (x.runtime_evidence.by ? ` · ${Object.entries(x.runtime_evidence.by).map(([k, v]) => `${k} ${v}`).join(', ')}` : '') }] : []),
        ]} />
        <Sec title="Integration map" hint="from Python imports between modules">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr auto 1fr', gap: 10, alignItems: 'center' }} data-testid="integration-map">
            <div>{x.used_by.length ? x.used_by.map((d: any) => <div key={d.id}><button className="st-link" onClick={() => openExtension(d.id, nameOf(d.id))}>{nameOf(d.id)}</button> <span className="st-faint">({d.imports})</span></div>) : <span className="st-faint">no backend module imports it</span>}</div>
            <ArrowRight size={16} className="st-faint" />
            <div style={{ border: '1px solid var(--focus)', borderRadius: 6, padding: 10, textAlign: 'center', fontWeight: 600 }}>{x.name}</div>
            <ArrowRight size={16} className="st-faint" />
            <div>{x.depends_on.length ? x.depends_on.map((d: any) => <div key={d.id}><button className="st-link" onClick={() => openExtension(d.id, nameOf(d.id))}>{nameOf(d.id)}</button> <span className="st-faint">({d.imports})</span></div>) : <span className="st-faint">no internal dependencies</span>}</div>
          </div>
          <div className="rv-kv" style={{ gridTemplateColumns: '150px 1fr', marginTop: 10 }}>
            <span>External libraries</span><span>{x.external_dependencies.join(', ') || '—'}</span>
            <span>Related agents</span><span>{x.related_agents.length ? x.related_agents.map((a: string) => <button key={a} className="st-link" style={{ marginRight: 8 }} onClick={() => openAgent(a)}>{a}</button>) : '—'}</span>
            <span>Settings read</span><span className="st-mono" style={{ fontSize: 12 }}>{x.settings.join(', ') || '—'}</span>
            <span>Data models</span><span className="st-mono" style={{ fontSize: 12 }}>{x.data_models.join(', ') || '—'}</span>
          </div>
        </Sec>
        <Sec title="Execution flow" hint="entry points other modules import, and the module's own functions each one calls">
          {x.execution_flow.length === 0 ? <div className="st-muted">No entry point is imported by other backend modules.</div> : (
            <Table head={['entry point', 'used by', 'calls inside the module']} rows={x.execution_flow.map((f: any) => [
              <SourceLink src={f.source} label={f.entry} />, <span className="st-faint" style={{ fontSize: 12 }}>{f.used_by.map((u: string) => u.split('/').pop()).join(', ')}</span>,
              <span className="st-mono" style={{ fontSize: 12 }}>{f.calls.join(' → ') || '—'}</span>,
            ])} />
          )}
        </Sec>
        {x.endpoints.length > 0 && (
          <Sec title={`API endpoints (${x.endpoints.length})`}>
            <Table head={['method', 'path', 'handler']} rows={x.endpoints.map((e: any) => [e.methods.join(', '), <span className="st-mono">{e.path}</span>, <SourceLink src={e.source} label={e.name} />])} />
          </Sec>
        )}
        <Sec title="Source explorer" hint="click a file to open it read-only; click a symbol to jump to it">
          {x.file_list.map((f: any) => (
            <div key={f.path} style={{ borderTop: '1px solid var(--border)', padding: '4px 0' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button className="st-link" style={{ fontSize: 12 }} onClick={() => setFileOpen(o => o === f.path ? null : f.path)}>{fileOpen === f.path ? '▾' : '▸'}</button>
                <SourceLink src={{ path: f.path }} />
                <span className="st-faint" style={{ fontSize: 11.5 }}>{f.lines ? `${f.lines} lines · ` : ''}{f.classes.length} classes · {f.functions.length} functions</span>
              </div>
              {fileOpen === f.path && (
                <div style={{ paddingLeft: 24, fontSize: 12 }}>
                  {f.classes.map((c: any) => <div key={c.name}><SourceLink src={{ path: f.path, line: c.line }} label={`class ${c.name}${c.bases.length ? `(${c.bases.join(', ')})` : ''}`} /> <span className="st-faint">{c.doc}</span></div>)}
                  {f.functions.map((c: any) => <div key={c.name}><SourceLink src={{ path: f.path, line: c.line }} label={`def ${c.name}`} /> <span className="st-faint">{c.doc}</span></div>)}
                </div>
              )}
            </div>
          ))}
        </Sec>
        <Sec title="Evaluation" hint="test files that import this module">
          {x.tests.length === 0 ? <div className="st-muted">No test file imports this module directly.</div> :
            <Table head={['test file', 'tests', 'imports']} rows={x.tests.map((t: any) => [<SourceLink src={{ path: t.path }} />, t.tests, <span className="st-mono" style={{ fontSize: 11.5 }}>{t.imports.join(', ')}</span>])} />}
        </Sec>
      </Page>
    )}</Load>
  );
}

/** Read-only viewer for VEXA's own source (GET /source/file). */
export function SourcePage({ path, line }: { path: string; line?: number }) {
  const q = useApi<any>(`/source/file?path=${encodeURIComponent(path)}`);
  const theme = useStudio(s => s.theme);
  const ed = useRef<Parameters<OnMount>[0] | null>(null);
  const reveal = (l?: number) => { if (ed.current && l) { ed.current.revealLineInCenter(l); ed.current.setSelection({ startLineNumber: l, startColumn: 1, endLineNumber: l, endColumn: 1 }); } };
  useEffect(() => {
    const h = (e: Event) => { const d = (e as CustomEvent).detail; if (d.path === path) reveal(d.line); };
    document.addEventListener('vexa:reveal-source', h);
    return () => document.removeEventListener('vexa:reveal-source', h);
  }, [path]);
  if (q.error) return <div className="st-empty st-error">{q.error}</div>;
  if (!q.data) return <div className="st-empty st-muted">Loading {path}…</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} data-testid="source-page">
      <div style={{ height: 22, flex: 'none', display: 'flex', alignItems: 'center', gap: 6, padding: '0 12px', fontSize: 12, color: 'var(--text-muted)' }}>
        <span>vexa</span>{path.split('/').map((p, i) => <span key={i}>› {p}</span>)}
        <span className="st-pill" style={{ marginLeft: 8 }}><Lock size={11} />VEXA source · read-only</span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <Editor path={`vexa-src://${path}`} value={q.data.content} language={languageFor(path)} theme={theme === 'light' ? 'vexa-light' : 'vexa-dark'}
          beforeMount={defineThemes} onMount={e => { ed.current = e; setTimeout(() => reveal(line), 50); }}
          options={{ readOnly: true, fontSize: 13, minimap: { enabled: true }, scrollBeyondLastLine: false, automaticLayout: true,
            fontFamily: '"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace' }} />
      </div>
    </div>
  );
}

