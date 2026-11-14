import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

// Types of the API bodies, by the name the backend gives them (see schema.d.ts, generated
// by `npm run gen:api`).
export type Schemas = components['schemas']
export type Me = Schemas['MeOut']
export type AppConfig = Schemas['ConfigOut']

/**
 * The typed client: `api.GET('/api/me')`, `api.POST('/api/auth/dev-login', { body })`.
 * Paths, parameters and bodies are checked against the generated schema. Wrap a call in
 * `unwrap()` to get the body or an `ApiError`.
 */
export const api = createClient<paths>({
  // An absolute URL, because `Request` outside a browser (the tests) rejects a relative one.
  baseUrl: window.location.origin,
  // Looked up on every call, so a test can replace the global.
  fetch: (request) => globalThis.fetch(request),
})

/** A failed API call. `message` is written for the person and can be shown as it is. */
export class ApiError extends Error {
  /** The HTTP status, or 0 when there was no answer at all. */
  readonly status: number
  /** The backend's machine-readable code (`not_authenticated`, `forbidden`, ...). */
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** The backend's errors are `{detail, code}`; FastAPI's validation errors `{detail: [{msg}]}`. */
function toApiError(status: number, body: unknown): ApiError {
  const detail = isRecord(body) ? body.detail : undefined
  const code = isRecord(body) && typeof body.code === 'string' ? body.code : `http_${status}`
  if (typeof detail === 'string' && detail !== '') {
    return new ApiError(status, code, detail)
  }
  if (Array.isArray(detail) && isRecord(detail[0]) && typeof detail[0].msg === 'string') {
    return new ApiError(status, 'invalid_request', detail[0].msg)
  }
  return new ApiError(status, code, `Something went wrong (error ${status}). Try again later.`)
}

interface ApiResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/** The body of a successful call; every failure becomes a thrown `ApiError`. */
export async function unwrap<T>(call: Promise<ApiResult<T>>): Promise<T> {
  let result: ApiResult<T>
  try {
    result = await call
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.')
  }
  if (!result.response.ok) {
    throw toApiError(result.response.status, result.error)
  }
  return result.data as T
}
