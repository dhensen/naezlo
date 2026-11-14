import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import { APP_NAME } from '../config'
import { ADA, apiError, config, json, mockApi, NOT_SIGNED_IN } from '../test/api'
import { renderApp } from '../test/render'

function location() {
  return screen.getByTestId('location').textContent
}

test('a signed-out visitor is sent to the login page with the path to return to', async () => {
  mockApi({ 'GET /api/me': NOT_SIGNED_IN, 'GET /api/config': config() })

  renderApp('/projects/42?tab=lists#top')

  await waitFor(() =>
    expect(location()).toBe(`/login?next=${encodeURIComponent('/projects/42?tab=lists#top')}`),
  )
  expect(await screen.findByRole('heading', { name: `Sign in to ${APP_NAME}` })).toBeInTheDocument()
})

test('the start page needs no next parameter', async () => {
  mockApi({ 'GET /api/me': NOT_SIGNED_IN, 'GET /api/config': config() })

  renderApp('/')

  await waitFor(() => expect(location()).toBe('/login'))
})

test('a signed-in user gets the page', async () => {
  mockApi({ 'GET /api/me': json(ADA) })

  renderApp('/')

  expect(await screen.findByRole('heading', { level: 1, name: APP_NAME })).toBeInTheDocument()
  expect(location()).toBe('/')
})

test('unknown paths are guarded too', async () => {
  const routes = { 'GET /api/me': NOT_SIGNED_IN, 'GET /api/config': config() }
  mockApi(routes)

  renderApp('/nowhere')

  await waitFor(() => expect(location()).toBe('/login?next=%2Fnowhere'))
})

test('a failing /api/me shows the error, not the login page, and can be retried', async () => {
  const routes = { 'GET /api/me': apiError(500, 'internal', 'The database is away') }
  mockApi(routes)
  renderApp('/')

  expect(await screen.findByRole('alert')).toHaveTextContent('The database is away')
  expect(location()).toBe('/')

  routes['GET /api/me'] = json(ADA)
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { level: 1, name: APP_NAME })).toBeInTheDocument()
})

test('a session that ends while the app is open leads to the login page', async () => {
  const routes = { 'GET /api/me': json(ADA), 'GET /api/config': config() }
  mockApi(routes)
  renderApp('/')
  await screen.findByRole('heading', { level: 1, name: APP_NAME })

  // The query refetches when the window gets the focus again.
  routes['GET /api/me'] = NOT_SIGNED_IN()
  window.dispatchEvent(new Event('visibilitychange'))

  await waitFor(() => expect(location()).toBe('/login'))
})
