import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'

import type { Schemas } from '../api/client'
import { leaveTo } from '../auth/next'
import { APP_NAME } from '../config'
import { ACME, ADA, ADA_IN_ORGS, apiError, BETA, config, json, mockApi, NOT_SIGNED_IN } from '../test/api'
import { renderApp } from '../test/render'

vi.mock(import('../auth/next'), async (importOriginal) => ({
  ...(await importOriginal()),
  leaveTo: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(leaveTo).mockClear()
})

const REQUEST_ID = '0190a000-0000-7000-8000-0000000000c1'
const PAGE = `/oauth/consent?request=${REQUEST_ID}`
const API = `/api/oauth/requests/${REQUEST_ID}`
const CALLBACK = 'http://localhost:33418/callback'

function agent(id: string, name: string, organization: { id: string; name: string }, description: string | null = null) {
  return { id, name, description, organization: { id: organization.id, name: organization.name } }
}

const CLAUDE = agent('0190a000-0000-7000-8000-0000000000f1', 'Claude', ACME, 'Keeps the backlog tidy.')
const CODEX = agent('0190a000-0000-7000-8000-0000000000f2', 'Codex', ACME)
const SCOUT = agent('0190a000-0000-7000-8000-0000000000f3', 'Scout', BETA)

function pending(overrides: Partial<Schemas['AuthorizationRequestOut']> = {}): Response {
  return json({
    id: REQUEST_ID,
    client_name: 'Claude Code',
    redirect_host: 'localhost:33418',
    scope: 'mcp',
    expires_at: '2026-11-15T10:10:00Z',
    agents: [CLAUDE, CODEX, SCOUT],
    ...overrides,
  })
}

/** A route that answers with `body` and keeps the JSON bodies it was sent. */
function recorded(body: unknown) {
  const bodies: unknown[] = []
  const route = async (request: Request) => {
    const text = await request.text()
    bodies.push(text === '' ? null : JSON.parse(text))
    return json(body)
  }
  return { bodies, route }
}

function location() {
  return screen.getByTestId('location').textContent
}

test('shows the client, the redirect host and the agents grouped by organization', async () => {
  mockApi({ 'GET /api/me': json(ADA_IN_ORGS), [`GET ${API}`]: pending() })

  renderApp(PAGE)

  expect(
    await screen.findByRole('heading', { level: 1, name: `Claude Code wants to access ${APP_NAME}` }),
  ).toBeInTheDocument()
  expect(screen.getByText('localhost:33418')).toBeInTheDocument()
  expect(screen.getByText(ADA.user.email)).toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('an application on this computer')

  const acme = screen.getByRole('group', { name: 'Acme' })
  expect(within(acme).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([
    CLAUDE.id,
    CODEX.id,
  ])
  expect(within(acme).getByRole('radio', { name: 'Claude' })).toHaveAccessibleDescription('Keeps the backlog tidy.')
  expect(within(screen.getByRole('group', { name: 'Beta Works' })).getByRole('radio', { name: 'Scout' })).not.toBeChecked()

  // Nothing is chosen for the user when there is more than one agent.
  expect(screen.getByRole('button', { name: 'Allow' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Deny' })).toBeEnabled()
  // The page stands alone: no navigation of the app around it.
  expect(screen.queryByRole('banner')).not.toBeInTheDocument()
})

test('"Allow" approves with the chosen agent and sends the browser to the returned URL', async () => {
  const approve = recorded({ redirect_url: `${CALLBACK}?code=abc&state=xyz` })
  mockApi({ 'GET /api/me': json(ADA_IN_ORGS), [`GET ${API}`]: pending(), [`POST ${API}/approve`]: approve.route })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('radio', { name: 'Scout' }))
  await userEvent.click(screen.getByRole('button', { name: 'Allow' }))

  await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${CALLBACK}?code=abc&state=xyz`))
  expect(approve.bodies).toEqual([{ agent_id: SCOUT.id }])
  expect(screen.getByText('Returning to the application…')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Allow' })).not.toBeInTheDocument()
})

test('a single agent is chosen already', async () => {
  const approve = recorded({ redirect_url: `${CALLBACK}?code=abc` })
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending({ agents: [CLAUDE] }),
    [`POST ${API}/approve`]: approve.route,
  })
  renderApp(PAGE)

  expect(await screen.findByRole('radio', { name: 'Claude' })).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Allow' }))

  await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${CALLBACK}?code=abc`))
  expect(approve.bodies).toEqual([{ agent_id: CLAUDE.id }])
})

test('"Deny" denies and sends the browser to the returned URL', async () => {
  const deny = recorded({ redirect_url: `${CALLBACK}?error=access_denied&state=xyz` })
  mockApi({ 'GET /api/me': json(ADA_IN_ORGS), [`GET ${API}`]: pending(), [`POST ${API}/deny`]: deny.route })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Deny' }))

  await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${CALLBACK}?error=access_denied&state=xyz`))
  expect(deny.bodies).toEqual([null])
})

test('a client without a name and a redirect to another site', async () => {
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending({ client_name: null, redirect_host: 'tools.example.com' }),
  })

  renderApp(PAGE)

  expect(
    await screen.findByRole('heading', { level: 1, name: `An application wants to access ${APP_NAME}` }),
  ).toBeInTheDocument()
  expect(screen.getByText('tools.example.com')).toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('Check that this address belongs to the application')
})

test('without an eligible agent the page says to create one and links to the agents pages', async () => {
  const deny = recorded({ redirect_url: `${CALLBACK}?error=access_denied` })
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending({ agents: [] }),
    [`POST ${API}/deny`]: deny.route,
  })

  renderApp(PAGE)

  expect(await screen.findByText('Create an agent first.')).toBeInTheDocument()
  // Ada is the owner of Acme and only a member of Beta Works.
  const links = screen.getAllByRole('link')
  expect(links.map((link) => link.textContent)).toEqual(['Agents of Acme'])
  expect(links[0]).toHaveAttribute('href', '/o/acme/agents')
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Allow' })).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Deny' }))
  await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${CALLBACK}?error=access_denied`))
})

test('someone who manages no organization is told to ask an owner or admin', async () => {
  mockApi({
    'GET /api/me': json({ ...ADA, organizations: [BETA] }),
    [`GET ${API}`]: pending({ agents: [] }),
  })

  renderApp(PAGE)

  expect(await screen.findByText(/Only the owners and admins of an organization/)).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

test('an expired or unknown request shows an error and goes nowhere', async () => {
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: apiError(404, 'not_found', 'Authorization request not found'),
  })

  renderApp(PAGE)

  expect(await screen.findByRole('alert')).toHaveTextContent('It may have expired or been answered already')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(leaveTo).not.toHaveBeenCalled()
  expect(location()).toBe(PAGE)
})

test('an id that is not one and a missing id show the same error', async () => {
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    'GET /api/oauth/requests/nonsense': json({ detail: [{ msg: 'Input should be a valid UUID' }] }, 422),
  })

  const { unmount } = renderApp('/oauth/consent?request=nonsense')
  expect(await screen.findByRole('alert')).toHaveTextContent('This authorization request was not found')
  unmount()

  renderApp('/oauth/consent')
  expect(await screen.findByRole('alert')).toHaveTextContent('This authorization request was not found')
  expect(leaveTo).not.toHaveBeenCalled()
})

test('a request that expires before the answer shows the error without a redirect', async () => {
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending({ agents: [CLAUDE] }),
    [`POST ${API}/approve`]: apiError(404, 'not_found', 'Authorization request not found'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Allow' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('It may have expired or been answered already')
  expect(leaveTo).not.toHaveBeenCalled()
})

test('an agent the user may not connect shows the backend message', async () => {
  mockApi({
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending({ agents: [CLAUDE] }),
    [`POST ${API}/approve`]: apiError(403, 'forbidden', 'You may not authorize this agent'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Allow' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('You may not authorize this agent')
  expect(screen.getByRole('button', { name: 'Allow' })).toBeEnabled()
})

test('a signed-out visitor goes through the login page and comes back to the consent page', async () => {
  const routes: Parameters<typeof mockApi>[0] = {
    'GET /api/me': NOT_SIGNED_IN,
    'GET /api/config': config({ dev_login_enabled: true }),
    'POST /api/auth/dev-login': json(ADA_IN_ORGS),
    [`GET ${API}`]: pending(),
  }
  mockApi(routes)

  renderApp(PAGE)

  await waitFor(() => expect(location()).toBe(`/login?next=${encodeURIComponent(PAGE)}`))
  await userEvent.type(await screen.findByLabelText('Email'), ADA.user.email)
  await userEvent.type(screen.getByLabelText('Name'), ADA.user.name)
  routes['GET /api/me'] = json(ADA_IN_ORGS)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('heading', { level: 1, name: /Claude Code wants to access/ })).toBeInTheDocument()
  expect(location()).toBe(PAGE)
  expect(leaveTo).not.toHaveBeenCalled()
})
