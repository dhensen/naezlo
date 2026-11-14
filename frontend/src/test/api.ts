import { vi } from 'vitest'

import type { AppConfig, Me } from '../api/client'

type Answer = Response | ((request: Request) => Response | Promise<Response>)

/** A JSON response, as the backend would send it. */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** The backend's error shape. */
export function apiError(status: number, code: string, detail: string): Response {
  return json({ detail, code }, status)
}

export const NOT_SIGNED_IN = () => apiError(401, 'not_authenticated', 'Not signed in')

/**
 * Replace `fetch` with a fake backend for one test: `routes` maps `'GET /api/me'` to a
 * response or a function that makes one. `routes` may be changed while the test runs; a
 * request without a route fails the call. Returns the mock, to inspect the requests.
 */
export function mockApi(routes: Record<string, Answer>) {
  const fetchMock = vi.fn(async (request: Request): Promise<Response> => {
    const url = new URL(request.url)
    const answer = routes[`${request.method} ${url.pathname}`]
    if (answer === undefined) {
      throw new Error(`No mocked route for ${request.method} ${url.pathname}`)
    }
    // A Response can be read once, so every call gets its own copy.
    return typeof answer === 'function' ? answer(request) : answer.clone()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export const ADA: Me = {
  user: { id: '0190a000-0000-7000-8000-000000000001', email: 'ada@example.com', name: 'Ada Lovelace', avatar_url: null },
  organizations: [],
}

export function config(overrides: Partial<AppConfig> = {}): Response {
  return json({ dev_login_enabled: false, google_login_enabled: false, ...overrides })
}
