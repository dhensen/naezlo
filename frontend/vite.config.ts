import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Where the FastAPI backend listens in development.
const BACKEND = 'http://localhost:8000'

// Everything the backend serves itself: the JSON API, the OAuth endpoints for MCP clients,
// the well-known metadata documents and the MCP endpoint. All other paths belong to the SPA.
// Keep this in step with `BACKEND_PREFIXES` in src/todolist/frontend.py.
const BACKEND_PATHS = [
  '/api',
  '/authorize',
  '/token',
  '/register',
  '/revoke',
  '/.well-known',
  '/mcp',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The origin stays localhost:5173 for the browser (the session cookie is first-party);
    // the Host header is not rewritten, absolute URLs come from PUBLIC_BASE_URL.
    proxy: Object.fromEntries(BACKEND_PATHS.map((path) => [path, { target: BACKEND }])),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
})
