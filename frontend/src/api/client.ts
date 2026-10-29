// VEXA API Client — types mirror backend/agents/contracts.py and the API routers.

export const API_BASE_URL: string = import.meta.env.VITE_VEXA_API_URL ?? 'http://localhost:8000';
const API_TOKEN: string | undefined = import.meta.env.VITE_VEXA_API_TOKEN;

// Every API call goes through here so the optional bearer token is always sent.
function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (API_TOKEN) headers.set('Authorization', `Bearer ${API_TOKEN}`);
  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(message: string, status: number, detail: any) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

// FastAPI errors: a string, a validation list [{loc, msg}], or a structured object with a message.
function describeDetail(detail: any): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => `${(d.loc ?? []).filter((x: any) => x !== 'body').join('.') || 'request'}: ${d.msg}`).join('; ');
  }
  if (detail && typeof detail === 'object') return detail.message ?? JSON.stringify(detail);
  return '';
}

async function json<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(describeDetail(err.detail) || `${what} failed (HTTP ${res.status})`, res.status, err.detail);
  }
  return res.json();
}

export interface Workspace {
  workspace_id: string;
  project_root: string;
  status: string;
  created_at: string;
}

export interface AgentEvent {
  timestamp: string;
  agent: string;
  event: string;
  detail: string;
  duration_ms: number | null;
}

export interface CoordinationEvent {
  seq: number;
  kind: 'dispatch' | 'decision' | 'event' | 'delivery' | 'message' | 'review' | 'stop';
  actor: string;
  target: string | null;
  detail: string;
  data: Record<string, any>;
  at: string;
}

export interface StateEntry {
  entry_id: string;
  seq: number;
  key: string;
  version: number;
  author: string;
  value_type: string;
  value: any;
  written_at: string;
  derived_from: string[];
}

export interface StateAccess {
  seq: number;
  kind: 'read' | 'write';
  key: string;
  agent: string;
  version: number | null;
}

export interface Span {
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: 'run' | 'agent' | 'tool' | 'llm' | string;
  start_ns: number;
  end_ns: number;
  duration_ms: number;
  status: string;
  status_message: string | null;
  attributes: Record<string, any>;
  source?: string;  // vexa | google-adk | a2a-python-sdk (framework OpenTelemetry spans in the same trace)
  events?: { name: string; attributes: Record<string, any> }[];
}

export interface GuardrailEvent {
  seq: number;
  run_id: string;
  rule: string;
  rule_name: string;
  kind: string;
  agent: string | null;
  decision: 'allowed' | 'blocked' | 'sanitized' | 'flagged' | 'indeterminate';
  action: string;
  reason: string;
  detail: string;
  at: string;
  tool?: string;
}

export interface AgentMetrics {
  framework: string;
  status: string;
  first_started_at: string | null;
  last_finished_at: string | null;
  invocations: number;
  failures: number;
  duration_ms: number;
  llm_calls: number;
  usage_available: boolean;
  usage_note?: string;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd?: number | null;
  tool_calls: number;
  tool_errors: number;
  validation_retries: number;
  llm_retries?: number;
  guardrail_blocks: number;
}

export interface TestResult {
  passed: boolean;
  no_tests: boolean;
  exit_code: number | null;
  tests_found: number;
  tests_passed: number;
  tests_failed: number;
  failures: string[];
  verdict_source: string;
}

export interface VerificationResult {
  verified: boolean;
  llm_claimed_verified: boolean | null;
  requirements_satisfied: string[];
  requirements_failed: string[];
  backend: string;
  remote: Record<string, any> | null;
  evidence: string;
}

// Either a finished RunResult or a live RunContext snapshot; fields shared by both.
export interface RunResult {
  run_id: string;
  workspace_id: string;
  requirement: string;
  architecture: string;
  execution_mode: string;
  provider: string | null;
  model: string | null;
  prompt_variant?: string | null;
  prompt_version?: string | null;
  current_agent: string;
  started_at: string;
  finished_at: string | null;
  files_changed: string[];
  test_attempts: number;
  debug_iterations: number;
  errors: string[];
  usage_available: boolean;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  cost_basis?: string;
  events: AgentEvent[];
  coordination_log?: CoordinationEvent[];
  state?: { entries: StateEntry[]; access_log: StateAccess[] };
  guardrail_events?: GuardrailEvent[];
  agent_metrics?: Record<string, AgentMetrics>;
  trace?: { spans: Span[]; callback_events: any[]; agent_metrics?: Record<string, AgentMetrics> } | null;
  trace_id?: string | null;
  tool_transport?: string | null;
  verifier_backend?: string | null;
  code_changes?: { path: string; change: string; lines_added: number; lines_removed: number; diff: string }[];
  metadata?: Record<string, any>;
  mcp_servers?: { name: string; status: string; tools: string[] }[];
  final_test_result?: TestResult | null;
  verification_result?: VerificationResult | null;
}

export interface AgentRunResponse {
  run_id: string;
  workspace_id: string;
  execution_mode: string;
  architecture: string;
  status: string;
  total_duration_ms: number;
  files_changed: string[];
  debug_iterations: number;
  errors: string[];
  result: RunResult;
}

export interface AgentRunListResponse {
  runs: AgentRunResponse[];
}

export interface Option {
  name: string;
  description: string;
  version?: string;
}

export interface RateStat {
  k: number;
  n: number;
  rate: number | null;
  ci95: [number | null, number | null];
}

export interface Described {
  n: number;
  mean: number | null;
  sd: number | null;
  median: number | null;
  p90: number | null;
}

export interface ConditionSummary {
  architecture: string;
  prompt_variant: string;
  model: string;
  runs: number;
  prompt_versions?: string[];
  config_fingerprints?: string[];
  comparable?: boolean;
  warnings?: string[];
  task_success: RateStat;
  verified_claimed: RateStat;
  verifier_false_positive: RateStat;
  regression: RateStat;
  run_failed: RateStat;
  timeouts: RateStat;
  hidden_pass_rate: Described;
  latency_ms: Described;
  debug_iterations: Described;
  llm_calls: Described;
  tool_calls: Described;
  total_tokens: Described & { runs_with_usage: number };
  estimated_cost_usd: Described & { total: number; runs_with_cost: number; label: string };
  guardrails: { blocked_total: number; flagged_total: number };
  repeatability: { tasks_with_repeats: number; consistent_tasks: number };
  agent_time_share: Record<string, number>;
}

export interface Comparison {
  a: string;
  b: string;
  prompt_variant?: string;
  architecture?: string;
  model: string;
  success_diff_a_minus_b: { diff: number | null; low: number | null; high: number | null };
  comparable?: boolean;
  warnings?: string[];
}

export interface ExperimentSummary {
  experiment: Experiment;
  conditions: ConditionSummary[];
  comparable?: boolean;
  warnings?: string[];
  prompt_comparisons: Comparison[];
  architecture_comparisons: {
    prompt_variant: string;
    model: string;
    a: string;
    b: string;
    success_diff_a_minus_b: { diff: number | null; low: number | null; high: number | null };
  }[];
  total_runs: number;
}

export interface Experiment {
  experiment_id: string;
  name: string;
  description: string | null;
  status: string;
  config: Record<string, any>;
  environment: Record<string, any>;
  created_at: string;
  finished_at: string | null;
  run_count: number;
  total_trials: number | null;
  completed_trials: number | null;
  failed_trials: number | null;
  error: string | null;
  active?: boolean;
}

export interface ExperimentOptions {
  tasks: { id: string; title: string; category: string; difficulty: string }[];
  architectures: Option[];
  prompt_variants: Option[];
  execution_modes: string[];
  tool_transports: string[];
  verifier_backends: Option[];
  configured_model: { model: string; provider: string; api_key_configured: boolean;
    input_cost_per_1m: number | null; output_cost_per_1m: number | null };
  docs_search_available: boolean;
  sandbox_backend: string;
  rag: { available: boolean; note: string };
}

export interface Validation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  total_trials: number;
  tasks: string[];
}

export interface ExperimentRunRow {
  run_id: string;
  task_id: string;
  category: string | null;
  architecture: string;
  prompt_variant: string;
  model_condition: string;
  status: string;
  task_success: boolean;
  hidden_pass_rate: number | null;
  regression: boolean;
  verified: boolean | null;
  duration_ms: number;
  llm_calls: number;
  tool_calls: number;
  total_tokens: number | null;
  usage_available: boolean;
  estimated_cost_usd: number | null;
  debug_iterations: number;
  repeat_index: number | null;
  guard_blocked: number;
  guard_flagged: number;
}

export interface SubmitRunOptions {
  workspace_id: string;
  requirement: string;
  execution_mode: string;
  architecture: string;
  prompt_variant: string;
  verifier_backend?: string;
  tool_transport?: string;
  llm_model?: string;
  llm_api_key?: string;
  llm_fallback_api_key?: string;
  confirm_guardrail_review?: boolean;
  task_category?: string;
}

export const VexaApi = {
  getWorkspaces: async (): Promise<{ workspaces: Workspace[] }> => {
    const data = await json<string[]>(await apiFetch(`/workspaces`), 'Listing workspaces');
    return { workspaces: data.map(id => ({ workspace_id: id, project_root: '', status: '', created_at: '' })) };
  },

  createWorkspace: async (custom_id?: string, output_path?: string): Promise<Workspace> => {
    const data = await json<any>(await apiFetch(`/workspaces`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: custom_id, output_path: output_path || null }),
    }), 'Creating workspace');
    return { workspace_id: data.workspace_id, project_root: data.output_path || '', status: '', created_at: '' };
  },

  submitAgentRunAsync: async (opts: SubmitRunOptions): Promise<AgentRunResponse> =>
    json(await apiFetch(`/agent-runs/async`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...opts,
        llm_model: opts.llm_model || undefined,
        llm_api_key: opts.llm_api_key || undefined,
        llm_fallback_api_key: opts.llm_fallback_api_key || undefined,
      }),
    }), 'Starting run'),

  cancelAgentRun: async (run_id: string): Promise<{ run_id: string; status: string }> =>
    json(await apiFetch(`/agent-runs/${encodeURIComponent(run_id)}/cancel`, { method: 'POST' }), 'Cancelling run'),

  getAgentRun: async (run_id: string): Promise<AgentRunResponse> =>
    json(await apiFetch(`/agent-runs/${encodeURIComponent(run_id)}`), 'Fetching run'),

  listAgentRuns: async (): Promise<AgentRunListResponse> => json(await apiFetch(`/agent-runs`), 'Listing runs'),

  getArchitectures: async (): Promise<Option[]> => json(await apiFetch(`/agent-runs/architectures`), 'Listing architectures'),

  getPromptVariants: async (): Promise<Option[]> => json(await apiFetch(`/agent-runs/prompt-variants`), 'Listing prompt variants'),

  testModel: async (llm_model?: string, llm_api_key?: string): Promise<{ ok: boolean; model: string; provider: string; latency_ms?: number; error?: string }> =>
    json(await apiFetch(`/agent-runs/test-model`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm_model: llm_model || undefined, llm_api_key: llm_api_key || undefined }),
    }), 'Testing model'),

  getReport: async (run_id: string): Promise<any> =>
    json(await apiFetch(`/agent-runs/${encodeURIComponent(run_id)}/report`), 'Report'),

  downloadRunReport: async (run_id: string, format: 'json' | 'md'): Promise<void> => {
    const res = await apiFetch(`/agent-runs/${encodeURIComponent(run_id)}/report${format === 'md' ? '?format=md' : ''}`);
    if (!res.ok) throw new Error(`Report unavailable (HTTP ${res.status})`);
    const blob = format === 'md' ? await res.blob() : new Blob([JSON.stringify(await res.json(), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vexa-run-${run_id.slice(0, 8)}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  },

  getReportMarkdown: async (run_id: string): Promise<string> => {
    const res = await apiFetch(`/agent-runs/${encodeURIComponent(run_id)}/report?format=md`);
    if (!res.ok) throw new Error(`Report unavailable (HTTP ${res.status})`);
    return res.text();
  },

  /**
   * Subscribe to live run snapshots over server-sent events.
   * Falls back to polling if the stream cannot be opened. Returns an unsubscribe function.
   */
  streamRun: (run_id: string, onSnapshot: (r: AgentRunResponse) => void, onDone: () => void): (() => void) => {
    const qs = API_TOKEN ? `?token=${encodeURIComponent(API_TOKEN)}` : '';
    let closed = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const es = new EventSource(`${API_BASE_URL}/agent-runs/${encodeURIComponent(run_id)}/stream${qs}`);
    es.addEventListener('snapshot', (e) => onSnapshot(JSON.parse((e as MessageEvent).data)));
    es.addEventListener('done', () => { es.close(); if (!closed) { closed = true; onDone(); } });
    es.onerror = () => {
      es.close();
      if (closed || timer) return;
      timer = setInterval(async () => {
        try {
          const run = await VexaApi.getAgentRun(run_id);
          onSnapshot(run);
          if (!['running'].includes(run.status)) { clearInterval(timer); closed = true; onDone(); }
        } catch { /* keep polling */ }
      }, 1000);
    };
    return () => { closed = true; es.close(); if (timer) clearInterval(timer); };
  },

  getFileDiff: async (workspace_id: string): Promise<string | null> => {
    // payload is a ToolResult whose data holds the diff
    const body = await json<any>(await apiFetch(`/workspaces/${encodeURIComponent(workspace_id)}/git/diff`), 'Diff');
    if (!body.data?.is_git_repo) return null;
    return body.data.diff || null;
  },

  listFiles: async (workspace_id: string): Promise<any> =>
    json(await apiFetch(`/workspaces/${encodeURIComponent(workspace_id)}/files`), 'Listing files'),

  readFile: async (workspace_id: string, path: string): Promise<any> =>
    json(await apiFetch(`/workspaces/${encodeURIComponent(workspace_id)}/read`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }), 'Reading file'),

  listExperiments: async (): Promise<Experiment[]> => json(await apiFetch(`/experiments`), 'Listing experiments'),

  getExperimentSummary: async (id: string): Promise<ExperimentSummary> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}/summary`), 'Experiment summary'),

  getExperimentOptions: async (): Promise<ExperimentOptions> => json(await apiFetch(`/experiments/options`), 'Experiment options'),

  validateExperiment: async (config: Record<string, any>, llm_api_key?: string): Promise<Validation> =>
    json(await apiFetch(`/experiments/validate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, llm_api_key: llm_api_key || undefined }),
    }), 'Validating experiment'),

  startExperiment: async (config: Record<string, any>, confirm_real_cost = false, llm_api_key?: string):
    Promise<{ experiment_id: string; status: string; total_trials: number; warnings: string[] }> =>
    json(await apiFetch(`/experiments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, confirm_real_cost, llm_api_key: llm_api_key || undefined }),
    }), 'Starting experiment'),

  cancelExperiment: async (id: string): Promise<any> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}/cancel`, { method: 'POST' }), 'Cancelling'),

  rerunExperiment: async (id: string, opts: { pin_prompt_versions?: boolean; confirm_real_cost?: boolean; llm_api_key?: string } = {}): Promise<any> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}/rerun`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin_prompt_versions: opts.pin_prompt_versions ?? true, confirm_real_cost: !!opts.confirm_real_cost,
        llm_api_key: opts.llm_api_key || undefined }),
    }), 'Rerunning'),

  resumeExperiment: async (id: string, llm_api_key?: string): Promise<any> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}/resume`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm_api_key: llm_api_key || undefined }),
    }), 'Resuming'),

  getExperiment: async (id: string): Promise<Experiment> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}`), 'Experiment'),

  getExperimentRuns: async (id: string): Promise<ExperimentRunRow[]> =>
    json(await apiFetch(`/experiments/${encodeURIComponent(id)}/runs`), 'Experiment runs'),

  downloadExport: async (id: string, format: 'csv' | 'json' | 'md'): Promise<void> => {
    const res = await apiFetch(`/experiments/${encodeURIComponent(id)}/export?format=${format}`);
    if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `${id}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  },
};
