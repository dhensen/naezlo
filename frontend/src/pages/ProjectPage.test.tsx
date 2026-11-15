import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, BETA, json, mockApi, project, todoList } from '../test/api'
import { renderApp } from '../test/render'

type Routes = Parameters<typeof mockApi>[0]

const WEBSITE = project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website', { description: 'The new site.' })
const LAUNCH = project(ACME, '0190a000-0000-7000-8000-0000000000b2', 'Launch')
const PAGE = `/o/acme/p/${WEBSITE.id}`

function location() {
  return screen.getByTestId('location').textContent
}

function routes(shown: Schemas['ProjectOut'] = WEBSITE, lists: Schemas['ListOut'][] = []): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([shown, LAUNCH]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/projects/${shown.id}`]: json(shown),
    [`GET /api/projects/${shown.id}/lists`]: json(lists),
  }
}

function sidebar() {
  return screen.getByRole('navigation', { name: 'Projects' })
}

test('shows the name, the description and the lists with mode and open items', async () => {
  mockApi(
    routes(WEBSITE, [
      todoList(WEBSITE, 'l1', 'Backlog', { mode: 'mixed', open_item_count: 3 }),
      todoList(WEBSITE, 'l2', 'Agent queue', { mode: 'ai_only', open_item_count: 1, position: 2 }),
      todoList(WEBSITE, 'l3', 'Private', { position: 3 }),
    ]),
  )
  renderApp(PAGE)

  expect(await screen.findByRole('heading', { level: 1, name: 'Website' })).toBeInTheDocument()
  expect(screen.getByText('The new site.')).toBeInTheDocument()
  const rows = within(await screen.findByRole('list', { name: 'Lists' })).getAllByRole('listitem')
  // Each row: the name, the mode badge (the tooltip's text follows the label) and the open items.
  expect(rows.map((row) => row.textContent)).toEqual([
    expect.stringMatching(/^BacklogMixedPeople and AI agents .*3 open items/),
    expect.stringMatching(/^Agent queueAI onlyAI agents work .*1 open item/),
    expect.stringMatching(/^PrivateHuman onlyOnly people .*No open items/),
  ])
})

test('a project without lists has an empty state', async () => {
  mockApi(routes())
  renderApp(PAGE)

  expect(await screen.findByText('This project has no lists yet.')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Lists' })).not.toBeInTheDocument()
})

test('an unknown project is not found', async () => {
  mockApi({ ...routes(), [`GET /api/projects/${WEBSITE.id}`]: apiError(404, 'not_found', 'Project not found') })
  renderApp(PAGE)

  expect(await screen.findByRole('heading', { level: 1, name: 'Project not found' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to Acme' })).toHaveAttribute('href', '/o/acme')
})

test('a project of another organization is not found under this one', async () => {
  const elsewhere = project(BETA, WEBSITE.id, 'Elsewhere')
  mockApi({ ...routes(), [`GET /api/projects/${WEBSITE.id}`]: json(elsewhere) })
  renderApp(PAGE)

  expect(await screen.findByRole('heading', { level: 1, name: 'Project not found' })).toBeInTheDocument()
})

test('a viewer gets no controls, an editor only Edit, an admin Edit and Delete', async () => {
  mockApi(routes({ ...WEBSITE, role: 'viewer' }))
  const viewer = renderApp(PAGE)
  expect(await screen.findByRole('heading', { level: 1, name: 'Website' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  viewer.unmount()

  mockApi(routes({ ...WEBSITE, role: 'editor' }))
  const editor = renderApp(PAGE)
  expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  editor.unmount()

  mockApi(routes())
  renderApp(PAGE)
  expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
})

test('"New project" creates the project, opens it and adds it to the sidebar', async () => {
  const created = project(ACME, '0190a000-0000-7000-8000-0000000000b9', 'Moon landing', { description: 'One small step.' })
  const bodies: unknown[] = []
  mockApi({
    ...routes(),
    [`POST /api/orgs/${ACME.id}/projects`]: async (request) => {
      bodies.push(await request.json())
      return json(created, 201)
    },
    [`GET /api/projects/${created.id}/lists`]: json([]),
  })
  renderApp('/o/acme')

  await userEvent.click(await within(await screen.findByRole('navigation', { name: 'Projects' })).findByRole('button', { name: /New project/ }))
  const dialog = screen.getByRole('dialog', { name: 'New project' })
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled()
  await userEvent.type(within(dialog).getByLabelText('Name'), 'Moon landing')
  await userEvent.type(within(dialog).getByLabelText('Description (optional)'), 'One small step.')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

  await waitFor(() => expect(location()).toBe(`/o/acme/p/${created.id}`))
  expect(bodies).toEqual([{ name: 'Moon landing', description: 'One small step.' }])
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  // The project comes from the answer: it is not asked for again.
  expect(await screen.findByRole('heading', { level: 1, name: 'Moon landing' })).toBeInTheDocument()
  expect(within(sidebar()).getAllByRole('link').map((link) => link.textContent)).toEqual([
    'Website',
    'Launch',
    'Moon landing',
  ])
})

test('a failed create stays in the dialog with the error; Cancel and Escape close it', async () => {
  mockApi({ ...routes(), [`POST /api/orgs/${ACME.id}/projects`]: apiError(422, 'validation_error', 'Name is too long') })
  renderApp('/o/acme')
  const newProject = await within(await screen.findByRole('navigation', { name: 'Projects' })).findByRole('button', {
    name: /New project/,
  })

  await userEvent.click(newProject)
  await userEvent.type(screen.getByLabelText('Name'), 'X')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Name is too long')
  expect(location()).toBe('/o/acme')

  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await userEvent.click(newProject)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('editing renames the project on the page and in the sidebar', async () => {
  const bodies: unknown[] = []
  mockApi({
    ...routes(),
    [`PATCH /api/projects/${WEBSITE.id}`]: async (request) => {
      bodies.push(await request.json())
      return json({ ...WEBSITE, name: 'Website 2', description: null })
    },
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  const dialog = screen.getByRole('dialog', { name: 'Edit project' })
  const name = within(dialog).getByLabelText('Name')
  expect(name).toHaveValue('Website')
  expect(within(dialog).getByLabelText('Description (optional)')).toHaveValue('The new site.')
  await userEvent.clear(name)
  await userEvent.type(name, 'Website 2')
  await userEvent.clear(within(dialog).getByLabelText('Description (optional)'))
  await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Website 2' })).toBeInTheDocument()
  expect(bodies).toEqual([{ name: 'Website 2', description: null }])
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.queryByText('The new site.')).not.toBeInTheDocument()
  expect(within(sidebar()).getByRole('link', { name: 'Website 2' })).toBeInTheDocument()
  expect(within(sidebar()).queryByRole('link', { name: 'Website' })).not.toBeInTheDocument()
})

test('deleting asks first, then leaves the page and the sidebar', async () => {
  const all = { ...routes(), [`DELETE /api/projects/${WEBSITE.id}`]: new Response(null, { status: 204 }) }
  const fetchMock = mockApi(all)
  const deletes = () => fetchMock.mock.calls.filter(([request]) => request.method === 'DELETE').length
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
  const dialog = screen.getByRole('dialog', { name: 'Delete Website?' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(deletes()).toBe(0)

  await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
  // The organization's start page, where this ends, loads the projects again.
  all[`GET /api/orgs/${ACME.id}/projects`] = json([LAUNCH])
  await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))

  await waitFor(() => expect(location()).toBe('/o/acme'))
  expect(deletes()).toBe(1)
  expect(within(sidebar()).queryByRole('link', { name: 'Website' })).not.toBeInTheDocument()
  expect(within(sidebar()).getByRole('link', { name: 'Launch' })).toBeInTheDocument()
})

test('a refused delete shows the error in the dialog', async () => {
  mockApi({
    ...routes(),
    [`DELETE /api/projects/${WEBSITE.id}`]: apiError(403, 'forbidden', 'This needs the admin role on the project'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('This needs the admin role on the project')
  expect(location()).toBe(PAGE)
})
