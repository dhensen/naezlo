import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Schemas } from '../api/client'
import {
  ACME,
  ADA_IN_ORGS,
  ADA_MEMBER,
  agentGrant,
  apiError,
  BETA,
  CLAUDE_AGENT,
  GRACE,
  json,
  mockApi,
  project,
  todoList,
  userGrant,
} from '../test/api'
import { renderApp } from '../test/render'

type Routes = Parameters<typeof mockApi>[0]

const WEBSITE = project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website')
const BACKLOG = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c1', 'Backlog', { mode: 'mixed' })
const PROJECT_PAGE = `/o/acme/p/${WEBSITE.id}`
const LIST_PAGE = `/o/acme/l/${BACKLOG.id}`
const PROJECT_GRANTS = `/api/projects/${WEBSITE.id}/grants`
const LIST_GRANTS = `/api/lists/${BACKLOG.id}/grants`

const ADA_ADMIN = userGrant('g1', ADA_MEMBER, 'admin' as const)

/** A route that records the JSON bodies it gets and answers with `answer`. */
function recorded(answer: (body: never) => Response) {
  const bodies: unknown[] = []
  const route = async (request: Request) => {
    const body: unknown = request.method === 'DELETE' ? null : await request.json()
    bodies.push(body)
    return answer(body as never)
  }
  return { bodies, route }
}

function projectRoutes(shown = WEBSITE, grants: Schemas['GrantOut'][] = [ADA_ADMIN]): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([shown]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/orgs/${ACME.id}/members`]: json([ADA_MEMBER, GRACE]),
    [`GET /api/orgs/${ACME.id}/agents`]: json([CLAUDE_AGENT]),
    [`GET /api/projects/${shown.id}`]: json(shown),
    [`GET /api/projects/${shown.id}/lists`]: json([]),
    [`GET ${PROJECT_GRANTS}`]: json(grants),
  }
}

function listRoutes(
  list = BACKLOG,
  grants: Schemas['ListGrantOut'][] = [],
  inherited: Schemas['GrantOut'][] = [ADA_ADMIN],
): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([WEBSITE]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/orgs/${ACME.id}/members`]: json([ADA_MEMBER, GRACE]),
    [`GET /api/orgs/${ACME.id}/agents`]: json([CLAUDE_AGENT]),
    [`GET /api/lists/${list.id}`]: json(list),
    [`GET /api/lists/${list.id}/items`]: json([]),
    [`GET ${LIST_GRANTS}`]: json(grants),
    [`GET ${LIST_GRANTS}/inherited`]: json(inherited),
  }
}

async function openShare(title: string) {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Share' }))
  const dialog = await screen.findByRole('dialog', { name: title })
  return { user, dialog: within(dialog) }
}

function rowTexts(list: HTMLElement) {
  return within(list)
    .getAllByRole('listitem')
    .map((row) => row.textContent)
}

/** The principals the picker offers, without its placeholder. */
function offered(dialog: ReturnType<typeof within>) {
  return within(dialog.getByRole('combobox', { name: 'Person or agent' }))
    .getAllByRole('option')
    .slice(1)
    .map((option) => option.textContent)
}

test('the project dialog lists the grants with name, a person or agent marker and the role', async () => {
  mockApi(projectRoutes(WEBSITE, [ADA_ADMIN, agentGrant('g2', CLAUDE_AGENT, 'editor' as const)]))
  renderApp(PROJECT_PAGE)

  const { dialog } = await openShare('Share Website')

  const rows = within(await dialog.findByRole('list', { name: 'People and agents with access' })).getAllByRole(
    'listitem',
  )
  expect(within(rows[0]).getByText('Ada Lovelace')).toBeInTheDocument()
  expect(within(rows[0]).getByText('Person')).toBeInTheDocument()
  expect(within(rows[0]).getByText('ada@example.com')).toBeInTheDocument()
  expect(within(rows[0]).getByRole('combobox', { name: 'Role of Ada Lovelace' })).toHaveValue('admin')
  expect(within(rows[1]).getByText('Claude')).toBeInTheDocument()
  expect(within(rows[1]).getByText('Agent')).toBeInTheDocument()
  expect(within(rows[1]).getByRole('combobox', { name: 'Role of Claude' })).toHaveValue('editor')
  // A project has no "No access" role.
  expect(dialog.queryByRole('option', { name: 'No access' })).not.toBeInTheDocument()
  // Whoever has a grant is not offered again.
  await waitFor(() => expect(offered(dialog)).toEqual(['Grace Hopper (grace@example.com)']))
})

test('only a project admin gets the Share button', async () => {
  mockApi(projectRoutes(project(ACME, WEBSITE.id, 'Website', { role: 'editor' })))
  renderApp(PROJECT_PAGE)

  expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument()
})

test('the picker adds a grant, the role is changed in the row and a grant is revoked after a question', async () => {
  const routes = projectRoutes()
  const put = recorded((body: Schemas['GrantIn']) =>
    json(
      body.principal_kind === 'agent'
        ? agentGrant('g3', CLAUDE_AGENT, body.role)
        : userGrant('g2', GRACE, body.role),
    ),
  )
  const revoked = recorded(() => new Response(null, { status: 204 }))
  routes[`PUT ${PROJECT_GRANTS}`] = put.route
  routes[`DELETE ${PROJECT_GRANTS}/g2`] = revoked.route
  mockApi(routes)
  renderApp(PROJECT_PAGE)
  const { user, dialog } = await openShare('Share Website')
  await waitFor(() => expect(offered(dialog)).toEqual(['Grace Hopper (grace@example.com)', 'Claude']))

  // Nothing picked: nothing to add.
  expect(dialog.getByRole('button', { name: 'Add' })).toBeDisabled()
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Person or agent' }), 'Grace Hopper (grace@example.com)')
  await user.click(dialog.getByRole('button', { name: 'Add' }))

  const graceRole = await dialog.findByRole('combobox', { name: 'Role of Grace Hopper' })
  expect(graceRole).toHaveValue('viewer')
  expect(put.bodies).toEqual([{ principal_kind: 'user', principal_id: GRACE.user_id, role: 'viewer' }])
  expect(offered(dialog)).toEqual(['Claude'])
  expect(dialog.getByRole('combobox', { name: 'Person or agent' })).toHaveValue('')

  // An agent, with another role.
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Person or agent' }), 'Claude')
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Role' }), 'Editor')
  await user.click(dialog.getByRole('button', { name: 'Add' }))
  expect(await dialog.findByRole('combobox', { name: 'Role of Claude' })).toHaveValue('editor')
  expect(put.bodies[1]).toEqual({ principal_kind: 'agent', principal_id: CLAUDE_AGENT.id, role: 'editor' })
  expect(dialog.getByText('Every member and agent of the organization is listed here.')).toBeInTheDocument()

  // Change a role in the row.
  await user.selectOptions(graceRole, 'Admin')
  await waitFor(() => expect(graceRole).toHaveValue('admin'))
  expect(put.bodies[2]).toEqual({ principal_kind: 'user', principal_id: GRACE.user_id, role: 'admin' })

  // Revoke: the row asks first.
  await user.click(dialog.getByRole('button', { name: 'Remove Grace Hopper' }))
  await user.click(dialog.getByRole('button', { name: 'Cancel' }))
  expect(revoked.bodies).toEqual([])
  await user.click(dialog.getByRole('button', { name: 'Remove Grace Hopper' }))
  await user.click(dialog.getByRole('button', { name: 'Yes, remove' }))
  await waitFor(() => expect(dialog.queryByText('Grace Hopper')).not.toBeInTheDocument())
  expect(revoked.bodies).toHaveLength(1)
  expect(offered(dialog)).toEqual(['Grace Hopper (grace@example.com)'])

  await user.click(dialog.getByRole('button', { name: 'Done' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('a change the API refuses shows its message and leaves the role as it was', async () => {
  const routes = projectRoutes()
  routes[`PUT ${PROJECT_GRANTS}`] = apiError(409, 'last_project_admin', 'A project needs at least one admin')
  mockApi(routes)
  renderApp(PROJECT_PAGE)
  const { user, dialog } = await openShare('Share Website')

  await user.selectOptions(await dialog.findByRole('combobox', { name: 'Role of Ada Lovelace' }), 'Viewer')

  expect(await dialog.findByRole('alert')).toHaveTextContent('A project needs at least one admin')
  expect(dialog.getByRole('combobox', { name: 'Role of Ada Lovelace' })).toHaveValue('admin')
})

test('a change to the own grant asks for the project again', async () => {
  const routes = projectRoutes()
  routes[`PUT ${PROJECT_GRANTS}`] = () => {
    const viewer = project(ACME, WEBSITE.id, 'Website', { role: 'viewer' })
    routes[`GET /api/projects/${WEBSITE.id}`] = json(viewer)
    routes[`GET /api/orgs/${ACME.id}/projects`] = json([viewer])
    return json(userGrant('g1', ADA_MEMBER, 'viewer' as const))
  }
  mockApi(routes)
  renderApp(PROJECT_PAGE)
  const { user, dialog } = await openShare('Share Website')

  await user.selectOptions(await dialog.findByRole('combobox', { name: 'Role of Ada Lovelace' }), 'Viewer')

  // No longer an admin: the page loses its admin controls.
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument())
  expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument()
})

test('the list dialog shows the grants on the list apart from the access that comes from the project', async () => {
  const routes = listRoutes(
    BACKLOG,
    [userGrant('lg1', GRACE, 'none' as const)],
    [ADA_ADMIN, userGrant('g2', GRACE, 'editor' as const), agentGrant('g3', CLAUDE_AGENT, 'viewer' as const)],
  )
  const put = recorded((body: Schemas['ListGrantIn']) => json(agentGrant('lg2', CLAUDE_AGENT, body.role)))
  routes[`PUT ${LIST_GRANTS}`] = put.route
  mockApi(routes)
  renderApp(LIST_PAGE)

  const { user, dialog } = await openShare('Share Backlog')

  const own = await dialog.findByRole('list', { name: 'Access to this list only' })
  expect(within(own).getAllByRole('listitem')).toHaveLength(1)
  // "No access" is a role here: it hides the list from Grace.
  expect(within(own).getByRole('combobox', { name: 'Role of Grace Hopper' })).toHaveValue('none')
  expect(within(own).getByRole('option', { name: 'No access' })).toBeInTheDocument()
  expect(dialog.getByRole('heading', { name: 'Access from the project Website' })).toBeInTheDocument()
  const inherited = await dialog.findByRole('list', { name: 'Access from the project' })
  expect(rowTexts(inherited)).toEqual([
    'Ada LovelacePersonada@example.comAdmin',
    'Grace HopperPersongrace@example.comEditor (replaced on this list)',
    'ClaudeAgentViewer',
  ])
  // Inherited access is not changed here.
  expect(within(inherited).queryByRole('combobox')).not.toBeInTheDocument()
  // A mixed list: nothing to warn about.
  expect(dialog.queryByRole('note')).not.toBeInTheDocument()

  // Someone with a role on the project can get one of their own on the list.
  await waitFor(() => expect(offered(dialog)).toEqual(['Ada Lovelace (ada@example.com)', 'Claude']))
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Person or agent' }), 'Claude')
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Role' }), 'No access')
  await user.click(dialog.getByRole('button', { name: 'Add' }))

  expect(await within(own).findByRole('combobox', { name: 'Role of Claude' })).toHaveValue('none')
  expect(put.bodies).toEqual([{ principal_kind: 'agent', principal_id: CLAUDE_AGENT.id, role: 'none' }])
  expect(rowTexts(inherited)[2]).toBe('ClaudeAgentViewer (replaced on this list)')
})

test('on a human-only list the dialog says that agents have no access whatever the grants', async () => {
  mockApi(listRoutes(todoList(WEBSITE, BACKLOG.id, 'Backlog', { mode: 'human_only' })))
  renderApp(LIST_PAGE)

  const { dialog } = await openShare('Share Backlog')

  expect(dialog.getByRole('note')).toHaveTextContent(
    'This list is human only: AI agents cannot access it, whatever role they are given here or on the project.',
  )
  expect(await dialog.findByText('Nobody has a role of their own on this list.')).toBeInTheDocument()
})

test('only a list admin gets the Share button on the list page', async () => {
  mockApi(
    listRoutes(todoList(WEBSITE, BACKLOG.id, 'Backlog', { role: 'editor', actions: ['read', 'change_items', 'edit_list'] })),
  )
  renderApp(LIST_PAGE)

  expect(await screen.findByRole('textbox', { name: 'Add an item' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument()
})
