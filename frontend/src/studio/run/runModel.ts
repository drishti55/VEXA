// Pure derivations from a run snapshot (live RunContext or stored RunResult). Nothing here invents data:
// every field is computed from events, coordination log, spans, callbacks, state or metrics the backend recorded.

import type { AgentRunResponse, RunResult, Span, GuardrailEvent, CoordinationEvent } from '../../api/client';

// The specialist roster of the VEXA runtime (backend/agents/crew.py); Manager exists only in hierarchical runs.
// Phase 4 replaces this with GET /agents.
export const SPECIALISTS = ['RequirementAnalyst', 'ProjectAnalyst', 'Planner', 'Coder', 'Tester', 'Debugger', 'Verifier'];

export type AgentStatus = 'not_dispatched' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';

export interface ToolCall { name: string; transport: string; mcpServer?: string; args?: string; status: string; durationMs: number; origin?: string; spanId: string; start: number }
export interface LlmCall { model: string; inputTokens?: number; outputTokens?: number; finishReason?: string; status: string; durationMs: number }

export interface AgentView {
  name: string;
  status: AgentStatus;
  framework?: string;
  invocations: number;
  failures: number;
  durationMs: number;
  firstStartedAt?: string | null;
  lastFinishedAt?: string | null;
  llmCalls: LlmCall[];
  inputTokens: number | null;
  outputTokens: number | null;
  usageNote?: string;
  tools: ToolCall[];
  filesRead: string[];
  filesWritten: string[];
  guardrails: GuardrailEvent[];
  retries: number;            // validation + LLM retries reported by the runtime
  errors: string[];
  inputs: { at: number; text: string }[];   // CrewAI task prompts (redacted by the backend)
  outputs: { at: number; text: string }[];  // CrewAI task outputs (redacted)
  stateWrites: string[];
  stateReads: string[];
  dispatches: number;
  lastDetail?: string;
}

const isFinal = (r: AgentRunResponse) => r.status !== 'running';

function argPath(args?: string): string | undefined {
  if (!args) return undefined;
  const m = args.match(/'path':\s*'([^']+)'/) ?? args.match(/"path":\s*"([^"]+)"/);
  return m?.[1];
}

export function spansOf(result?: RunResult): Span[] {
  return result?.trace?.spans ?? [];
}

export function agentViews(run: AgentRunResponse): AgentView[] {
  const res = run.result;
  const events = res?.events ?? [];
  const coord = res?.coordination_log ?? [];
  const metrics = (res?.agent_metrics ?? res?.trace?.agent_metrics ?? {}) as Record<string, any>;
  const spans = spansOf(res);
  const callbacks: any[] = (res?.trace as any)?.callback_events ?? [];
  const guards = res?.guardrail_events ?? [];
  const access = res?.state?.access_log ?? [];
  const provenance: Record<string, any> = (res as any)?.file_provenance ?? (res?.trace as any)?.file_provenance ?? {};

  const names = new Set<string>(SPECIALISTS);
  if (run.architecture === 'hierarchical') names.add('Manager');
  Object.keys(metrics).forEach(n => names.add(n));
  events.forEach(e => e.agent && e.agent !== 'runtime' && names.add(e.agent));
  coord.filter(c => c.kind === 'dispatch' && c.target).forEach(c => names.add(c.target!));

  const order = [...(run.architecture === 'hierarchical' ? ['Manager'] : []), ...SPECIALISTS];
  const sorted = [...names].sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));

  return sorted.map(name => {
    const m = metrics[name] ?? {};
    const evs = events.filter(e => e.agent === name);
    // status from the agent's own lifecycle events
    let status: AgentStatus = 'not_dispatched';
    let open = 0;
    for (const e of evs) {
      if (e.event === 'started') open++;
      if (e.event === 'completed' || e.event === 'failed') { open = Math.max(0, open - 1); status = e.event; }
    }
    if (open > 0) status = isFinal(run) ? (run.status === 'interrupted' ? 'interrupted' : 'cancelled') : 'running';
    if (status === 'not_dispatched' && (m.invocations ?? 0) > 0) status = m.failures ? 'failed' : 'completed';

    const mySpans = spans.filter(s => s.attributes?.['vexa.agent'] === name);
    const tools: ToolCall[] = mySpans.filter(s => s.kind === 'tool').map(s => ({
      name: s.attributes['vexa.tool'] ?? s.name, transport: s.attributes['vexa.transport'] ?? 'direct',
      mcpServer: s.attributes['vexa.mcp_server'], args: s.attributes['vexa.args'], status: s.status,
      durationMs: s.duration_ms, origin: s.attributes['vexa.origin'], spanId: s.span_id, start: s.start_ns,
    }));
    const llmCalls: LlmCall[] = mySpans.filter(s => s.kind === 'llm').map(s => ({
      model: s.attributes['vexa.model'], inputTokens: s.attributes['vexa.input_tokens'], outputTokens: s.attributes['vexa.output_tokens'],
      finishReason: s.attributes['vexa.finish_reason'], status: s.status, durationMs: s.duration_ms,
    }));
    const filesRead = [...new Set(tools.filter(t => t.name === 'read_file').map(t => argPath(t.args)).filter(Boolean) as string[])];
    const filesWritten = Object.entries(provenance)
      .filter(([, w]) => (Array.isArray(w) ? w : [w]).some((x: any) => x?.agent === name)).map(([p]) => p);
    const cbs = callbacks.filter(c => c.agent === name);
    return {
      name, status,
      framework: m.framework,
      invocations: m.invocations ?? evs.filter(e => e.event === 'started').length,
      failures: m.failures ?? evs.filter(e => e.event === 'failed').length,
      durationMs: m.duration_ms ?? evs.reduce((a, e) => a + (e.duration_ms ?? 0), 0),
      firstStartedAt: m.first_started_at ?? evs.find(e => e.event === 'started')?.timestamp ?? null,
      lastFinishedAt: m.last_finished_at ?? null,
      llmCalls,
      inputTokens: m.input_tokens ?? null,
      outputTokens: m.output_tokens ?? null,
      usageNote: m.usage_note,
      tools, filesRead, filesWritten,
      guardrails: guards.filter(g => g.agent === name),
      retries: (m.validation_retries ?? 0) + (m.llm_retries ?? 0),
      errors: evs.filter(e => e.event === 'failed' || e.event.endsWith('_failed')).map(e => e.detail).filter(Boolean),
      inputs: cbs.filter(c => c.kind === 'task_started' && c.task).map(c => ({ at: c.at, text: c.task })),
      outputs: cbs.filter(c => c.kind === 'task_completed' && c.output).map(c => ({ at: c.at, text: c.output })),
      stateWrites: [...new Set(access.filter(a => a.agent === name && a.kind === 'write').map(a => a.key))],
      stateReads: [...new Set(access.filter(a => a.agent === name && a.kind === 'read').map(a => a.key))],
      dispatches: coord.filter(c => c.kind === 'dispatch' && c.target === name).length,
      lastDetail: [...evs].reverse().find(e => e.detail)?.detail,
    };
  });
}

// ---------------------------------------------------------------- timeline

export interface TimelineItem {
  t: number;              // epoch ms
  source: 'agent' | 'coordination' | 'guardrail' | 'callback';
  kind: string;
  actor: string;
  target?: string | null;
  text: string;
  tone: 'ok' | 'err' | 'warn' | 'run' | 'muted';
  data: any;
}

const toneOfEvent = (e: string): TimelineItem['tone'] =>
  e === 'completed' ? 'ok' : e === 'failed' || e.endsWith('_failed') ? 'err' : e === 'started' ? 'run' : 'muted';

export function timeline(run: AgentRunResponse): TimelineItem[] {
  const res = run.result;
  const items: TimelineItem[] = [];
  for (const e of res?.events ?? []) {
    items.push({ t: +new Date(e.timestamp), source: 'agent', kind: e.event, actor: e.agent, text: e.detail ? `${e.event} — ${e.detail}` : e.event,
      tone: toneOfEvent(e.event), data: e });
  }
  for (const c of (res?.coordination_log ?? []) as (CoordinationEvent & { at?: string })[]) {
    items.push({ t: c.at ? +new Date(c.at) : NaN, source: 'coordination', kind: c.kind, actor: c.actor, target: c.target,
      text: c.detail || `${c.kind}${c.target ? ` → ${c.target}` : ''}`, tone: c.kind === 'stop' ? 'muted' : c.kind === 'review' ? 'warn' : 'run', data: c });
  }
  for (const g of res?.guardrail_events ?? []) {
    items.push({ t: +new Date(g.at), source: 'guardrail', kind: `${g.rule} ${g.decision}`, actor: g.agent ?? 'runtime',
      text: `${g.rule} ${g.rule_name}: ${g.decision}${g.reason ? ` — ${g.reason}` : ''}`,
      tone: g.decision === 'blocked' ? 'err' : g.decision === 'flagged' || g.decision === 'indeterminate' ? 'warn' : 'muted', data: g });
  }
  for (const c of ((res?.trace as any)?.callback_events ?? []) as any[]) {
    if (c.kind === 'task_started' || c.kind === 'task_completed') continue; // shown as agent started/completed
    items.push({ t: typeof c.at === 'number' ? c.at * 1000 : +new Date(c.at), source: 'callback', kind: c.kind, actor: c.agent ?? 'crewai',
      text: c.kind + (c.error ? ` — ${c.error}` : c.retry_count ? ` (retry ${c.retry_count})` : ''), tone: c.error ? 'warn' : 'muted', data: c });
  }
  // stable sort by time; items without a timestamp keep their source order at the end of their group
  return items.map((x, i) => ({ x, i })).sort((a, b) => (a.x.t || 0) - (b.x.t || 0) || a.i - b.i).map(({ x }) => x);
}

export function dispatchSequence(run: AgentRunResponse): { agent: string; actor: string; seq: number; n: number }[] {
  const seen: Record<string, number> = {};
  return (run.result?.coordination_log ?? []).filter(c => c.kind === 'dispatch' && c.target).map(c => ({
    agent: c.target!, actor: c.actor, seq: c.seq, n: (seen[c.target!] = (seen[c.target!] ?? 0) + 1),
  }));
}
