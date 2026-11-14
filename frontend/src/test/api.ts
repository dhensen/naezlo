import { vi } from 'vitest'

import type { AppConfig, Me, Schemas } from '../api/client'

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

export const ACME: Schemas['MyOrganizationOut'] = {
  id: '0190a000-0000-7000-8000-0000000000a1',
  name: 'Acme',
  slug: 'acme',
  role: 'owner',
}

export const BETA: Schemas['MyOrganizationOut'] = {
  id: '0190a000-0000-7000-8000-0000000000a2',
  name: 'Beta Works',
  slug: 'beta-works',
  role: 'member',
}

/** Ada as a member of Acme and Beta Works. Mock `GET /api/orgs/<id>/projects` for the sidebar. */
export const ADA_IN_ORGS: Me = { ...ADA, organizations: [ACME, BETA] }

/** A project as the API returns it. */
export function project(
  organization: Schemas['MyOrganizationOut'],
  id: string,
  name: string,
  overrides: Partial<Schemas['ProjectOut']> = {},
): Schemas['ProjectOut'] {
  return {
    id,
    organization_id: organization.id,
    name,
    description: null,
    created_by: ADA.user.id,
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T10:00:00Z',
    role: 'admin',
    default_list_mode: 'human_only',
    ...overrides,
  }
}

/** A list as the API returns it. */
export function todoList(
  of: Schemas['ProjectOut'],
  id: string,
  name: string,
  overrides: Partial<Schemas['ListOut']> = {},
): Schemas['ListOut'] {
  return {
    id,
    project_id: of.id,
    project_name: of.name,
    name,
    description: null,
    mode: 'human_only',
    position: 1,
    open_item_count: 0,
    role: 'admin',
    actions: ['read', 'change_items', 'edit_list', 'administer'],
    created_by: ADA.user.id,
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T10:00:00Z',
    ...overrides,
  }
}

export function config(overrides: Partial<AppConfig> = {}): Response {
  return json({ dev_login_enabled: false, google_login_enabled: false, ...overrides })
}
