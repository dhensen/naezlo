import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import { ADA, apiError, config, json, mockApi, NOT_SIGNED_IN } from '../test/api'
import { renderApp } from '../test/render'

function location() {
  return screen.getByTestId('location').textContent
}

async function openMenu() {
  await userEvent.click(await screen.findByRole('button', { name: 'Account: Ada Lovelace' }))
}

test('the user menu shows the name and the email address', async () => {
  mockApi({ 'GET /api/me': json(ADA) })
  renderApp('/')

  expect(screen.queryByText('ada@example.com')).not.toBeInTheDocument()
  await openMenu()

  expect(screen.getByText('ada@example.com')).toBeInTheDocument()
  expect(screen.getAllByText('Ada Lovelace')).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()

  await userEvent.keyboard('{Escape}')
  expect(screen.queryByText('ada@example.com')).not.toBeInTheDocument()
})

test('signing out calls the API and leads to the login page', async () => {
  const routes: Parameters<typeof mockApi>[0] = {
    'GET /api/me': json(ADA),
    'GET /api/config': config({ dev_login_enabled: true }),
    'POST /api/auth/logout': () => {
      routes['GET /api/me'] = NOT_SIGNED_IN
      return new Response(null, { status: 204 })
    },
  }
  const fetchMock = mockApi(routes)
  renderApp('/some/page')
  await openMenu()

  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

  await waitFor(() => expect(location()).toBe('/login'))
  expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([request]) => request.url.endsWith('/api/auth/logout'))).toBe(true)
})

test('a failed sign-out shows the error and keeps the user signed in', async () => {
  mockApi({
    'GET /api/me': json(ADA),
    'POST /api/auth/logout': apiError(500, 'internal', 'Could not sign out'),
  })
  renderApp('/')
  await openMenu()

  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign out')
  expect(location()).toBe('/')
})
