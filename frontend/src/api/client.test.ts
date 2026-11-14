import { expect, test } from 'vitest'

import { isBackendPath } from '../backendPaths'
import { safeNextPath } from '../auth/next'
import { apiError, json, mockApi } from '../test/api'
import { api, ApiError, unwrap } from './client'

test('unwrap gives the body of a successful call', async () => {
  mockApi({ 'GET /api/config': json({ dev_login_enabled: true, google_login_enabled: false }) })

  const config = await unwrap(api.GET('/api/config'))

  expect(config.dev_login_enabled).toBe(true)
})

test('an API error becomes an ApiError with status, code and the detail as message', async () => {
  mockApi({ 'GET /api/me': apiError(403, 'forbidden', 'Not allowed') })

  const error = await unwrap(api.GET('/api/me')).catch((caught: unknown) => caught)

  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({ status: 403, code: 'forbidden', message: 'Not allowed' })
})

test('an error without a JSON body still has a message', async () => {
  mockApi({ 'GET /api/me': new Response('<html>Bad Gateway</html>', { status: 502 }) })

  const error = await unwrap(api.GET('/api/me')).catch((caught: unknown) => caught)

  expect(error).toMatchObject({ status: 502, code: 'http_502' })
  expect((error as ApiError).message).toContain('502')
})

test('no answer at all is a network error', async () => {
  mockApi({})

  const error = await unwrap(api.GET('/api/me')).catch((caught: unknown) => caught)

  expect(error).toMatchObject({ status: 0, code: 'network_error' })
})

test('safeNextPath accepts only paths inside the app', () => {
  expect(safeNextPath('/projects/1?x=1#y')).toBe('/projects/1?x=1#y')
  expect(safeNextPath(null)).toBeNull()
  expect(safeNextPath('https://evil.example')).toBeNull()
  expect(safeNextPath('//evil.example')).toBeNull()
  expect(safeNextPath('/\\evil.example')).toBeNull()
  expect(safeNextPath('/a\nb')).toBeNull()
})

test('isBackendPath matches whole path segments and ignores the query string', () => {
  expect(isBackendPath('/authorize?client_id=1')).toBe(true)
  expect(isBackendPath('/api/me')).toBe(true)
  expect(isBackendPath('/apiary')).toBe(false)
  expect(isBackendPath('/projects?next=/api')).toBe(false)
})
