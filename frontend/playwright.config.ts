import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Browser end-to-end tests against the REAL backend (FastAPI + CrewAI + ADK/A2A + MCP + SQLite).
// The backend runs isolated: scratch workspaces and database, and no .env (mock mode needs no keys).
// Uses the locally installed Google Chrome (channel 'chrome'), so no browser download is needed.
const scratch = mkdtempSync(join(tmpdir(), 'vexa-e2e-'));
const API_PORT = 8790;
const UI_PORT = 5180;

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'e2e-results.json' }]],
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    channel: 'chrome',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `cd .. && python -m uvicorn backend.main:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        VEXA_ENV_FILE: '',
        WORKSPACE_ROOT: join(scratch, 'workspaces'),
        VEXA_DB_PATH: join(scratch, 'vexa.sqlite3'),
        VEXA_A2A_EMBEDDED_PORT: '8792',
        CORS_ORIGINS: `http://127.0.0.1:${UI_PORT},http://localhost:${UI_PORT}`,
        SANDBOX_BACKEND: 'local',
      },
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_VEXA_API_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
