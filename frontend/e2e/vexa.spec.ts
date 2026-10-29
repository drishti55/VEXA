import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Real UI → real backend. Each test checks the browser AND the backend effect (API / SQLite).
const API = 'http://127.0.0.1:8790';

const BUGGY = `def add(a, b):\n    return a + b\n\n\ndef modulo(a, b):\n    return a + b  # BUG\n`;
const TEST = `import os, sys\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n` +
  `from calculator import add, modulo\n\ndef test_add():\n    assert add(2, 3) == 5\n\n` +
  `def test_modulo():\n    assert modulo(10, 3) == 1\n`;

async function makeWorkspace(request: APIRequestContext, broken = true): Promise<string> {
  const ws = (await (await request.post(`${API}/workspaces`, { data: {} })).json()).workspace_id as string;
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'src/calculator.py', content: broken ? BUGGY : BUGGY.replace('a + b  # BUG', 'a % b') } });
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'tests/test_calculator.py', content: TEST } });
  return ws;
}

// Collect console errors and failed requests; expected 409 (guardrail review) is allowed.
function watch(page: Page) {
  const problems: string[] = [];
  page.on('console', m => { if (m.type() === 'error') problems.push(`console: ${m.text()}`); });
  page.on('pageerror', e => problems.push(`pageerror: ${e.message}`));
  page.on('response', r => {
    if (r.url().startsWith(API) && r.status() >= 400 && r.status() !== 409) problems.push(`HTTP ${r.status()} ${r.url()}`);
  });
  page.on('requestfailed', r => { if (r.url().startsWith(API)) problems.push(`failed: ${r.url()} ${r.failure()?.errorText}`); });
  return problems;
}

async function startRun(page: Page, ws: string, requirement: string, opts: { arch?: string; category?: string } = {}) {
  await page.goto('/');
  await page.getByTestId('workspace-select').selectOption(ws);
  await page.getByTestId('requirement').fill(requirement);
  await page.getByTestId('execution-mode').selectOption('mock');
  if (opts.arch) await page.getByTestId('architecture-select').selectOption(opts.arch);
  if (opts.category) await page.getByTestId('task-category').selectOption(opts.category);
  await page.getByTestId('run-button').click();
}

async function waitFinished(page: Page) {
  await expect(page.getByTestId('run-status')).toHaveText(/SUCCESS|PARTIAL|FAILED/, { timeout: 150_000 });
  return (await page.getByTestId('run-status').innerText()).trim();
}

test('mock hierarchical run: live monitoring, coordination, trace, guardrails, report, editor, preview', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await startRun(page, ws, 'Fix the failing modulo test in src/calculator.py', { arch: 'hierarchical', category: 'bug_fix' });

  // live: status moves through RUNNING before it finishes
  await expect(page.getByTestId('run-status')).toHaveText(/RUNNING|SUCCESS|PARTIAL|FAILED/);
  const status = await waitFinished(page);
  expect(status).toContain('MOCK');

  // backend effect: the run is persisted with the same id the UI shows
  const runs = (await (await request.get(`${API}/agent-runs/registry/runs?limit=5`)).json()) as any[];
  const run = runs.find(r => r.workspace_id === ws);
  expect(run, 'run persisted in SQLite').toBeTruthy();
  expect(run.architecture).toBe('hierarchical');
  expect(run.config_fingerprint).toMatch(/^[0-9a-f]{16}$/);

  // coordination: the mock policy decision and the reproduce-first route are visible
  await page.getByTestId('tab-coordination').click();
  await expect(page.getByText(/mock policy: reproduce_first/)).toBeVisible();
  await expect(page.getByText('route: repair').first()).toBeVisible();

  // trace: real spans, VEXA + A2A-SDK + ADK sources in one trace, guardrail decisions listed
  await page.getByTestId('tab-trace').click();
  await expect(page.getByTestId('trace-span').first()).toBeVisible();
  const sources = await page.getByTestId('trace-sources').innerText();
  expect(sources).toContain('vexa');
  expect(sources).toMatch(/google-adk|a2a/);
  await expect(page.getByText(/G2|G6|G9/).first()).toBeVisible();

  // report: rendered from the backend, labelled as mock
  await page.getByTestId('tab-report').click();
  await expect(page.getByText(/MOCK RUN/).first()).toBeVisible();
  await expect(page.getByText(/deterministic mock policy/).first()).toBeVisible();

  // code editor: workspace file tree and content
  await page.getByTestId('tab-code').click();
  await expect(page.getByText('src/calculator.py').first()).toBeVisible();
  await page.getByText('src/calculator.py').first().click();
  await expect(page.locator('.monaco-editor, textarea').first()).toBeVisible({ timeout: 60_000 });

  // preview: a Python project has no web page — the UI says so instead of loading a 404
  await page.getByTestId('tab-preview').click();
  await expect(page.getByTestId('preview-unavailable')).toBeVisible();

  expect(problems, problems.join('\n')).toEqual([]);
});

test('sequential vs hierarchical take different paths for the same bug-fix task', async ({ page, request }) => {
  const paths: Record<string, string[]> = {};
  for (const arch of ['sequential', 'hierarchical']) {
    const ws = await makeWorkspace(request);
    await startRun(page, ws, 'Fix the failing modulo test', { arch, category: 'bug_fix' });
    await waitFinished(page);
    const runs = (await (await request.get(`${API}/agent-runs/registry/runs?limit=10`)).json()) as any[];
    const id = runs.find(r => r.workspace_id === ws).run_id;
    const full = await (await request.get(`${API}/agent-runs/${id}`)).json();
    paths[arch] = full.result.coordination_log.filter((c: any) => c.kind === 'dispatch').map((c: any) => c.target);
  }
  expect(paths.sequential.slice(0, 3)).toEqual(['RequirementAnalyst', 'ProjectAnalyst', 'Planner']);
  expect(paths.hierarchical.slice(0, 3)).toEqual(['RequirementAnalyst', 'Tester', 'Debugger']);
});

test('preview renders a web workspace in the sandboxed iframe', async ({ page, request }) => {
  const ws = (await (await request.post(`${API}/workspaces`, { data: {} })).json()).workspace_id as string;
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'index.html', content: '<h1 id="hello">Hello VEXA</h1>' } });
  await page.goto('/');
  await page.getByTestId('workspace-select').selectOption(ws);
  await page.getByTestId('tab-preview').click();
  await expect(page.frameLocator('iframe[title="Web Preview"]').locator('#hello')).toHaveText('Hello VEXA');
});

test('G1 ambiguous requirement asks the human, then runs with the decision recorded', async ({ page, request }) => {
  const ws = await makeWorkspace(request, false);
  let dialogText = '';
  page.on('dialog', d => { dialogText = d.message(); d.accept(); });
  await startRun(page, ws, 'Show the API key field in the settings form');
  await waitFinished(page);
  expect(dialogText).toContain('Guardrail G1 needs your review');
  const runs = (await (await request.get(`${API}/agent-runs/registry/runs?limit=10`)).json()) as any[];
  const full = await (await request.get(`${API}/agent-runs/${runs.find(r => r.workspace_id === ws).run_id}`)).json();
  const g1 = full.result.guardrail_events.filter((g: any) => g.rule === 'G1');
  expect(g1[0].decision).toBe('flagged');
  expect(g1[0].confirmed_by).toBe('user');
});

test('model/provider configuration: real mode shows the model field and Test model reports the key status', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('execution-mode').selectOption('real');
  await expect(page.getByTestId('llm-model')).toBeVisible();
  await page.getByTestId('nav-experiments').click();
  await page.getByTestId('exp-mode-real').click();
  await page.getByRole('button', { name: 'Test model' }).click();
  // the e2e backend runs without keys: the UI must show the backend's honest answer, not a fake success
  await expect(page.getByText(/failed · no API key configured/)).toBeVisible();
});

test('experiment: configure, run, retrieve results, compare, export, rerun with pinned prompts', async ({ page, request }) => {
  const problems = watch(page);
  await page.goto('/');
  await page.getByTestId('nav-experiments').click();
  const name = `e2e-${Date.now()}`;
  await page.getByTestId('exp-name').fill(name);
  await page.getByTestId('exp-mode-mock').click();
  // one task, two architectures
  await page.getByRole('button', { name: 'none' }).click();
  await page.getByTestId('exp-task-feature_modulo').check();
  for (const arch of ['sequential', 'hierarchical', 'event_driven', 'blackboard']) {
    const box = page.locator('fieldset', { hasText: 'Architectures' }).locator('label', { hasText: new RegExp(`^${arch}`) })
      .locator('input[type=checkbox]');
    await box.setChecked(arch === 'sequential' || arch === 'hierarchical');
  }
  await page.getByTestId('exp-validate').click();
  await expect(page.getByText(/valid|trials/i).first()).toBeVisible();
  await page.getByTestId('exp-start').click();

  const item = page.getByTestId('exp-list-item').filter({ hasText: name });
  await expect(item).toBeVisible();
  await item.click();
  await expect(item).toHaveAttribute('data-status', 'completed', { timeout: 170_000 });
  await item.click();

  // results and comparison come from the stored raw runs
  await expect(page.getByText('Aggregated by condition')).toBeVisible();
  await expect(page.getByTestId('condition-prompt-version').first()).toHaveText(/[0-9a-f]{8}/);
  await expect(page.getByTestId('comparison').first()).toBeVisible();

  const exps = (await (await request.get(`${API}/experiments`)).json()) as any[];
  const exp = exps.find(e => e.name === name);
  const rows = (await (await request.get(`${API}/experiments/${exp.experiment_id}/runs`)).json()) as any[];
  expect(rows.length).toBe(2);
  expect(new Set(rows.map(r => r.architecture))).toEqual(new Set(['sequential', 'hierarchical']));
  const csv = await request.get(`${API}/experiments/${exp.experiment_id}/export?format=csv`);
  expect(csv.status()).toBe(200);

  // rerun: a NEW experiment with the original prompt versions pinned; the original is untouched
  await page.getByTestId('rerun-experiment').click();
  await expect(page.getByTestId('exp-list-item').filter({ hasText: `Rerun of ${name}` })).toBeVisible();
  const after = (await (await request.get(`${API}/experiments`)).json()) as any[];
  const rerun = after.find(e => e.name === `Rerun of ${name}`);
  expect(rerun.config.rerun_of).toBe(exp.experiment_id);
  expect(rerun.config.prompt_version_pins.baseline).toBe(rows[0].prompt_version);

  expect(problems, problems.join('\n')).toEqual([]);
});

test('new workspace: + New opens a named form, invalid/duplicate names are refused, the new one is selected', async ({ page, request }) => {
  const problems = watch(page);
  const name = `My App ${Date.now()}`;
  await page.goto('/');
  await page.getByTestId('new-workspace-toggle').click();
  const input = page.getByTestId('new-workspace-name');
  await expect(input).toBeVisible();

  // client-side validation mirrors the backend rule
  await input.fill('../escape');
  await expect(page.getByTestId('new-workspace-name-error')).toBeVisible();
  await expect(page.getByTestId('create-workspace')).toBeDisabled();

  await input.fill(name);
  await expect(page.getByTestId('new-workspace-name-error')).toHaveCount(0);
  await page.getByTestId('create-workspace').click();
  await expect(page.getByTestId('new-workspace-form')).toHaveCount(0);
  await expect(page.getByTestId('workspace-select')).toHaveValue(name);

  // backend effect: it exists under that name; a second create with the same name is a 409, not a reuse
  expect(((await (await request.get(`${API}/workspaces`)).json()) as string[])).toContain(name);
  expect((await request.post(`${API}/workspaces`, { data: { workspace_id: name } })).status()).toBe(409);

  // the UI also refuses the duplicate before sending it
  await page.getByTestId('new-workspace-toggle').click();
  await page.getByTestId('new-workspace-name').fill(name);
  await expect(page.getByTestId('new-workspace-name-error')).toContainText('already exists');

  expect(problems, problems.join('\n')).toEqual([]);
});

test('stop run: the button cancels a running run, which ends failed with the cancellation recorded', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await startRun(page, ws, 'Fix the failing modulo test in src/calculator.py', { arch: 'blackboard' });
  await expect(page.getByTestId('cancel-run')).toBeVisible();
  await page.getByTestId('cancel-run').click();
  await expect(page.getByTestId('cancel-run')).toHaveText(/Stopping/);
  const status = await waitFinished(page);
  expect(status).toContain('FAILED');
  await expect(page.getByTestId('cancel-run')).toHaveCount(0);

  const runs = (await (await request.get(`${API}/agent-runs/registry/runs?limit=10`)).json()) as any[];
  const full = await (await request.get(`${API}/agent-runs/${runs.find(r => r.workspace_id === ws).run_id}`)).json();
  expect(full.errors.join(' ')).toMatch(/cancelled/);
  expect(full.result.coordination_log.some((c: any) => c.kind === 'stop' && /cancelled/.test(c.detail))).toBe(true);
  expect(problems, problems.join('\n')).toEqual([]);
});
