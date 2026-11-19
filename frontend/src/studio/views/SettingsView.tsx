import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { VexaApi } from '../../api/client';
import type { SystemStatus } from '../../api/client';
import { useStudio, setState, setTheme, openRun } from '../store';
import type { EditorPrefs } from '../store';
import { timeAgo } from '../util';
import { useLlmCredentials, setLlmCredentials, clearLlmCredentials, MODEL_PRESETS, modelForKey } from '../llmCredentials';

function Head({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="st-head"><span className="title">{title}</span>{children}</div>;
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '8px 14px 10px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{children}</div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
      <span style={{ flex: 1 }}>
        <div>{label}</div>
        {hint && <div className="st-faint" style={{ fontSize: 11.5 }}>{hint}</div>}
      </span>
      {children}
    </label>
  );
}

const KV = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div style={{ display: 'flex', gap: 8, fontSize: 12 }}><span className="st-faint" style={{ width: 92, flex: 'none' }}>{k}</span><span className="st-mono" style={{ wordBreak: 'break-all' }}>{v ?? '—'}</span></div>
);

/** Studio preferences (stored in this browser) plus a read-only view of the backend's configuration. */
export function SettingsView() {
  const theme = useStudio(s => s.theme);
  const prefs = useStudio(s => s.editorPrefs);
  const [sys, setSys] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => VexaApi.systemStatus().then(s => { setSys(s); setError(null); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);
  const setPref = (p: Partial<EditorPrefs>) => setState(s => ({ editorPrefs: { ...s.editorPrefs, ...p } }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Head title="Settings" />
      <div className="st-scroll" data-testid="settings">
        <Group title="Appearance">
          <Field label="Color theme">
            <select className="st-select" value={theme} onChange={e => setTheme(e.target.value as 'dark' | 'light')} data-testid="setting-theme">
              <option value="dark">Dark</option><option value="light">Light</option>
            </select>
          </Field>
        </Group>
        <Group title="Editor">
          <Field label="Font size" hint="10–24 px">
            <input className="st-input" type="number" min={10} max={24} style={{ width: 64 }} value={prefs.fontSize} data-testid="setting-font-size"
              onChange={e => { const v = Number(e.target.value); if (v >= 10 && v <= 24) setPref({ fontSize: v }); }} />
          </Field>
          <Field label="Minimap"><input type="checkbox" checked={prefs.minimap} onChange={e => setPref({ minimap: e.target.checked })} data-testid="setting-minimap" /></Field>
          <Field label="Word wrap"><input type="checkbox" checked={prefs.wordWrap} onChange={e => setPref({ wordWrap: e.target.checked })} data-testid="setting-word-wrap" /></Field>
        </Group>
        <ModelKeySettings serverKey={sys?.llm.status === 'configured'} serverModel={sys?.llm.model} />
        <Group title="Layout">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button className="st-btn secondary" onClick={() => setState({ sidebarWidth: 280, panelHeight: 240, rightWidth: 360, sidebarVisible: true, panelVisible: true, rightVisible: true })}>Reset layout</button>
            <button className="st-btn secondary" onClick={() => setState({ paletteOpen: 'commands' })}>Command palette (⇧⌘P)</button>
            <button className="st-btn secondary" onClick={() => { window.location.href = '/?classic'; }}>Classic dashboard</button>
          </div>
          <div className="st-faint" style={{ fontSize: 11.5 }}>Layout, theme, editor settings and open files are saved in this browser only.</div>
        </Group>
        <Group title="Backend configuration (read-only)">
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span className="st-faint" style={{ flex: 1, fontSize: 11.5 }}>Set in the backend's environment (.env). The Studio never receives API keys.</span>
            <button className="st-icon-btn" title="Refresh" onClick={load}><RefreshCw size={14} /></button>
          </div>
          {error && <div className="st-error">Backend unreachable: {error}</div>}
          {sys && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }} data-testid="settings-backend">
              <KV k="Version" v={`${sys.backend.version} · ${sys.backend.environment}`} />
              <KV k="LLM" v={sys.llm.status === 'configured' ? `${sys.llm.model} (${sys.llm.provider})` : 'not configured — runs use mock mode'} />
              <KV k="Key source" v={sys.llm.key_source ?? 'none'} />
              <KV k="Database" v={`${sys.database.dialect ?? ''} ${sys.database.status}`} />
              <KV k="Sandbox" v={sys.sandbox.backend} />
              <KV k="A2A" v={sys.a2a.url ?? sys.a2a.status} />
              <KV k="MCP" v={sys.mcp.servers.map(s => `${s.name}${s.configured ? '' : ' (off)'}`).join(', ') || 'none'} />
            </div>
          )}
        </Group>
        <NotificationList />
      </div>
    </div>
  );
}

/** Session history of notifications (failed runs, guardrail blocks, save errors). Also opened from the status bar bell. */
export function NotificationList({ compact }: { compact?: boolean }) {
  const items = useStudio(s => s.notifications);
  useEffect(() => { setState({ unreadNotifications: 0 }); }, [items.length]);
  const color = (k: string) => (k === 'error' ? 'var(--err)' : k === 'warn' ? 'var(--warn)' : 'var(--info)');
  const body = (
    <div data-testid="notifications">
      {items.length === 0 && <div className="st-faint" style={{ fontSize: 12 }}>No notifications in this session.</div>}
      {items.map(n => (
        <div key={n.id} className={n.runId ? 'st-row' : undefined} style={{ height: 'auto', padding: '4px 0', display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12 }}
          onClick={n.runId ? () => openRun(n.runId!) : undefined}>
          <span style={{ width: 7, height: 7, borderRadius: 4, background: color(n.kind), marginTop: 5, flex: 'none' }} />
          <span style={{ flex: 1, whiteSpace: 'normal', lineHeight: 1.4 }}>{n.text}</span>
          <span className="st-faint" style={{ flex: 'none', fontSize: 11 }}>{timeAgo(n.at)}</span>
        </div>
      ))}
      {items.length > 0 && <button className="st-btn secondary" style={{ marginTop: 6 }} onClick={() => setState({ notifications: [], unreadNotifications: 0 })}>Clear</button>}
    </div>
  );
  return compact ? body : <Group title={`Notifications (${items.length})`}>{body}</Group>;
}


/** Model + API key for real runs, kept in this browser and sent with each run only. */
export function ModelKeySettings({ serverKey, serverModel, compact = false }: { serverKey?: boolean; serverModel?: string; compact?: boolean }) {
  const cred = useLlmCredentials();
  const [show, setShow] = useState(false);
  const [test, setTest] = useState<string | null>(null);
  const model = modelForKey(cred.apiKey, cred.model);
  const runTest = async () => {
    setTest('Testing…');
    try {
      const r = await VexaApi.testModel(model || undefined, cred.apiKey || undefined);
      setTest(r.ok ? `✓ ${r.model} answered in ${Math.round(r.latency_ms ?? 0)} ms` : `✗ ${r.model}: ${r.error}`);
    } catch (e: any) { setTest(`✗ ${e.message}`); }
  };
  const body = (
    <>
      <div className="st-faint" style={{ fontSize: 11.5 }}>
        {serverKey ? `The server has its own key (${serverModel}). A key here overrides it for your runs.` : 'The server has no LLM key. Add one here to run real agents.'}
        {' '}The key stays in this browser and is sent only with each run; the server never stores it.
      </div>
      <label style={{ fontSize: 12.5 }}>Model
        <input className="st-input" list="vexa-model-presets" data-testid="settings-llm-model" value={cred.model}
          placeholder={model || 'e.g. groq/openai/gpt-oss-20b'} onChange={e => setLlmCredentials({ model: e.target.value })}
          style={{ width: '100%', boxSizing: 'border-box', marginTop: 3 }} />
        <datalist id="vexa-model-presets">{MODEL_PRESETS.map(p => <option key={p.model} value={p.model}>{p.label}</option>)}</datalist>
      </label>
      <label style={{ fontSize: 12.5 }}>API key
        <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
          <input className="st-input" data-testid="settings-llm-key" type={show ? 'text' : 'password'} autoComplete="off" spellCheck={false}
            value={cred.apiKey} placeholder="gsk_… (Groq), AIza… (Gemini), sk-… (OpenAI)" onChange={e => { setLlmCredentials({ apiKey: e.target.value.trim() }); setTest(null); }}
            style={{ flex: 1, minWidth: 0 }} />
          <button type="button" className="st-btn secondary" style={{ height: 26 }} onClick={() => setShow(v => !v)}>{show ? 'Hide' : 'Show'}</button>
        </div>
      </label>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12.5 }}>
        <input type="checkbox" checked={cred.remember} onChange={e => setLlmCredentials({ remember: e.target.checked })} data-testid="settings-llm-remember" />
        Remember on this device (otherwise cleared when the tab closes)
      </label>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="st-btn" style={{ height: 26 }} disabled={!cred.apiKey && !serverKey} onClick={runTest} data-testid="settings-llm-test">Test key</button>
        <button type="button" className="st-btn secondary" style={{ height: 26 }} disabled={!cred.apiKey && !cred.model} onClick={() => { clearLlmCredentials(); setTest(null); }}>Clear</button>
        {test && <span data-testid="settings-llm-test-result" style={{ fontSize: 12, color: test.startsWith('✓') ? 'var(--ok)' : test.startsWith('✗') ? 'var(--err)' : undefined }}>{test}</span>}
      </div>
    </>
  );
  if (compact) return <div style={{ display: 'grid', gap: 6 }}>{body}</div>;
  return <Group title="Model & API key (real runs)">{body}</Group>;
}
