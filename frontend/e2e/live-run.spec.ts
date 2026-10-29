import { expect, test } from '@playwright/test';

// Displays a stored live-provider run (VEXA_LIVE_RUN_ID) exactly as a user would open it.
const RUN = process.env.VEXA_LIVE_RUN_ID;
test.skip(!RUN, 'set VEXA_LIVE_RUN_ID to a run produced with a real provider');

test('a real CrewAI + ADK run is visualised from stored data', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.getByTestId('recent-runs').selectOption(RUN!);
  await expect(page.getByTestId('run-status')).toHaveText(/SUCCESS|PARTIAL|FAILED/);
  await expect(page.getByTestId('run-status')).not.toContainText('MOCK');
  await expect(page.getByTestId('header-mode')).toHaveText('REAL');  // the opened run, not the form
  await page.getByTestId('tab-trace').click();
  await expect(page.getByTestId('trace-sources')).toContainText('google-adk');
  await expect(page.locator('[data-testid="trace-span"][data-source="google-adk"][data-kind="llm"]').first()).toBeVisible();
  await expect(page.locator('tr', { hasText: 'execute_tool' }).first()).toHaveCount(0);  // ADK tools named properly
  await expect(page.locator('td', { hasText: 'adk (in-process)' }).first()).toBeVisible();
  await page.screenshot({ path: 'test-results/live-trace.png', fullPage: true });
  await page.getByTestId('tab-coordination').click();
  await expect(page.getByText(/manager_llm|Manager/).first()).toBeVisible();
  await page.getByTestId('tab-report').click();
  await expect(page.getByText(/LLM Manager \(real CrewAI agent\)/).first()).toBeVisible();
  await page.screenshot({ path: 'test-results/live-report.png', fullPage: true });
  expect(errors).toEqual([]);
});
