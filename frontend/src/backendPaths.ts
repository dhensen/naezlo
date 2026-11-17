// Everything the backend serves itself: the JSON API, the OAuth endpoints for MCP clients,
// the well-known metadata documents and the MCP endpoint. All other paths belong to the SPA.
// Keep this in step with `BACKEND_PREFIXES` in src/naezlo/frontend.py.
export const BACKEND_PATHS = [
  '/api',
  '/authorize',
  '/token',
  '/register',
  '/revoke',
  '/.well-known',
  '/mcp',
]

/** Whether `path` (which may carry a query string) is answered by the backend, not by a page. */
export function isBackendPath(path: string): boolean {
  const pathname = path.split(/[?#]/, 1)[0]
  return BACKEND_PATHS.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}
