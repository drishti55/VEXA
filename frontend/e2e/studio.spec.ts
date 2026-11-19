import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// VEXA Studio, real browser → real backend (isolated, mock mode). Every UI assertion is paired with
// a backend check, so the test fails if the UI shows something the backend did not record.
const API = 'http://127.0.0.1:8790';

const CALC = `def add(a, b):\n    return a + b\n`;
const TEST = `import os, sys\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n` +
  `from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n`;

async function makeWorkspace(request: APIRequestContext): Promise<string> {
  const ws = (await (await request.post(`${API}/workspaces`, { data: {} })).json()).workspace_id as string;
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'src/calculator.py', content: CALC } });
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'tests/test_calculator.py', content: TEST } });
  return ws;
}

async function readFile(request: APIRequestContext, ws: string, path: string): Promise<string | null> {
  const r = await request.post(`${API}/workspaces/${ws}/read`, { data: { path } });
  return r.ok() ? (await r.json()).data.content : null;
}

function watch(page: Page) {
  const problems: string[] = [];
  page.on('pageerror', e => problems.push(`pageerror: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('Failed to load resource')) problems.push(`console: ${m.text()}`); });
  page.on('response', r => { if (r.url().startsWith(API) && r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  return problems;
}

async function openStudio(page: Page, ws: string) {
  await page.addInitScript(w => {
    if (window.top !== window) return;   // not inside the sandboxed preview frame (no storage there)
    if (!sessionStorage.getItem('seeded')) {
      localStorage.setItem('vexa-studio:layout:v1', JSON.stringify({ workspaceId: w, activity: 'explorer', rightVisible: true, panelVisible: true }));
      sessionStorage.setItem('seeded', '1');
    }
  }, ws);
  await page.goto('/');
  await expect(page.getByTestId('explorer-tree')).toBeVisible();
}

test('explorer shows the real workspace; files open in Monaco, edit and save to the backend', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  // the tree is the backend listing, not a frontend fixture
  const listing = (await (await request.get(`${API}/workspaces/${ws}/files`)).json()).data as { path: string }[];
  for (const f of listing) {
    const top = f.path.split('/')[0];
    await expect(page.locator(`[data-testid=explorer-item][data-path="${top}"]`)).toBeVisible();
  }
  await page.locator('[data-path="src"]').click();
  await page.locator('[data-path="src/calculator.py"]').dblclick();
  await expect(page.locator('[data-tab="file:src/calculator.py"]')).toBeVisible();
  const editor = page.locator('[data-testid=monaco-host] .monaco-editor');
  await expect(editor).toBeVisible({ timeout: 60_000 });
  await expect(editor).toContainText('return a + b');
  await expect(editor.locator('.minimap')).toBeVisible(); // default on (Settings test turns it off)

  // edit: unsaved indicator, then ⌘S persists through the API
  await editor.click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.keyboard.type('\n\ndef sub(a, b):\n    return a - b\n');
  await expect(page.locator('[data-tab="file:src/calculator.py"] .close.dirty')).toBeVisible();
  await page.keyboard.press('ControlOrMeta+s');
  await expect(page.locator('[data-tab="file:src/calculator.py"] .close.dirty')).toHaveCount(0);
  await expect.poll(() => readFile(request, ws, 'src/calculator.py')).toContain('def sub(a, b):');

  // command palette opens files by name
  await page.keyboard.press('ControlOrMeta+p');
  await page.getByTestId('command-palette').locator('input').fill('test_calc');
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-tab="file:tests/test_calculator.py"]')).toBeVisible();
  expect(problems).toEqual([]);
});

test('explorer creates, renames and deletes files through the backend', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('explorer-new-file').click();
  await page.keyboard.type('notes.md');
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-path="notes.md"]')).toBeVisible();
  await expect.poll(() => readFile(request, ws, 'notes.md')).toBe('');

  await page.locator('[data-path="notes.md"]').click({ button: 'right' });
  await page.getByRole('menuitem', { name: /Rename/ }).click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.type('README-2.md');
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-path="README-2.md"]')).toBeVisible();
  expect(await readFile(request, ws, 'notes.md')).toBeNull();
  expect(await readFile(request, ws, 'README-2.md')).toBe('');

  await page.locator('[data-path="README-2.md"]').click({ button: 'right' });
  await page.getByRole('menuitem', { name: /Delete/ }).click();
  await page.getByTestId('confirm-ok').click();
  await expect(page.locator('[data-path="README-2.md"]')).toHaveCount(0);
  expect(await readFile(request, ws, 'README-2.md')).toBeNull();
  expect(problems).toEqual([]);
});

test('a hierarchical run is watched live: agents, workflow, timeline, panel and trace match the backend', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('requirement').fill('Add a subtract function to src/calculator.py with a test');
  await page.getByTestId('architecture-select').selectOption('hierarchical');
  await page.getByTestId('execution-mode').selectOption('mock');
  await page.getByTestId('run-button').click();

  const view = page.getByTestId('run-view');
  await expect(view).toBeVisible();
  await expect(view.getByText('MOCK · scripted agents')).toBeVisible();
  await expect(page.getByTestId('run-status')).toHaveText(/success|partial|failed/i, { timeout: 150_000 });

  const runId = (await view.getByText(/^run [0-9a-f-]{36}$/).innerText()).replace('run ', '');
  const stored = await (await request.get(`${API}/agent-runs/${runId}`)).json();
  expect(stored.architecture).toBe('hierarchical');
  expect(stored.workspace_id).toBe(ws);

  // every dispatched agent has a card in the backend-reported final state, and the Manager is shown
  const dispatched = new Set<string>(stored.result.coordination_log.filter((c: any) => c.kind === 'dispatch').map((c: any) => c.target));
  expect(dispatched.size).toBeGreaterThan(3);
  await expect(page.locator('[data-testid=agent-card][data-agent=Manager]')).toBeVisible();
  for (const a of dispatched) {
    await expect(page.locator(`[data-testid=agent-card][data-agent="${a}"]`)).toHaveAttribute('data-status', /completed|failed/);
  }
  // the workflow is the dispatch log, in order
  const nodes = await page.getByTestId('workflow').locator('.rv-node').count();
  expect(nodes).toBe(stored.result.coordination_log.filter((c: any) => c.kind === 'dispatch').length);
  // a manager review sent work back (rule policy) — visible as a review entry
  await expect(view.getByText(/revise/).first()).toBeVisible();

  // agent detail: tool calls are the recorded spans
  await page.locator('[data-testid=agent-card][data-agent=Tester]').click();
  await expect(page.getByTestId('agent-detail')).toContainText('run_tests');

  // timeline + bottom panel
  await expect(page.getByTestId('timeline')).toContainText('Tester');
  await page.getByTestId('panel-tab-output').click();
  await expect(page.getByTestId('output-log')).toContainText('Verifier');
  await page.getByTestId('panel-tab-trace').click();
  const spanRows = await page.getByTestId('trace-span').count();
  expect(spanRows).toBe(stored.result.trace.spans.length);
  await page.getByTestId('panel-tab-tests').click();
  await expect(page.getByTestId('bottom-panel')).toContainText(/passed|No tests/);

  // the run is listed in Sessions
  await expect(page.getByTestId('session-row').first()).toContainText('subtract');
  expect(problems).toEqual([]);
});

test('terminal runs pytest in the sandbox and refuses anything else; monitoring mirrors /system/status', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('panel-tab-terminal').click();
  const input = page.getByTestId('terminal-input');
  await input.fill('rm -rf /');
  await input.press('Enter');
  await expect(page.getByTestId('terminal')).toContainText("'rm' is not available");
  await input.fill('pytest');
  await input.press('Enter');
  await expect(page.getByTestId('terminal')).toContainText('1 passed', { timeout: 60_000 });
  await expect(page.getByTestId('terminal')).toContainText('exit code 0');

  const sys = await (await request.get(`${API}/system/status`)).json();
  await page.getByTestId('activity-monitoring').click();
  await expect(page.getByTestId('monitoring')).toContainText(`${sys.database.runs} runs`);
  await expect(page.getByTestId('monitoring')).toContainText(sys.a2a.status.replace('_', ' '));
  await expect(page.getByTestId('status-backend')).toContainText('VEXA backend');
  expect(problems).toEqual([]);
});

test('agent anatomy: profile, internal architecture linked to real source, tools from the policy', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);
  await page.getByTestId('activity-agents').click();
  await page.getByTestId('agent-row').filter({ hasText: 'Coder' }).click();
  const prof = await (await request.get(`${API}/agents/Coder`)).json();
  await expect(page.getByTestId('agent-page')).toContainText(prof.role);
  const stages = page.getByTestId('anatomy').locator(':scope > div');
  await expect(stages).toHaveCount(prof.anatomy.length);
  await expect(page.getByTestId('agent-tools').locator('tbody tr')).toHaveCount(prof.tools.length);
  // a stage opens its implementation, read-only, from the real file
  await page.getByTestId('anatomy').getByRole('button', { name: /crew\.py:\d+/ }).first().click();
  await expect(page.getByTestId('source-page')).toContainText('read-only');
  await expect(page.locator('[data-testid=source-page] .monaco-editor')).toContainText('class SoftwareEngineeringCrew', { timeout: 30_000 });
  // prompt viewer switches variants
  await page.locator('[data-tab="agent:Coder"]').click();
  await page.getByTestId('prompt-viewer').locator('select').selectOption('react');
  await expect(page.getByTestId('prompt-viewer').locator('pre')).toContainText(/Observation|ReAct|Thought/i);
  expect(problems).toEqual([]);
});

test('evaluation, benchmarks, guardrails and extensions show backend-computed data', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('activity-evaluation').click();
  await page.getByTestId('nav-criteria').click();
  const ev = await (await request.get(`${API}/evaluation/agents`)).json();
  await page.getByTestId('eval-agent-Verifier').click();
  await expect(page.getByTestId('criterion')).toHaveCount(ev.criteria.filter((c: any) => c.agent === 'Verifier').length);
  const notEval = ev.criteria.filter((c: any) => c.agent === 'Tester' && c.status === 'not_evaluated').length;
  await page.getByTestId('eval-agent-Tester').click();
  await expect(page.locator('[data-testid=criterion][data-status=not_evaluated]')).toHaveCount(notEval);

  await page.getByTestId('activity-benchmarks').click();
  const ov = await (await request.get(`${API}/benchmarks/overview`)).json();
  await expect(page.getByTestId('case-row')).toHaveCount(ov.total_cases);
  await page.getByTestId('open-benchmarks').click();
  await expect(page.getByTestId('cases-table').locator('tbody tr')).toHaveCount(ov.total_cases);
  await expect(page.getByTestId('compare-table')).toContainText('task success');
  await page.getByTestId('case-row').first().click();
  await expect(page.getByTestId('case-page')).toContainText('Reference solution');

  await page.getByTestId('activity-monitoring').click();
  await page.getByTestId('open-guardrails').click();
  await expect(page.getByTestId('guardrail-card')).toHaveCount(10);
  await page.locator('[data-testid=guardrail-card][data-id=G6]').click();
  await expect(page.getByTestId('guardrails-page')).toContainText('Heuristic detection');

  await page.getByTestId('activity-extensions').click();
  const ext = await (await request.get(`${API}/extensions`)).json();
  await expect(page.getByTestId('extension-row')).toHaveCount(ext.extensions.length);
  await page.getByTestId('extension-row').filter({ hasText: 'HTTP API' }).click();
  await expect(page.getByTestId('extension-page')).toContainText('/agents/{name}');
  await expect(page.getByTestId('integration-map')).toBeVisible();
  expect(problems).toEqual([]);
});

test('run tab: waterfall explorer, replay of recorded events, comparison, global search', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);
  for (const arch of ['sequential', 'blackboard']) {
    await page.getByTestId('requirement').fill(`Add a subtract function (${arch})`);
    await page.getByTestId('architecture-select').selectOption(arch);
    await page.getByTestId('run-button').click();
    await expect(page.getByTestId('run-status')).toHaveText(/success|partial|failed/i, { timeout: 150_000 });
  }
  await page.getByTestId('run-tab-waterfall').click();
  await expect(page.getByTestId('trace-span').first()).toBeVisible();
  const all = await page.getByTestId('trace-span').count();
  await page.locator('select').filter({ hasText: 'all kinds' }).selectOption('tool');
  await expect(page.getByTestId('trace-span')).not.toHaveCount(all);
  const tools = await page.getByTestId('trace-span').count();
  expect(tools).toBeGreaterThan(0);
  expect(tools).toBeLessThan(all);

  await page.getByTestId('run-tab-live').click();
  await page.getByTestId('replay-start').click();
  await expect(page.getByTestId('replay-bar')).toContainText('REPLAY of recorded events');
  await page.getByRole('button', { name: 'Exit replay' }).click();

  await page.getByTestId('compare-select').selectOption({ index: 1 });
  await expect(page.getByTestId('compare-page')).toContainText('blackboard');
  await expect(page.getByTestId('compare-page')).toContainText('sequential');

  await page.keyboard.press('ControlOrMeta+p');
  await page.getByTestId('command-palette').locator('input').fill('#subtract');
  await expect(page.getByTestId('command-palette')).toContainText('run: Add a subtract function');
  await page.keyboard.press('Escape');
  expect(problems).toEqual([]);
});

test('settings: editor prefs apply to Monaco, backend config mirrors /system/status; run outcomes land in notifications', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('activity-settings').click();
  const sys = await (await request.get(`${API}/system/status`)).json();
  const backend = page.getByTestId('settings-backend');
  await expect(backend).toContainText(sys.sandbox.backend);
  await expect(backend).toContainText(sys.backend.version);
  await page.getByTestId('setting-font-size').fill('17');
  await page.getByTestId('setting-minimap').uncheck();

  await page.getByTestId('activity-explorer').click();
  await page.locator('[data-path="src"]').click();
  await page.locator('[data-path="src/calculator.py"]').dblclick();
  const editor = page.locator('[data-testid=monaco-host] .monaco-editor');
  await expect(editor).toContainText('return a + b', { timeout: 60_000 });
  await expect(editor.locator('.view-lines')).toHaveCSS('font-size', '17px');
  await expect(editor.locator('.minimap')).toBeHidden();

  // a finished run produces a notification that matches the stored status and links back to the run
  await page.getByTestId('requirement').fill('Add a subtract function to src/calculator.py with a test');
  await page.getByTestId('execution-mode').selectOption('mock');
  await page.getByTestId('run-button').click();
  await expect(page.getByTestId('run-status')).toHaveText(/success|partial|failed/i, { timeout: 150_000 });
  const runId = (await page.getByTestId('run-view').getByText(/^run [0-9a-f-]{36}$/).innerText()).replace('run ', '');
  const stored = await (await request.get(`${API}/agent-runs/${runId}`)).json();
  await expect(page.getByTestId('bell-unread')).toBeVisible();
  await page.getByTestId('status-bell').click();
  await expect(page.getByTestId('notifications')).toContainText(runId.slice(0, 8));
  await expect(page.getByTestId('notifications')).toContainText(stored.status === 'failed' ? 'failed' : `finished: ${stored.status}`);
  expect(problems).toEqual([]);
});

test('live preview: serves the workspace page, reloads after a save; any workspace can be picked', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await request.post(`${API}/workspaces/${ws}/write`, { data: { path: 'index.html', content: '<h1 id="t">Hello from VEXA</h1>\n' } });
  await openStudio(page, ws);

  await page.getByTestId('right-tab-preview').click();
  const frame = page.frameLocator('[data-testid=preview-frame]');
  await expect(frame.locator('#t')).toHaveText('Hello from VEXA');

  // edit in Monaco + save -> the preview reloads by itself and shows the new content
  await page.locator('[data-path="index.html"]').dblclick();
  const editor = page.locator('[data-testid=monaco-host] .monaco-editor');
  await expect(editor).toContainText('Hello from VEXA', { timeout: 60_000 });
  await editor.click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.keyboard.type('Saved and reloaded');
  await page.keyboard.press('ControlOrMeta+s');
  await expect.poll(() => readFile(request, ws, 'index.html')).toContain('Saved and reloaded');
  await expect(frame.locator('body')).toContainText('Saved and reloaded');

  // a workspace without a web page says so instead of showing a 404
  const other = await makeWorkspace(request);
  await page.reload();
  await page.getByTestId('right-tab-preview').click();
  await page.getByTestId('preview-workspace').selectOption(other);
  await expect(page.getByTestId('preview-unavailable')).toBeVisible();
  // the composer stays available next to the preview
  await expect(page.getByTestId('requirement')).toBeVisible();
  expect(problems).toEqual([]);
});

test('reports mode: full-width reports with an index of every evaluation; IDE work switches back', async ({ page, request }) => {
  const problems = watch(page);
  const ws = await makeWorkspace(request);
  await openStudio(page, ws);

  await page.getByTestId('mode-reports').click();
  await expect(page.getByTestId('reports-mode')).toBeVisible();
  await expect(page.getByTestId('explorer-tree')).toHaveCount(0);           // IDE chrome is gone
  await expect(page.getByTestId('dashboard-page')).toBeVisible();

  // the index's counts are the API's
  const cases = await (await request.get(`${API}/benchmarks/cases`)).json();
  await expect(page.getByTestId('nav-benchmarks')).toContainText(`${cases.length} cases`);
  const ev = await (await request.get(`${API}/evaluation/agents`)).json();
  const coder = ev.criteria.filter((c: any) => c.agent === 'Coder');
  await expect(page.getByTestId('nav-agent-Coder')).toContainText(`${coder.length} criteria`);

  // per-agent evaluation and anatomy open as report tabs
  await page.getByTestId('nav-agent-Coder').click();
  await expect(page.getByTestId('criterion')).toHaveCount(coder.length);
  await page.getByTestId('nav-agent-Coder').getByTitle(/anatomy/).click();
  await expect(page.getByTestId('agent-page')).toBeVisible();
  await page.getByTestId('nav-guardrails').click();
  await page.getByTestId('nav-experiments').click();

  // file tabs belong to the IDE: they are hidden in Reports mode and come back in IDE mode
  await page.getByTestId('mode-ide').click();
  await expect(page.getByTestId('explorer-tree')).toBeVisible();
  await page.getByTestId('activity-evaluation').click();
  await expect(page.getByTestId('reports-nav')).toBeVisible();              // same index in the IDE sidebar
  await page.getByTestId('activity-explorer').click();
  await page.locator('[data-path="src"]').click();
  await page.locator('[data-path="src/calculator.py"]').dblclick();
  await page.getByTestId('mode-reports').click();
  await expect(page.locator('[data-tab="file:src/calculator.py"]')).toHaveCount(0);
  await page.getByTestId('mode-ide').click();
  await expect(page.locator('[data-tab="file:src/calculator.py"]')).toBeVisible();
  expect(problems).toEqual([]);
});
