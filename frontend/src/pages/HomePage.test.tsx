import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import { APP_NAME } from '../config'
import { rememberOrganization } from '../orgs/paths'
import { ACME, ADA, ADA_IN_ORGS, BETA, json, mockApi } from '../test/api'
import { renderApp } from '../test/render'

function location() {
  return screen.getByTestId('location').textContent
}

const ROUTES = {
  'GET /api/me': json(ADA_IN_ORGS),
  [`GET /api/orgs/${ACME.id}/projects`]: json([]),
  [`GET /api/orgs/${BETA.id}/projects`]: json([]),
}

test('the start page leads to the first organization', async () => {
  mockApi(ROUTES)

  renderApp('/')

  await waitFor(() => expect(location()).toBe('/o/acme'))
  expect(await screen.findByRole('heading', { level: 1, name: 'Acme' })).toBeInTheDocument()
})

test('the start page leads to the organization that was used last', async () => {
  rememberOrganization('beta-works')
  mockApi(ROUTES)

  renderApp('/')

  await waitFor(() => expect(location()).toBe('/o/beta-works'))
})

test('visiting an organization makes it the one the start page leads to', async () => {
  mockApi(ROUTES)
  renderApp('/o/beta-works')
  await screen.findByRole('heading', { level: 1, name: 'Beta Works' })

  await userEvent.click(screen.getByRole('link', { name: APP_NAME }))

  await waitFor(() => expect(location()).toBe('/o/beta-works'))
})

test('a remembered organization the user is no longer in falls back to the first', async () => {
  rememberOrganization('gone')
  mockApi(ROUTES)

  renderApp('/')

  await waitFor(() => expect(location()).toBe('/o/acme'))
})

test('someone without an organization can create one from the start page', async () => {
  const created = { id: '0190a000-0000-7000-8000-0000000000a9', name: 'First', slug: 'first', role: 'owner' }
  mockApi({
    'GET /api/me': json(ADA),
    'POST /api/orgs': json(created, 201),
    [`GET /api/orgs/${created.id}/projects`]: json([]),
  })
  renderApp('/')

  expect(await screen.findByText('You are not a member of an organization yet.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'New organization' }))
  await userEvent.type(screen.getByLabelText('Name'), 'First')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))

  await waitFor(() => expect(location()).toBe('/o/first'))
})
