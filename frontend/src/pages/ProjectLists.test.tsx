import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, BETA, json, mockApi, project, todoList } from '../test/api'
import { renderApp } from '../test/render'

type Routes = Parameters<typeof mockApi>[0]
type List = Schemas['ListOut']

const WEBSITE = project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website')
const PAGE = `/o/acme/p/${WEBSITE.id}`
const BACKLOG = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c1', 'Backlog', { description: 'Everything else.' })

function routes(shown: Schemas['ProjectOut'] = WEBSITE, lists: List[] = []): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([shown]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/projects/${shown.id}`]: json(shown),
    [`GET /api/projects/${shown.id}/lists`]: json(lists),
  }
}

async function rows() {
  return within(await screen.findByRole('list', { name: 'Lists' })).getAllByRole('listitem')
}

function checkedMode(dialog: HTMLElement) {
  return within(dialog)
    .getAllByRole('radio')
    .filter((radio) => (radio as HTMLInputElement).checked)
    .map((radio) => (radio as HTMLInputElement).value)
}

test('every mode has its own label, icon and explaining tooltip', async () => {
  mockApi(
    routes(WEBSITE, [
      todoList(WEBSITE, 'l1', 'Private'),
      todoList(WEBSITE, 'l2', 'Agent queue', { mode: 'ai_only', position: 2 }),
      todoList(WEBSITE, 'l3', 'Shared', { mode: 'mixed', position: 3 }),
    ]),
  )
  renderApp(PAGE)

  const [humanOnly, aiOnly, mixed] = await rows()
  const badges = [
    [humanOnly, 'Human only', 'human_only', 'Only people work on this list. AI agents cannot see it.'],
    [aiOnly, 'AI only', 'ai_only', 'AI agents work on this list. People can read it, but not change its items.'],
    [mixed, 'Mixed', 'mixed', 'People and AI agents work on this list together.'],
  ] as const
  for (const [row, label, icon, explanation] of badges) {
    const badge = within(row).getByText(label)
    expect(badge).toHaveAccessibleDescription(explanation)
    expect(within(row).getByRole('tooltip', { hidden: true })).toHaveTextContent(explanation)
    expect(badge.querySelector('svg')).toHaveAttribute('data-mode-icon', icon)
    // Reachable with the keyboard, so the tooltip is not for the mouse alone.
    expect(badge).toHaveAttribute('tabindex', '0')
  }
})

test('"New list" preselects the default mode of the organization and adds the list', async () => {
  const created = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c2', 'Launch', { description: 'Go live.' })
  const bodies: unknown[] = []
  mockApi({
    ...routes(),
    [`POST /api/projects/${WEBSITE.id}/lists`]: async (request) => {
      bodies.push(await request.json())
      return json(created, 201)
    },
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'New list' }))
  const dialog = screen.getByRole('dialog', { name: 'New list' })
  expect(within(dialog).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([
    'human_only',
    'ai_only',
    'mixed',
  ])
  expect(checkedMode(dialog)).toEqual(['human_only'])
  expect(within(dialog).getByRole('radio', { name: 'Human only' })).toHaveAccessibleDescription(
    'Only people work on this list. AI agents cannot see it.',
  )
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled()
  await userEvent.type(within(dialog).getByLabelText('Name'), 'Launch')
  await userEvent.type(within(dialog).getByLabelText('Description (optional)'), 'Go live.')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(bodies).toEqual([{ name: 'Launch', description: 'Go live.', mode: 'human_only' }])
  const [row] = await rows()
  expect(row).toHaveTextContent('Launch')
  expect(row).toHaveTextContent('Go live.')
  expect(screen.queryByText('This project has no lists yet.')).not.toBeInTheDocument()
})

test('the preselected mode is Mixed in an organization with an agent, and can be changed', async () => {
  const withAgent = project(ACME, WEBSITE.id, 'Website', { default_list_mode: 'mixed' })
  const bodies: unknown[] = []
  mockApi({
    ...routes(withAgent),
    [`POST /api/projects/${WEBSITE.id}/lists`]: async (request) => {
      bodies.push(await request.json())
      return json(todoList(WEBSITE, 'l9', 'Queue', { mode: 'ai_only' }), 201)
    },
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'New list' }))
  const dialog = screen.getByRole('dialog', { name: 'New list' })
  expect(checkedMode(dialog)).toEqual(['mixed'])
  await userEvent.click(within(dialog).getByRole('radio', { name: 'AI only' }))
  expect(checkedMode(dialog)).toEqual(['ai_only'])
  await userEvent.type(within(dialog).getByLabelText('Name'), 'Queue')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

  await waitFor(() => expect(bodies).toEqual([{ name: 'Queue', description: null, mode: 'ai_only' }]))
  expect((await rows())[0]).toHaveTextContent('AI only')
})

test('the dialog asks for the default again: an agent added since the page loaded counts', async () => {
  const api = routes()
  mockApi(api)
  renderApp(PAGE)
  const newList = await screen.findByRole('button', { name: 'New list' })
  api[`GET /api/projects/${WEBSITE.id}`] = json({ ...WEBSITE, default_list_mode: 'mixed' })

  await userEvent.click(newList)

  const dialog = screen.getByRole('dialog', { name: 'New list' })
  await waitFor(() => expect(checkedMode(dialog)).toEqual(['mixed']))
})

test('a failed create stays in the dialog with the error', async () => {
  mockApi({
    ...routes(),
    [`POST /api/projects/${WEBSITE.id}/lists`]: apiError(403, 'forbidden', 'This needs the editor role on the project'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'New list' }))
  await userEvent.type(screen.getByLabelText('Name'), 'Launch')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('This needs the editor role on the project')
  expect(screen.getByRole('dialog', { name: 'New list' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('a project viewer gets no "New list"', async () => {
  mockApi(routes({ ...WEBSITE, role: 'viewer' }, [{ ...BACKLOG, role: 'viewer', actions: ['read'] }]))
  renderApp(PAGE)

  await rows()
  expect(screen.queryByRole('button', { name: 'New list' })).not.toBeInTheDocument()
})

test('the row controls follow what the API allows on each list', async () => {
  mockApi(
    routes(WEBSITE, [
      { ...BACKLOG, role: 'viewer', actions: ['read'] },
      todoList(WEBSITE, 'l2', 'Plans', { role: 'editor', actions: ['read', 'change_items', 'edit_list'], position: 2 }),
      // An editor of an AI-only list may not change it.
      todoList(WEBSITE, 'l3', 'Agent queue', { mode: 'ai_only', role: 'editor', actions: ['read'], position: 3 }),
      todoList(WEBSITE, 'l4', 'Mine', { position: 4 }),
    ]),
  )
  renderApp(PAGE)

  const buttons = (await rows()).map((row) =>
    within(row)
      .queryAllByRole('button')
      .map((button) => button.getAttribute('aria-label')),
  )
  expect(buttons).toEqual([[], ['Edit Plans'], [], ['Edit Mine', 'Delete Mine']])
})

test('editing renames the list and changes its mode; only what changed is sent', async () => {
  const bodies: unknown[] = []
  mockApi({
    ...routes(WEBSITE, [BACKLOG]),
    [`PATCH /api/lists/${BACKLOG.id}`]: async (request) => {
      bodies.push(await request.json())
      return json({ ...BACKLOG, name: 'Icebox', mode: 'mixed' })
    },
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Edit Backlog' }))
  const dialog = screen.getByRole('dialog', { name: 'Edit list' })
  const name = within(dialog).getByLabelText('Name')
  expect(name).toHaveValue('Backlog')
  expect(within(dialog).getByLabelText('Description (optional)')).toHaveValue('Everything else.')
  expect(checkedMode(dialog)).toEqual(['human_only'])
  await userEvent.clear(name)
  await userEvent.type(name, 'Icebox')
  await userEvent.click(within(dialog).getByRole('radio', { name: 'Mixed' }))
  await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(bodies).toEqual([{ name: 'Icebox', mode: 'mixed' }])
  const [row] = await rows()
  expect(row).toHaveTextContent('Icebox')
  expect(within(row).getByText('Mixed')).toBeInTheDocument()
  expect(within(row).queryByText('Human only')).not.toBeInTheDocument()
})

test('clearing the description sends null; saving without a change sends nothing', async () => {
  const bodies: unknown[] = []
  const fetchMock = mockApi({
    ...routes(WEBSITE, [BACKLOG]),
    [`PATCH /api/lists/${BACKLOG.id}`]: async (request) => {
      bodies.push(await request.json())
      return json({ ...BACKLOG, description: null })
    },
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Edit Backlog' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([request]) => request.method === 'PATCH')).toHaveLength(0)

  await userEvent.click(screen.getByRole('button', { name: 'Edit Backlog' }))
  await userEvent.clear(screen.getByLabelText('Description (optional)'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(bodies).toEqual([{ description: null }]))
  await waitFor(() => expect(screen.queryByText('Everything else.')).not.toBeInTheDocument())
})

test('a refused mode change shows the error in the dialog', async () => {
  mockApi({
    ...routes(WEBSITE, [BACKLOG]),
    [`PATCH /api/lists/${BACKLOG.id}`]: apiError(403, 'list_ai_only', 'This list is AI-only: only its admins can change it'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Edit Backlog' }))
  await userEvent.click(screen.getByRole('radio', { name: 'AI only' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('only its admins can change it')
  expect(screen.getByRole('dialog', { name: 'Edit list' })).toBeInTheDocument()
})

test('deleting a list asks first, then removes the row', async () => {
  const fetchMock = mockApi({
    ...routes(WEBSITE, [BACKLOG, todoList(WEBSITE, 'l2', 'Plans', { position: 2 })]),
    [`DELETE /api/lists/${BACKLOG.id}`]: new Response(null, { status: 204 }),
  })
  const deletes = () => fetchMock.mock.calls.filter(([request]) => request.method === 'DELETE').length
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Delete Backlog' }))
  const dialog = screen.getByRole('dialog', { name: 'Delete Backlog?' })
  expect(dialog).toHaveTextContent('The list is deleted with all its items.')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(deletes()).toBe(0)

  await userEvent.click(screen.getByRole('button', { name: 'Delete Backlog' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete list' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(deletes()).toBe(1)
  expect((await rows()).map((row) => within(row).getByText(/^(Backlog|Plans)$/).textContent)).toEqual(['Plans'])
})

test('a list created while the lists are still loading is not lost to the older answer', async () => {
  const created = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c2', 'Launch')
  let answerLists: (response: Response) => void = () => {}
  let listRequests = 0
  const api: Routes = {
    ...routes(),
    // The first answer is held back until after the create; it does not know the new list.
    [`GET /api/projects/${WEBSITE.id}/lists`]: () => {
      listRequests += 1
      if (listRequests > 1) {
        return json([created])
      }
      return new Promise<Response>((resolve) => {
        answerLists = resolve
      })
    },
    [`POST /api/projects/${WEBSITE.id}/lists`]: json(created, 201),
  }
  mockApi(api)
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'New list' }))
  await userEvent.type(screen.getByLabelText('Name'), 'Launch')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  answerLists(json([]))

  expect((await rows())[0]).toHaveTextContent('Launch')
  expect(screen.queryByText('This project has no lists yet.')).not.toBeInTheDocument()
})
