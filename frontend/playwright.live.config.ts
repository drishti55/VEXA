import { defineConfig } from '@playwright/test';

// Opt-in: view a REAL (live-provider) run in the browser. Start the backend with your .env yourself:
//   CORS_ORIGINS=http://127.0.0.1:5190 python -m uvicorn backend.main:app --port 8800
//   VEXA_LIVE_RUN_ID=<run id> npx playwright test -c playwright.live.config.ts
const API = process.env.VEXA_LIVE_API ?? 'http://127.0.0.1:8800';
export default defineConfig({
  testDir: './e2e',
  testMatch: /live-run\.spec\.ts/,
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:5190', channel: 'chrome', headless: true, screenshot: 'on' },
  webServer: {
    command: 'npx vite --host 127.0.0.1 --port 5190 --strictPort',
    url: 'http://127.0.0.1:5190', reuseExistingServer: false, timeout: 60_000,
    env: { VITE_VEXA_API_URL: API },
  },
});
