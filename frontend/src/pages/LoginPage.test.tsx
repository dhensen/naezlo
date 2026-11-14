import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'

import { leaveTo } from '../auth/next'
import { APP_NAME } from '../config'
import { ADA, apiError, config, json, mockApi, NOT_SIGNED_IN } from '../test/api'
import { renderApp } from '../test/render'

vi.mock(import('../auth/next'), async (importOriginal) => ({
  ...(await importOriginal()),
  leaveTo: vi.fn(),
}))

function location() {
  return screen.getByTestId('location').textContent
}

function signedOut(overrides: Parameters<typeof config>[0]) {
  return { 'GET /api/me': NOT_SIGNED_IN, 'GET /api/config': config(overrides) }
}

test('with Google login enabled there is a "Sign in with Google" button and no form', async () => {
  mockApi(signedOut({ google_login_enabled: true }))

  renderApp('/login')

  const google = await screen.findByRole('link', { name: 'Sign in with Google' })
  expect(google).toHaveAttribute('href', '/api/auth/google/login')
  expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
})

test('the Google button passes the path to return to', async () => {
  mockApi(signedOut({ google_login_enabled: true }))

  renderApp('/login?next=%2Fprojects%2F42%3Ftab%3Dlists')

  expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toHaveAttribute(
    'href',
    '/api/auth/google/login?next=%2Fprojects%2F42%3Ftab%3Dlists',
  )
})

test('with dev-login enabled there is an email and name form and no Google button', async () => {
  mockApi(signedOut({ dev_login_enabled: true }))

  renderApp('/login')

  expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Sign in with Google' })).not.toBeInTheDocument()
})

test('with both enabled the page shows both', async () => {
  mockApi(signedOut({ dev_login_enabled: true, google_login_enabled: true }))

  renderApp('/login')

  expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toBeInTheDocument()
  expect(screen.getByLabelText('Email')).toBeInTheDocument()
})

test('with neither enabled the page says so', async () => {
  mockApi(signedOut({}))

  renderApp('/login')

  expect(await screen.findByText(/Signing in is not set up/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
})

test('a dev-login signs in and returns to the path the visitor came for', async () => {
  const routes: Parameters<typeof mockApi>[0] = {
    ...signedOut({ dev_login_enabled: true }),
    'POST /api/auth/dev-login': async (request) => {
      expect(await request.json()).toEqual({ email: 'ada@example.com', name: 'Ada Lovelace' })
      // From here on the browser has the session cookie.
      routes['GET /api/me'] = json(ADA)
      return json(ADA)
    },
  }
  const fetchMock = mockApi(routes)
  renderApp('/somewhere?x=1')
  await waitFor(() => expect(location()).toBe('/login?next=%2Fsomewhere%3Fx%3D1'))

  await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.com')
  await userEvent.type(screen.getByLabelText('Name'), 'Ada Lovelace')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  await waitFor(() => expect(location()).toBe('/somewhere?x=1'))
  expect(await screen.findByRole('button', { name: 'Account: Ada Lovelace' })).toBeInTheDocument()
  const posts = fetchMock.mock.calls.filter(([request]) => request.method === 'POST')
  expect(posts).toHaveLength(1)
})

test('a failed dev-login shows the API error and stays on the page', async () => {
  mockApi({
    ...signedOut({ dev_login_enabled: true }),
    'POST /api/auth/dev-login': json(
      { detail: [{ loc: ['body', 'email'], msg: 'value is not a valid email address' }] },
      422,
    ),
  })
  renderApp('/login')

  await userEvent.type(await screen.findByLabelText('Email'), 'ada@example')
  await userEvent.type(screen.getByLabelText('Name'), 'Ada')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('value is not a valid email address')
  expect(location()).toBe('/login')
})

test('an error code from the Google sign-in is explained', async () => {
  mockApi(signedOut({ google_login_enabled: true }))

  renderApp('/login?error=email_not_verified')

  expect(await screen.findByRole('alert')).toHaveTextContent('no verified email address')
})

test('a signed-in visitor of the login page goes on to the app', async () => {
  mockApi({ 'GET /api/me': json(ADA), 'GET /api/config': config() })

  renderApp('/login')

  await waitFor(() => expect(location()).toBe('/'))
  expect(await screen.findByRole('heading', { level: 1, name: APP_NAME })).toBeInTheDocument()
})

test('a next parameter that points to another site is ignored', async () => {
  mockApi({ 'GET /api/me': json(ADA), 'GET /api/config': config() })

  renderApp('/login?next=%2F%2Fevil.example%2Fx')

  await waitFor(() => expect(location()).toBe('/'))
  expect(leaveTo).not.toHaveBeenCalled()
})

test('a next path of the backend (an MCP authorization) is opened as a full page load', async () => {
  mockApi({ 'GET /api/me': json(ADA), 'GET /api/config': config() })
  const next = '/authorize?client_id=abc&state=xyz'

  renderApp(`/login?next=${encodeURIComponent(next)}`)

  await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(next))
})

test('a failing /api/config is shown', async () => {
  mockApi({
    'GET /api/me': NOT_SIGNED_IN,
    'GET /api/config': apiError(503, 'unavailable', 'Come back later'),
  })

  renderApp('/login')

  expect(await screen.findByRole('alert')).toHaveTextContent('Come back later')
})
