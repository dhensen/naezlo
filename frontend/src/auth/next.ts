// The "return here after signing in" path, carried as /login?next=<path>.

/**
 * `value` when it is a path inside this app, otherwise null. The same rule as the backend's
 * `safe_next_path`: `//host` and `/\host` are read as other sites by browsers.
 */
export function safeNextPath(value: string | null): string | null {
  if (value === null || !value.startsWith('/') || value.startsWith('//')) {
    return null
  }
  if (value.includes('\\') || [...value].some((char) => char < ' ' || char === '\x7f')) {
    return null
  }
  return value
}

/** The login page that returns to `path` (a path with its query string and hash). */
export function loginPath(path: string): string {
  return path === '/' ? '/login' : `/login?next=${encodeURIComponent(path)}`
}

/**
 * Leave the single-page app with a full page load: for a path the backend answers, or the URL
 * of another site that the backend gave (the redirect back to an OAuth client).
 */
export function leaveTo(url: string): void {
  window.location.assign(url)
}
