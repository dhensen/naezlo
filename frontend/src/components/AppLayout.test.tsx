import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import { ACME, ADA_IN_ORGS, apiError, BETA, json, mockApi, project } from '../test/api'
import { renderApp } from '../test/render'

function location() {
  return screen.getByTestId('location').textContent
}

function routes(): Parameters<typeof mockApi>[0] {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([
      project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website'),
      project(ACME, '0190a000-0000-7000-8000-0000000000b2', 'Launch'),
    ]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
  }
}

async function openSwitcher(current: string) {
  await userEvent.click(await screen.findByRole('button', { name: `Organization: ${current}` }))
}

test('the sidebar lists the projects of the current organization', async () => {
  mockApi(routes())
  renderApp('/o/acme')

  const sidebar = await screen.findByRole('navigation', { name: 'Projects' })
  const website = await within(sidebar).findByRole('link', { name: 'Website' })
  expect(website).toHaveAttribute('href', '/o/acme/p/0190a000-0000-7000-8000-0000000000b1')
  expect(within(sidebar).getByRole('link', { name: 'Launch' })).toBeInTheDocument()
  expect(within(sidebar).queryByText('No projects yet.')).not.toBeInTheDocument()
})

test('the sidebar has an empty state when there are no projects', async () => {
  mockApi(routes())
  renderApp('/o/beta-works')

  const sidebar = await screen.findByRole('navigation', { name: 'Projects' })
  expect(await within(sidebar).findByText('No projects yet.')).toBeInTheDocument()
  expect(within(sidebar).queryByRole('link')).not.toBeInTheDocument()
})

test('the start page of an organization lists its projects and can create one', async () => {
  mockApi(routes())
  renderApp('/o/acme')

  const projects = await screen.findByRole('list', { name: 'Projects of this organization' })
  const links = within(projects).getAllByRole('link')
  expect(links.length).toBeGreaterThan(0)
  expect(links.map((link) => link.getAttribute('href'))).toEqual(
    within(screen.getByRole('navigation', { name: 'Projects' }))
      .getAllByRole('link')
      .map((link) => link.getAttribute('href')),
  )

  await userEvent.click(screen.getByRole('button', { name: 'Create a project' }))
  expect(screen.getByRole('dialog', { name: 'New project' })).toBeInTheDocument()
})

test('the sidebar shows an error when the projects cannot be loaded', async () => {
  mockApi({ ...routes(), [`GET /api/orgs/${ACME.id}/projects`]: apiError(500, 'internal', 'No projects today') })
  renderApp('/o/acme')

  const sidebar = await screen.findByRole('navigation', { name: 'Projects' })
  expect(await within(sidebar).findByRole('alert')).toHaveTextContent('No projects today')
})

test('the switcher lists the organizations and switches to the chosen one', async () => {
  mockApi(routes())
  renderApp('/o/acme')
  await openSwitcher('Acme')

  const list = screen.getByRole('list', { name: 'Organizations' })
  expect(within(list).getAllByRole('link').map((link) => link.textContent)).toEqual(['Acme✓', 'Beta Works'])
  expect(within(list).getByRole('link', { name: /Acme/ })).toHaveAttribute('aria-current', 'true')

  await userEvent.click(within(list).getByRole('link', { name: 'Beta Works' }))

  await waitFor(() => expect(location()).toBe('/o/beta-works'))
  expect(await screen.findByRole('button', { name: 'Organization: Beta Works' })).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Organizations' })).not.toBeInTheDocument()
  expect(await screen.findByText('No projects yet.')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Website' })).not.toBeInTheDocument()
})

test('the switcher closes on Escape and on a press outside it', async () => {
  mockApi(routes())
  renderApp('/o/acme')

  await openSwitcher('Acme')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('list', { name: 'Organizations' })).not.toBeInTheDocument()

  await openSwitcher('Acme')
  await userEvent.click(screen.getByRole('heading', { level: 1, name: 'Acme' }))
  expect(screen.queryByRole('list', { name: 'Organizations' })).not.toBeInTheDocument()
})

test('"New organization" opens a dialog, creates the organization and switches to it', async () => {
  const created = { id: '0190a000-0000-7000-8000-0000000000a3', name: 'Gamma', slug: 'gamma', role: 'owner' }
  let sent: unknown = null
  mockApi({
    ...routes(),
    'POST /api/orgs': async (request) => {
      sent = await request.json()
      return json(created, 201)
    },
    [`GET /api/orgs/${created.id}/projects`]: json([]),
  })
  renderApp('/o/acme')
  await openSwitcher('Acme')

  await userEvent.click(screen.getByRole('button', { name: 'New organization' }))
  const dialog = screen.getByRole('dialog', { name: 'New organization' })
  expect(within(dialog).getByLabelText('Name')).toHaveFocus()
  await userEvent.type(within(dialog).getByLabelText('Name'), 'Gamma')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

  await waitFor(() => expect(location()).toBe('/o/gamma'))
  expect(sent).toEqual({ name: 'Gamma' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await openSwitcher('Gamma')
  expect(screen.getByRole('link', { name: /Gamma/ })).toHaveAttribute('aria-current', 'true')
})

test('a failed creation shows the error in the dialog, which can be cancelled', async () => {
  mockApi({ ...routes(), 'POST /api/orgs': apiError(500, 'internal', 'Could not create it') })
  renderApp('/o/acme')
  await openSwitcher('Acme')
  await userEvent.click(screen.getByRole('button', { name: 'New organization' }))
  const dialog = screen.getByRole('dialog', { name: 'New organization' })

  await userEvent.type(within(dialog).getByLabelText('Name'), 'Gamma')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Could not create it')

  await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(location()).toBe('/o/acme')
})

test('an organization the user is not in is not found, and has no sidebar', async () => {
  mockApi(routes())
  renderApp('/o/elsewhere')

  expect(await screen.findByRole('heading', { level: 1, name: 'Organization not found' })).toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Projects' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Organization: Choose organization' })).toBeInTheDocument()
})

test('an unknown page of an organization keeps the layout', async () => {
  mockApi(routes())
  renderApp('/o/acme/nowhere')

  expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Projects' })).toBeInTheDocument()
})

test('the menu button opens and closes the sidebar drawer', async () => {
  mockApi(routes())
  renderApp('/o/acme')
  const open = await screen.findByRole('button', { name: 'Open navigation' })
  expect(open).toHaveAttribute('aria-expanded', 'false')

  await userEvent.click(open)
  expect(open).toHaveAttribute('aria-expanded', 'true')

  // Choosing a project closes the drawer again.
  const sidebar = screen.getByRole('navigation', { name: 'Projects' })
  await userEvent.click(await within(sidebar).findByRole('link', { name: 'Website' }))
  expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false')
})
