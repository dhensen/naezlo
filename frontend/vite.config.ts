import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

import { BACKEND_PATHS } from './src/backendPaths.ts'

// Where the FastAPI backend listens in development.
const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The origin stays localhost:5173 for the browser (the session cookie is first-party);
    // the Host header is not rewritten, absolute URLs come from PUBLIC_BASE_URL.
    proxy: Object.fromEntries(BACKEND_PATHS.map((path) => [path, { target: BACKEND }])),
  },
  test: {
    environment: 'jsdom',
    // Not e2e/*.spec.ts: those are Playwright's (npm run e2e).
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
})
