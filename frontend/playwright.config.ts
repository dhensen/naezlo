import { defineConfig, devices } from '@playwright/test'

// The browser tests run against the real backend, which serves the built frontend itself
// (`python -m naezlo.e2e`: dedicated database, emptied and migrated at every start,
// dev-login on). Port 8765 by default, so a development server on 8000 is left alone.
const PORT = Number(process.env.E2E_PORT ?? 8765)
const BASE_URL = `http://localhost:${PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `uv run python -m naezlo.e2e --port ${PORT}`,
    // The repository root: alembic.ini and frontend/dist are found from there.
    cwd: '..',
    url: `${BASE_URL}/healthz`,
    // Never an already running server: the database must be emptied before the run.
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
