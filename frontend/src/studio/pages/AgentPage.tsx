import { useState } from 'react';
import { ArrowDown, Bot, ShieldCheck, Wrench, Lock, Unlock, Network } from 'lucide-react';
import { useApi, Load, Page, Sec, Stats, SourceLink, Table, ModeTabs, num, pct } from '../kit';
import { openRun, openEvaluation, openGuardrails } from '../store';
import { fmtMs, timeAgo, StatusDot } from '../util';

export function AgentPage({ name }: { name: string }) {
  const q = useApi<any>(`/agents/${encodeURIComponent(name)}`);
  const [mode, setMode] = useState<'real' | 'mock'>('real');
  return (
    <Load q={q}>{a => {
      const h = a.history?.[mode];
      return (
        <Page testId="agent-page" onReload={q.reload}
          title={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Bot size={20} />{a.name}</span>}
          subtitle={<>{a.role} — {a.goal}</>}
          actions={<button className="st-btn secondary" onClick={() => openEvaluation(name)}>Evaluation criteria</button>}>
          <Sec title="Overview">
            <div className="rv-kv" style={{ gridTemplateColumns: '170px 1fr', fontSize: 13 }}>
              <span>Framework</span><span>{a.framework}</span>
              <span>Architectures</span><span>{a.architectures.join(', ')}</span>
              <span>Model / provider</span><span>{a.configured_model.model} ({a.configured_model.provider}) <span className="st-faint">— {a.configured_model.note}</span>
                {a.configured_model.adk_model && <> · ADK model {a.configured_model.adk_model}</>}</span>
              <span>Models seen in real runs</span><span>{Object.keys(a.history?.real?.models ?? {}).length ? Object.entries(a.history.real.models).map(([m, n]) => `${m} (${n})`).join(', ') : 'none recorded'}</span>
              <span>System prompt</span><span>{a.prompt_reference.key}_ROLE / GOAL / BACKSTORY / TASK · <SourceLink src={a.prompt_reference.source} /> · variants <SourceLink src={a.prompt_reference.variants_source} label="prompt_variants.py" /></span>
              <span>Input</span><span>step <code className="st-mono">{a.inputs.step}({a.inputs.parameters.map((p: any) => `${p.name}: ${p.type}`).join(', ')})</code></span>
              <span>Declared reads (blackboard)</span><span>{a.inputs.blackboard_reads ? a.inputs.blackboard_reads.map((k: string) => <span key={k} className="st-pill" style={{ marginRight: 4 }}>{k} ← {a.inputs.produced_by[k] ?? 'user'}</span>) : 'not a knowledge source (Manager)'}</span>
              <span>Output</span><span>{a.output.llm_schema ? <>LLM schema <b>{a.output.llm_schema}</b> <SourceLink src={a.output.llm_schema_source} label="" /> → </> : null}contract <b>{a.output.contract}</b> <SourceLink src={a.output.contract_source} label="" />{a.output.state_key && <> → state <code className="st-mono">{a.output.state_key}</code></>}</span>
              <span>Permissions</span><span>
                {a.permissions.can_write_files ? <span className="st-pill warn"><Unlock size={11} />writes files</span> : <span className="st-pill"><Lock size={11} />read-only</span>}{' '}
                {a.permissions.can_run_tests && <span className="st-pill">runs tests (sandbox)</span>}{' '}
                {a.permissions.network && <span className="st-pill warn">network: docs search</span>}{' '}
                {a.permissions.a2a.length > 0 && <span className="st-pill mock"><Network size={11} />{a.permissions.a2a.join(', ')}</span>}{' '}
                <SourceLink src={a.permissions.policy_source} label="TOOL_POLICY" />
              </span>
            </div>
          </Sec>

          <Sec title="Internal architecture" hint="the path one invocation takes through the runtime — every stage opens its implementation">
            <div data-testid="anatomy" style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', maxWidth: 820 }}>
              {a.anatomy.map((s: any, i: number) => (
                <div key={s.stage}>
                  {i > 0 && <div style={{ display: 'flex', justifyContent: 'center', color: 'var(--text-faint)' }}><ArrowDown size={14} /></div>}
                  <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', background: 'var(--bg-inset)', display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 8, alignItems: 'start' }}>
                    <span className="st-faint st-mono">{i + 1}</span>
                    <div><b style={{ color: 'var(--text-strong)' }}>{s.stage}</b><div className="st-muted" style={{ fontSize: 12.5, marginTop: 2 }}>{s.detail}</div></div>
                    <SourceLink src={s.source} label={s.source ? `${s.source.path.split('/').pop()}:${s.source.line}` : undefined} />
                  </div>
                </div>
              ))}
            </div>
          </Sec>

          <Sec title={`Tools (${a.tools.length})`} hint="definitions parsed from the MCP server modules and the in-process tool classes; usage from recorded spans"
            right={<ModeTabs mode={mode} set={setMode} />}>
            {a.tools.length === 0 ? <div className="st-muted">This agent has no tools: it reasons over the inputs it is given.</div> : (
              <Table testId="agent-tools" head={['tool', 'server', 'access', 'parameters', 'description', 'calls', 'errors', 'blocked']}
                rows={a.tools.map((t: any) => {
                  const u = h?.tools?.[t.name];
                  return [
                    <span className="st-mono"><Wrench size={11} style={{ verticalAlign: -1 }} /> {t.name}</span>,
                    t.mcp_server ? <span className="st-pill run">{t.mcp_server}</span> : <span className="st-pill">direct</span>,
                    t.read_only === true ? 'read-only' : t.read_only === false ? <span style={{ color: 'var(--warn)' }}>writes</span> : '—',
                    <span className="st-mono" style={{ fontSize: 11.5 }}>{(t.parameters ?? []).map((p: any) => `${p.name}${p.required ? '' : '?'}: ${p.type ?? 'any'}`).join(', ') || '—'}</span>,
                    <span style={{ fontSize: 12 }}>{t.description || t.direct_description || '—'} {t.source && <SourceLink src={t.source} label="" />}</span>,
                    num(u?.calls ?? 0), u?.errors ? <span style={{ color: 'var(--err)' }}>{u.errors}</span> : 0, u?.blocked ? <span style={{ color: 'var(--err)' }}>{u.blocked}</span> : 0,
                  ];
                })} />
            )}
            {h?.transports && <div className="st-faint" style={{ fontSize: 12, marginTop: 6 }}>Transports used: {Object.entries(h.transports).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>}
          </Sec>

          <Sec title="Guardrail checkpoints" hint="rules that can fire for this agent, derived from its permissions and output schema">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {a.guardrails.map((g: any) => (
                <button key={g.rule} className="st-pill" style={{ cursor: 'pointer', height: 22 }} onClick={() => openGuardrails(g.id)} title={`${g.name} · stage ${g.stage}`}>
                  <ShieldCheck size={11} /><b>{g.id}</b> {g.name}
                </button>
              ))}
            </div>
            {h?.guardrails && Object.keys(h.guardrails).length > 0 && (
              <div className="st-muted" style={{ fontSize: 12, marginTop: 8 }}>Recorded decisions ({mode}): {Object.entries(h.guardrails).map(([k, v]) => `${k} ×${v}`).join(' · ')}</div>
            )}
          </Sec>

          <Sec title="Input and output" hint="schemas the runtime enforces; per-run inputs and outputs are in each run's agent detail">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 12 }}>
              <div>
                <div className="st-muted" style={{ fontSize: 12, marginBottom: 4 }}>Structured input (step parameters)</div>
                <pre className="st-pre">{JSON.stringify(a.inputs, null, 2)}</pre>
              </div>
              <div>
                <div className="st-muted" style={{ fontSize: 12, marginBottom: 4 }}>Output schema — {a.output.llm_schema ?? 'n/a'} (Pydantic JSON schema)</div>
                <pre className="st-pre">{a.output.llm_schema_json ? JSON.stringify(a.output.llm_schema_json, null, 2) : 'This agent has no LLM output schema.'}</pre>
              </div>
            </div>
            <PromptViewer name={name} />
          </Sec>

          <Sec title="Execution history" hint="from the agent_runs table and recorded spans" right={<ModeTabs mode={mode} set={setMode} note />}>
            {!h || !h.executions ? <div className="st-muted">No {mode} execution of {name} is recorded{h?.not_invoked ? ` (${h.not_invoked} run(s) registered it without invoking it)` : ''}.</div> : (
              <>
                <Stats items={[
                  { label: 'Executions', value: num(h.executions), hint: `${num(h.invocations)} invocations${h.not_invoked ? ` · ${h.not_invoked} registered but not invoked` : ''}` },
                  { label: 'Successful', value: num(h.successful), tone: 'ok', hint: h.definitions?.successful },
                  { label: 'Failed', value: num(h.failed), tone: h.failed ? 'err' : undefined, hint: h.definitions?.failed },
                  { label: 'Partial', value: num(h.partial), hint: h.definitions?.partial },
                  { label: 'Avg duration', value: fmtMs(h.avg_duration_ms), hint: `median ${fmtMs(h.median_duration_ms)} per invocation` },
                  { label: 'Avg tokens', value: h.avg_tokens == null ? 'n/a' : num(h.avg_tokens), hint: `${h.runs_with_token_usage} run(s) reported usage` },
                  { label: 'Retries', value: num(h.validation_retries), hint: 'output-validation re-prompts (G8)' },
                  { label: 'Error rate', value: pct(h.error_rate, 1), hint: `failed invocations / invocations · ${h.llm_failures} LLM call failures` },
                  { label: 'Tool calls', value: num(h.tool_calls), hint: `${h.tool_errors} tool errors` },
                ]} />
                <div style={{ marginTop: 12 }}>
                  <Table testId="agent-recent" head={['run', 'started', 'architecture', 'run status', 'invocations', 'time', 'tokens', 'tools', 'retries']}
                    rows={h.recent.map((r: any) => [
                      <button className="st-link st-mono" onClick={() => openRun(r.run_id)}>{r.run_id.slice(0, 8)}</button>,
                      timeAgo(r.started_at), r.architecture, <span><StatusDot status={r.run_status} /> {r.run_status}</span>,
                      `${r.invocations}${r.failures ? ` (${r.failures} failed)` : ''}`, fmtMs(r.duration_ms), r.tokens ? num(r.tokens) : '—', r.tool_calls, r.validation_retries,
                    ])} />
                </div>
              </>
            )}
          </Sec>
        </Page>
      );
    }}</Load>
  );
}

function PromptViewer({ name }: { name: string }) {
  const [variant, setVariant] = useState('baseline');
  const [part, setPart] = useState<'ROLE' | 'GOAL' | 'BACKSTORY' | 'TASK'>('TASK');
  const q = useApi<any>(`/agents/${encodeURIComponent(name)}/prompt?variant=${variant}`);
  const hist = useApi<any>(`/agents/${encodeURIComponent(name)}/prompt-history`);
  return (
    <div style={{ marginTop: 14 }} data-testid="prompt-viewer">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
        <span className="st-muted" style={{ fontSize: 12 }}>Prompt context</span>
        <select className="st-select" value={variant} onChange={e => setVariant(e.target.value)}>
          {(q.data?.variants ?? ['baseline']).map((v: string) => <option key={v}>{v}</option>)}
        </select>
        {(['ROLE', 'GOAL', 'BACKSTORY', 'TASK'] as const).map(p => (
          <button key={p} className={`st-ptab${part === p ? ' active' : ''}`} onClick={() => setPart(p)}>{p}</button>
        ))}
        {q.data && <span className="st-faint" style={{ fontSize: 11.5 }}>prompt set {q.data.prompt_set_version} · agent version {q.data.agent_prompt_version}</span>}
      </div>
      <pre className="st-pre" style={{ maxHeight: 300 }}>{q.data?.parts?.[part] ?? (q.error ? q.error : 'Loading…')}</pre>
      {hist.data && (
        <div className="st-faint" style={{ fontSize: 12, marginTop: 6 }}>
          Version history: {hist.data.archived_versions.length} archived prompt set(s) used by runs
          ({hist.data.archived_versions.map((v: any) => `${v.variant} ${v.prompt_set_version} · agent ${v.agent_version} · ${v.runs} runs · first seen ${v.first_seen?.slice(0, 10)}`).join('; ') || 'none'}).
          Current code: {hist.data.current_code.map((c: any) => `${c.variant} ${c.agent_version}${c.archived ? '' : ' (never run)'}`).join(' · ')}.
        </div>
      )}
    </div>
  );
}
