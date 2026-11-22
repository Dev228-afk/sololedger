import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:5201',
    headless: true,
    viewport: { width: 1440, height: 900 },
  },
  reporter: [
    ['list'],
    ['json', { outputFile: '../evidence/ux/playwright-report.json' }],
  ],
});

