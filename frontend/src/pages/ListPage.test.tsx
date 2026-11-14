import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, BETA, item, json, mockApi, project, todoList } from '../test/api'
import { renderApp } from '../test/render'

type Routes = Parameters<typeof mockApi>[0]
type Item = Schemas['ItemOut']

const WEBSITE = project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website')
const BACKLOG = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c1', 'Backlog', {
  mode: 'mixed',
  description: 'Everything else.',
})
const PAGE = `/o/acme/l/${BACKLOG.id}`
const AGENT = { kind: 'agent', id: '0190a000-0000-7000-8000-0000000000f1' } as const

const MILK = item(BACKLOG, 'i1', 'Buy milk')
const BREAD = item(BACKLOG, 'i2', 'Bake bread', { position: 2, notes: 'Sourdough.' })
const EGGS = item(BACKLOG, 'i3', 'Boil eggs', { position: 3 })
const TEA = item(BACKLOG, 'i4', 'Make tea', {
  position: 4,
  status: 'done',
  completed_by: { kind: 'user', id: ADA_IN_ORGS.user.id },
  completed_at: '2026-11-02T10:00:00Z',
})

function routes(list: Schemas['ListOut'] = BACKLOG, items: Item[] = [MILK, BREAD, EGGS, TEA]): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([WEBSITE]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/lists/${list.id}`]: json(list),
    [`GET /api/lists/${list.id}/items`]: json(items),
  }
}

/** The titles of the items in a list, top to bottom. */
function titles(listName = 'Open items') {
  return within(screen.getByRole('list', { name: listName }))
    .getAllByRole('listitem')
    .map((row) => row.querySelector('[data-title]')?.textContent)
}

async function openItems() {
  return screen.findByRole('list', { name: 'Open items' })
}

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

test('shows the list with its mode, its project and its items; done items are folded away', async () => {
  mockApi(routes())
  renderApp(PAGE)

  expect(await screen.findByRole('heading', { level: 1, name: 'Backlog' })).toBeInTheDocument()
  const main = screen.getByRole('main')
  expect(within(main).getByText('Mixed')).toBeInTheDocument()
  expect(within(main).getByText('Everything else.')).toBeInTheDocument()
  expect(within(main).getByRole('link', { name: 'Website' })).toHaveAttribute('href', `/o/acme/p/${WEBSITE.id}`)

  await openItems()
  expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs'])
  expect(screen.queryByRole('note')).not.toBeInTheDocument()

  // The done ones are behind "Done (1)", struck through.
  expect(screen.queryByRole('list', { name: 'Done items' })).not.toBeInTheDocument()
  const toggle = screen.getByRole('button', { name: 'Done (1)' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const done = screen.getByRole('list', { name: 'Done items' })
  expect(within(done).getByText('Make tea')).toHaveClass('line-through')
  expect(within(done).getByRole('checkbox', { name: 'Mark Make tea as done' })).toBeChecked()
  expect(within(done).queryByRole('button', { name: /^Move/ })).not.toBeInTheDocument()
  await userEvent.click(toggle)
  expect(screen.queryByRole('list', { name: 'Done items' })).not.toBeInTheDocument()
})

test('Enter adds an item at the end and the field keeps the focus for the next one', async () => {
  let made = 0
  const post = recorded((body: { title: string }) => {
    made += 1
    return json(item(BACKLOG, `new-${made}`, body.title.trim(), { position: 4 + made }), 201)
  })
  mockApi({ ...routes(), [`POST /api/lists/${BACKLOG.id}/items`]: post.route })
  renderApp(PAGE)

  const input = await screen.findByRole('textbox', { name: 'Add an item' })
  await userEvent.type(input, ' Wash car {Enter}')
  expect(input).toHaveValue('')
  expect(input).toHaveFocus()
  await userEvent.type(input, 'Feed cat{Enter}')
  expect(input).toHaveFocus()

  await waitFor(() => expect(post.bodies).toEqual([{ title: ' Wash car ' }, { title: 'Feed cat' }]))
  await waitFor(() => expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs', 'Wash car', 'Feed cat']))
  // Stored: its controls work.
  expect(screen.getByRole('checkbox', { name: 'Mark Feed cat as done' })).toBeEnabled()

  // Nothing to add: no request.
  await userEvent.type(input, '   {Enter}')
  expect(post.bodies).toHaveLength(2)
})

test('the checkbox completes an item and reopens it', async () => {
  const patch = recorded((body: { status: 'open' | 'done' }) =>
    json({
      ...MILK,
      status: body.status,
      completed_by: body.status === 'done' ? { kind: 'user', id: ADA_IN_ORGS.user.id } : null,
    }),
  )
  mockApi({ ...routes(), [`PATCH /api/items/${MILK.id}`]: patch.route })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('checkbox', { name: 'Mark Buy milk as done' }))
  await waitFor(() => expect(titles()).toEqual(['Bake bread', 'Boil eggs']))
  await userEvent.click(screen.getByRole('button', { name: 'Done (2)' }))
  expect(titles('Done items')).toEqual(['Buy milk', 'Make tea'])
  expect(patch.bodies).toEqual([{ status: 'done' }])

  await userEvent.click(screen.getByRole('checkbox', { name: 'Mark Buy milk as done' }))
  await waitFor(() => expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs']))
  expect(screen.getByRole('button', { name: 'Done (1)' })).toBeInTheDocument()
  expect(patch.bodies).toEqual([{ status: 'done' }, { status: 'open' }])
})

test('the title is edited in place: Enter saves, Escape and an empty title do not', async () => {
  const patch = recorded((body: { title: string }) => json({ ...MILK, title: body.title }))
  mockApi({ ...routes(), [`PATCH /api/items/${MILK.id}`]: patch.route })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Edit title of Buy milk' }))
  const field = screen.getByRole('textbox', { name: 'Title' })
  expect(field).toHaveFocus()
  expect(field).toHaveValue('Buy milk')
  await userEvent.clear(field)
  await userEvent.type(field, 'Buy oat milk{Enter}')

  const renamed = await screen.findByRole('button', { name: 'Edit title of Buy oat milk' })
  expect(renamed).toHaveFocus()
  expect(patch.bodies).toEqual([{ title: 'Buy oat milk' }])
  expect(titles()).toEqual(['Buy oat milk', 'Bake bread', 'Boil eggs'])

  // Escape leaves it as it was.
  await userEvent.click(renamed)
  await userEvent.type(screen.getByRole('textbox', { name: 'Title' }), ' and sugar{Escape}')
  expect(screen.getByRole('button', { name: 'Edit title of Buy oat milk' })).toBeInTheDocument()
  // So does an empty title.
  await userEvent.click(screen.getByRole('button', { name: 'Edit title of Buy oat milk' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Title' }))
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Edit title of Buy oat milk' })).toBeInTheDocument()
  expect(patch.bodies).toHaveLength(1)
})

test('notes are edited in an area that opens under the item', async () => {
  const patch = recorded((body: { notes: string | null }) => json({ ...BREAD, notes: body.notes }))
  mockApi({ ...routes(), [`PATCH /api/items/${BREAD.id}`]: patch.route })
  renderApp(PAGE)

  const toggle = await screen.findByRole('button', { name: 'Notes of Bake bread' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('textbox', { name: 'Notes of Bake bread' })).not.toBeInTheDocument()
  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const area = screen.getByRole('textbox', { name: 'Notes of Bake bread' })
  expect(area).toHaveValue('Sourdough.')
  expect(screen.getByRole('button', { name: 'Save notes' })).toBeDisabled()

  await userEvent.type(area, ' Two loaves.')
  await userEvent.click(screen.getByRole('button', { name: 'Save notes' }))
  await waitFor(() => expect(patch.bodies).toEqual([{ notes: 'Sourdough. Two loaves.' }]))
  expect(area).toHaveValue('Sourdough. Two loaves.')

  // Emptied notes are removed.
  await userEvent.clear(area)
  await userEvent.click(screen.getByRole('button', { name: 'Save notes' }))
  await waitFor(() => expect(patch.bodies).toEqual([{ notes: 'Sourdough. Two loaves.' }, { notes: null }]))

  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('textbox', { name: 'Notes of Bake bread' })).not.toBeInTheDocument()
})

test('deleting asks in the row first', async () => {
  const remove = recorded(() => new Response(null, { status: 204 }))
  mockApi({ ...routes(), [`DELETE /api/items/${BREAD.id}`]: remove.route })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('button', { name: 'Delete Bake bread' }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(remove.bodies).toHaveLength(0)
  expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs'])

  await userEvent.click(screen.getByRole('button', { name: 'Delete Bake bread' }))
  await userEvent.click(screen.getByRole('button', { name: 'Yes, delete' }))
  await waitFor(() => expect(titles()).toEqual(['Buy milk', 'Boil eggs']))
  await waitFor(() => expect(remove.bodies).toHaveLength(1))
})

test('move up and move down work with the keyboard and keep the focus on the button', async () => {
  // A done item sits between the open ones: moving skips it.
  const tea = { ...TEA, position: 2 }
  const bread = { ...BREAD, position: 3 }
  const eggs = { ...EGGS, position: 4 }
  const moveMilk = recorded(() => json(MILK))
  const moveEggs = recorded(() => json(eggs))
  mockApi({
    ...routes(BACKLOG, [MILK, tea, bread, eggs]),
    [`POST /api/items/${MILK.id}/move`]: moveMilk.route,
    [`POST /api/items/${EGGS.id}/move`]: moveEggs.route,
  })
  renderApp(PAGE)

  const down = await screen.findByRole('button', { name: 'Move Buy milk down' })
  expect(screen.getByRole('button', { name: 'Move Buy milk up' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Move Boil eggs down' })).toBeDisabled()

  down.focus()
  await userEvent.keyboard('{Enter}')
  await waitFor(() => expect(titles()).toEqual(['Bake bread', 'Buy milk', 'Boil eggs']))
  expect(screen.getByRole('button', { name: 'Move Buy milk down' })).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  await waitFor(() => expect(titles()).toEqual(['Bake bread', 'Boil eggs', 'Buy milk']))
  // At the bottom "down" is switched off: the focus is on "up".
  expect(screen.getByRole('button', { name: 'Move Buy milk down' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Move Buy milk up' })).toHaveFocus()
  // After the bread means before the eggs; after the eggs means at the end.
  await waitFor(() => expect(moveMilk.bodies).toEqual([{ before_item_id: EGGS.id }, { before_item_id: null }]))

  await userEvent.click(screen.getByRole('button', { name: 'Move Boil eggs up' }))
  await waitFor(() => expect(titles()).toEqual(['Boil eggs', 'Bake bread', 'Buy milk']))
  await waitFor(() => expect(moveEggs.bodies).toEqual([{ before_item_id: BREAD.id }]))
})

test('a change shows before the server answers and is undone with a message when it is rejected', async () => {
  let answer: (response: Response) => void = () => {}
  const fetches = mockApi({
    ...routes(),
    [`PATCH /api/items/${MILK.id}`]: () => new Promise<Response>((resolve) => (answer = resolve)),
    [`POST /api/lists/${BACKLOG.id}/items`]: apiError(403, 'forbidden', 'You may not change the items of this list'),
  })
  renderApp(PAGE)

  await userEvent.click(await screen.findByRole('checkbox', { name: 'Mark Buy milk as done' }))
  // Shown as done while the request is still out.
  await waitFor(() => expect(titles()).toEqual(['Bake bread', 'Boil eggs']))
  expect(screen.getByRole('button', { name: 'Done (2)' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()

  answer(apiError(409, 'conflict', 'The item was changed by someone else'))
  expect(await screen.findByRole('alert')).toHaveTextContent('The item was changed by someone else')
  await waitFor(() => expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs']))
  expect(screen.getByRole('button', { name: 'Done (1)' })).toBeInTheDocument()
  // The items are asked for again after a rejection.
  const itemFetches = () =>
    fetches.mock.calls.filter(([request]) => request.method === 'GET' && request.url.endsWith('/items')).length
  await waitFor(() => expect(itemFetches()).toBe(2))

  // The next change clears the message; a rejected addition disappears again.
  await userEvent.type(screen.getByRole('textbox', { name: 'Add an item' }), 'Wash car{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('You may not change the items of this list')
  await waitFor(() => expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs']))
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a viewer sees the list read-only', async () => {
  mockApi(routes({ ...BACKLOG, role: 'viewer', actions: ['read'] }))
  renderApp(PAGE)

  await openItems()
  expect(titles()).toEqual(['Buy milk', 'Bake bread', 'Boil eggs'])
  expect(screen.getByRole('note')).toHaveTextContent('You can read this list, but not change its items.')
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^(Move|Delete|Edit title)/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument()

  // Notes can be read where there are any.
  expect(screen.queryByRole('button', { name: 'Notes of Buy milk' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Notes of Bake bread' }))
  expect(screen.getByText('Sourdough.')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})

test('an AI-only list is read-only for a person, with a notice that agents manage it', async () => {
  // Also for an admin: the API leaves `change_items` out.
  mockApi(routes({ ...BACKLOG, mode: 'ai_only', actions: ['read', 'edit_list', 'administer'] }))
  renderApp(PAGE)

  await openItems()
  expect(screen.getByRole('note')).toHaveTextContent(
    'AI agents manage this list. You can read it, but not change its items.',
  )
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^(Move|Delete|Edit title)/ })).not.toBeInTheDocument()
})

test('items that an agent added or completed carry a marker', async () => {
  mockApi(
    routes(BACKLOG, [
      MILK,
      item(BACKLOG, 'i2', 'Write report', { position: 2, created_by: AGENT }),
      { ...TEA, position: 3, completed_by: AGENT },
      // Reopened: who completed it before does not matter any more.
      item(BACKLOG, 'i5', 'Plan trip', { position: 4, created_by: AGENT, status: 'done', completed_by: AGENT }),
    ]),
  )
  renderApp(PAGE)

  const [milk, report] = within(await openItems()).getAllByRole('listitem')
  expect(within(milk).queryByText(/agent/)).not.toBeInTheDocument()
  expect(within(report).getByText('Added by an agent')).toBeInTheDocument()
  expect(within(report).queryByText('Completed by an agent')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Done (2)' }))
  const [tea, trip] = within(screen.getByRole('list', { name: 'Done items' })).getAllByRole('listitem')
  expect(within(tea).getByText('Completed by an agent')).toBeInTheDocument()
  expect(within(tea).queryByText('Added by an agent')).not.toBeInTheDocument()
  expect(within(trip).getByText('Added by an agent')).toBeInTheDocument()
  expect(within(trip).getByText('Completed by an agent')).toBeInTheDocument()
})

test('an empty list says so, and a list without open items too', async () => {
  const all = routes(BACKLOG, [])
  mockApi(all)
  const { unmount } = renderApp(PAGE)
  expect(await screen.findByText('This list has no items yet.')).toBeInTheDocument()
  unmount()

  all[`GET /api/lists/${BACKLOG.id}/items`] = json([TEA])
  renderApp(PAGE)
  expect(await screen.findByText('Everything is done.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Done (1)' })).toBeInTheDocument()
})

test('a list that does not exist for the user, or is of another organization, is not found', async () => {
  const all = routes()
  all[`GET /api/lists/${BACKLOG.id}`] = apiError(404, 'not_found', 'List not found')
  all[`GET /api/lists/${BACKLOG.id}/items`] = apiError(404, 'not_found', 'List not found')
  mockApi(all)
  const { unmount } = renderApp(PAGE)
  expect(await screen.findByRole('heading', { name: 'List not found' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to Acme' })).toHaveAttribute('href', '/o/acme')
  unmount()

  mockApi(routes())
  renderApp(`/o/beta-works/l/${BACKLOG.id}`)
  expect(await screen.findByRole('heading', { name: 'List not found' })).toBeInTheDocument()
})

test('without access to the project its name is shown, not a link', async () => {
  mockApi({ ...routes(), [`GET /api/orgs/${ACME.id}/projects`]: json([]) })
  renderApp(PAGE)

  await openItems()
  const main = screen.getByRole('main')
  expect(within(main).getByText('Website')).toBeInTheDocument()
  expect(within(main).queryByRole('link', { name: 'Website' })).not.toBeInTheDocument()
})

test('a list on the project page links to its own page', async () => {
  mockApi({
    ...routes(),
    [`GET /api/projects/${WEBSITE.id}`]: json(WEBSITE),
    [`GET /api/projects/${WEBSITE.id}/lists`]: json([BACKLOG]),
  })
  renderApp(`/o/acme/p/${WEBSITE.id}`)

  await userEvent.click(await screen.findByRole('link', { name: 'Backlog' }))
  expect(screen.getByTestId('location')).toHaveTextContent(PAGE)
  expect(await screen.findByRole('heading', { level: 1, name: 'Backlog' })).toBeInTheDocument()
})
