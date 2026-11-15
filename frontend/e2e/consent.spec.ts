import { createHash, randomBytes, randomUUID } from 'node:crypto'

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { uniqueUser } from './helpers.ts'
import type { TestUser } from './helpers.ts'

// Where the "client" listens. Nothing does: the browser's request is answered by the test.
const REDIRECT_URI = 'http://127.0.0.1:8799/callback'

interface Flow {
  authorizeUrl: string
  clientId: string
  state: string
  verifier: string
  /** The URL the browser was sent back to, once it got there. */
  callback: Promise<URL>
}

/** What an MCP client does before it opens the browser: register, and make the PKCE pair. */
async function startFlow(page: Page, clientName: string): Promise<Flow> {
  const registration = await page.request.post('/register', {
    data: { client_name: clientName, redirect_uris: [REDIRECT_URI], token_endpoint_auth_method: 'none' },
  })
  expect(registration.status()).toBe(201)
  const { client_id: clientId } = (await registration.json()) as { client_id: string }

  const verifier = randomBytes(32).toString('base64url')
  const state = randomUUID()
  const query = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
    state,
    scope: 'mcp',
  })

  const callback = new Promise<URL>((resolve) => {
    void page.route(`${REDIRECT_URI}*`, async (route) => {
      await route.fulfill({ contentType: 'text/html', body: '<h1>Back in the application</h1>' })
      resolve(new URL(route.request().url()))
    })
  })
  return { authorizeUrl: `/authorize?${query.toString()}`, clientId, state, verifier, callback }
}

/** The dev-login form, as the login page shows it on the way to the consent page. */
async function signInOnLoginPage(page: Page, user: TestUser): Promise<void> {
  await expect(page).toHaveURL(/\/login\?next=%2Fauthorize/)
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Name').fill(user.name)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/oauth\/consent\?request=[0-9a-f-]{36}$/)
}

async function myOrganization(page: Page): Promise<{ id: string; slug: string; name: string }> {
  const me = (await (await page.request.get('/api/me')).json()) as {
    organizations: { id: string; slug: string; name: string }[]
  }
  return me.organizations[0]
}

test('an MCP client is allowed to act as the chosen agent', async ({ page }) => {
  const user = uniqueUser()
  const flow = await startFlow(page, 'Claude Code')

  // Signed out: the authorize URL leads to the login page and from there to the consent page.
  await page.goto(flow.authorizeUrl)
  await signInOnLoginPage(page, user)

  // A new user has no agent yet: the page says so and leads to the agents page.
  await expect(page.getByRole('heading', { level: 1, name: /^Claude Code wants to access/ })).toBeVisible()
  await expect(page.getByText('Create an agent first.')).toBeVisible()
  const organization = await myOrganization(page)
  await expect(page.getByRole('link', { name: `Agents of ${organization.name}` })).toHaveAttribute(
    'href',
    `/o/${organization.slug}/agents`,
  )
  await expect(page.getByRole('button', { name: 'Allow' })).toBeHidden()

  for (const [name, description] of [
    ['Claude', 'Keeps the backlog tidy.'],
    ['Codex', null],
  ] as const) {
    const created = await page.request.post(`/api/orgs/${organization.id}/agents`, { data: { name, description } })
    expect(created.status()).toBe(201)
  }

  // Signed in now, a new attempt goes straight to the consent page.
  await page.goto(flow.authorizeUrl)
  await expect(page).toHaveURL(/\/oauth\/consent\?request=[0-9a-f-]{36}$/)
  await expect(page.getByText('127.0.0.1:8799')).toBeVisible()
  await expect(page.getByText(user.email)).toBeVisible()
  const agents = page.getByRole('group', { name: organization.name })
  await expect(agents.getByRole('radio')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Allow' })).toBeDisabled()
  await agents.getByRole('radio', { name: 'Codex' }).check()
  await page.getByRole('button', { name: 'Allow' }).click()

  const callback = await flow.callback
  await expect(page.getByRole('heading', { name: 'Back in the application' })).toBeVisible()
  expect(callback.origin + callback.pathname).toBe(REDIRECT_URI)
  expect(callback.searchParams.get('state')).toBe(flow.state)
  expect(callback.searchParams.get('error')).toBeNull()
  const code = callback.searchParams.get('code')
  expect(code).toBeTruthy()

  // The code is real: with the PKCE verifier the client gets its tokens.
  const tokens = await page.request.post('/token', {
    form: {
      grant_type: 'authorization_code',
      code: code ?? '',
      redirect_uri: REDIRECT_URI,
      client_id: flow.clientId,
      code_verifier: flow.verifier,
    },
  })
  expect(tokens.status()).toBe(200)
  expect(await tokens.json()).toMatchObject({ token_type: 'Bearer', access_token: expect.any(String) })

  // The request was answered: going back to the consent page shows an error and stays there.
  await page.goBack()
  await expect(page.getByRole('alert')).toContainText('It may have expired or been answered already')
  await expect(page).toHaveURL(/\/oauth\/consent\?request=/)
})

test('denying sends the browser back with an error and without a code', async ({ page }) => {
  const user = uniqueUser('Grace Hopper')
  const flow = await startFlow(page, 'Codex CLI')

  await page.goto(flow.authorizeUrl)
  await signInOnLoginPage(page, user)
  await expect(page.getByRole('heading', { level: 1, name: /^Codex CLI wants to access/ })).toBeVisible()
  await page.getByRole('button', { name: 'Deny' }).click()

  const callback = await flow.callback
  await expect(page.getByRole('heading', { name: 'Back in the application' })).toBeVisible()
  expect(callback.searchParams.get('error')).toBe('access_denied')
  expect(callback.searchParams.get('state')).toBe(flow.state)
  expect(callback.searchParams.get('code')).toBeNull()
})

test('an unknown request shows an error', async ({ page }) => {
  const user = uniqueUser()
  await page.goto(`/oauth/consent?request=${randomUUID()}`)
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Name').fill(user.name)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('alert')).toContainText('This authorization request was not found')
  await expect(page).toHaveURL(/\/oauth\/consent\?request=/)
  await expect(page.getByRole('button', { name: 'Allow' })).toBeHidden()
})
