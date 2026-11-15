import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, auditEvent, BETA, CLAUDE_ACTOR, json, mockApi, project, todoList } from '../test/api'
import { renderApp } from '../test/render'

type Routes = Parameters<typeof mockApi>[0]
type Event = Schemas['AuditEventOut']

const WEBSITE = project(ACME, '0190a000-0000-7000-8000-0000000000b1', 'Website')
const BACKLOG = todoList(WEBSITE, '0190a000-0000-7000-8000-0000000000c1', 'Backlog', { mode: 'mixed' })
const LIST_PAGE = `/o/acme/l/${BACKLOG.id}`
const PROJECT_PAGE = `/o/acme/p/${WEBSITE.id}`
const LIST_AUDIT = `GET /api/lists/${BACKLOG.id}/audit`
const PROJECT_AUDIT = `GET /api/projects/${WEBSITE.id}/audit`

// Oldest first here; the API answers newest first.
const CREATED = auditEvent(BACKLOG, 'list.created', { name: 'Backlog', mode: 'mixed' })
const ADDED = auditEvent(BACKLOG, 'item.created', { title: 'Write tests' }, { actor: CLAUDE_ACTOR })
const EDITED = auditEvent(BACKLOG, 'item.updated', {
  title: 'Write more tests',
  changes: { title: { old: 'Write tests', new: 'Write more tests' }, notes: { old: null, new: 'All of them.' } },
})
const COMPLETED = auditEvent(BACKLOG, 'item.completed', { title: 'Write more tests' }, { actor: CLAUDE_ACTOR })
const NEWEST_FIRST = [COMPLETED, EDITED, ADDED, CREATED]

function page(events: Event[], nextCursor: string | null = null): Response {
  return json({ events, next_cursor: nextCursor })
}

function routes(
  list: Schemas['ListOut'] = BACKLOG,
  of: Schemas['ProjectOut'] = WEBSITE,
  audit: Routes[string] = page(NEWEST_FIRST),
): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    [`GET /api/orgs/${ACME.id}/projects`]: json([of]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/projects/${of.id}`]: json(of),
    [`GET /api/projects/${of.id}/lists`]: json([list]),
    [`GET /api/lists/${list.id}`]: json(list),
    [`GET /api/lists/${list.id}/items`]: json([]),
    [LIST_AUDIT]: audit,
    [PROJECT_AUDIT]: audit,
  }
}

/** A route that keeps the query string of every request and answers by it. */
function recordedQueries(answer: (query: URLSearchParams) => Response) {
  const queries: string[] = []
  const route = (request: Request) => {
    const query = new URL(request.url).searchParams
    queries.push(query.toString())
    return answer(query)
  }
  return { queries, route }
}

async function rows() {
  return within(await screen.findByRole('list', { name: 'Activity, newest first' })).getAllByRole('listitem')
}

function sentences(items: HTMLElement[]) {
  return items.map((row) => row.querySelector('p')?.textContent)
}

test('the Activity tab of a list shows who did what, newest first, with a marker and the time', async () => {
  mockApi(routes())
  renderApp(LIST_PAGE)

  // The items are shown first; the log is not asked for.
  const tabs = within(await screen.findByRole('tablist', { name: 'Views of this list' }))
  expect(tabs.getByRole('tab', { name: 'Items' })).toHaveAttribute('aria-selected', 'true')
  expect(tabs.getByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'false')
  expect(await screen.findByText('This list has no items yet.')).toBeInTheDocument()
  expect(screen.getByRole('tabpanel', { name: 'Items' })).toBeInTheDocument()

  await userEvent.click(tabs.getByRole('tab', { name: 'Activity' }))
  expect(tabs.getByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByTestId('location')).toHaveTextContent(`${LIST_PAGE}?tab=activity`)
  expect(screen.queryByText('This list has no items yet.')).not.toBeInTheDocument()

  const items = await rows()
  expect(sentences(items)).toEqual([
    'Claude completed "Write more tests"',
    'Ada Lovelace edited "Write more tests"',
    'Claude added "Write tests"',
    'Ada Lovelace created the list "Backlog"',
  ])
  // An agent and a person are told apart, also without seeing the icon.
  expect(within(items[0]).getByText('AI agent:')).toBeInTheDocument()
  expect(items[0].querySelector('[data-actor-kind]')).toHaveAttribute('data-actor-kind', 'agent')
  expect(within(items[1]).getByText('Person:')).toBeInTheDocument()
  expect(items[1].querySelector('[data-actor-kind]')).toHaveAttribute('data-actor-kind', 'user')
  expect(items[0].querySelector('time')).toHaveAttribute('datetime', COMPLETED.created_at)
  expect(items[0].querySelector('time')).not.toBeEmptyDOMElement()

  // An update shows the changed fields with the old and the new value.
  const [title, notes] = within(items[1]).getAllByRole('definition')
  expect(within(items[1]).getAllByRole('term').map((term) => term.textContent)).toEqual(['Title:', 'Notes:'])
  expect(title).toHaveTextContent('from "Write tests" → to "Write more tests"')
  expect(notes).toHaveTextContent('from nothing → to "All of them."')
  expect(within(items[0]).queryByRole('term')).not.toBeInTheDocument()

  // Back to the items.
  await userEvent.click(tabs.getByRole('tab', { name: 'Items' }))
  expect(await screen.findByText('This list has no items yet.')).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent(LIST_PAGE)
  expect(screen.getByTestId('location')).not.toHaveTextContent('tab=')
})

test('the arrow keys move between the tabs', async () => {
  mockApi(routes())
  renderApp(LIST_PAGE)

  const itemsTab = await screen.findByRole('tab', { name: 'Items' })
  itemsTab.focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: 'Activity' })).toHaveFocus()
  expect(screen.getByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'true')
  expect(await screen.findByRole('tabpanel', { name: 'Activity' })).toBeInTheDocument()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: 'Items' })).toHaveFocus()
  expect(screen.getByRole('tab', { name: 'Items' })).toHaveAttribute('aria-selected', 'true')
})

test('the filters ask the API again; nothing left is said so', async () => {
  const audit = recordedQueries((query) => {
    const byAgents = NEWEST_FIRST.filter((event) => event.actor.kind === 'agent')
    if (query.get('group') === 'sharing') {
      return page([])
    }
    return page(query.get('actor_kind') === 'agent' ? byAgents : NEWEST_FIRST)
  })
  mockApi(routes(BACKLOG, WEBSITE, audit.route))
  renderApp(`${LIST_PAGE}?tab=activity`)

  expect(await rows()).toHaveLength(4)
  expect(audit.queries).toEqual([''])

  const by = screen.getByRole('combobox', { name: 'By' })
  expect(within(by).getAllByRole('option').map((option) => option.textContent)).toEqual(['Everyone', 'Humans', 'Agents'])
  await userEvent.selectOptions(by, 'Agents')
  await screen.findByRole('list', { name: 'Activity, newest first' })
  await expect.poll(async () => sentences(await rows())).toEqual([
    'Claude completed "Write more tests"',
    'Claude added "Write tests"',
  ])
  expect(audit.queries.at(-1)).toBe('actor_kind=agent')

  const changes = screen.getByRole('combobox', { name: 'Changes to' })
  expect(within(changes).getAllByRole('option').map((option) => option.textContent)).toEqual([
    'All changes',
    'Items',
    'Lists',
    'Sharing',
  ])
  await userEvent.selectOptions(changes, 'Sharing')
  expect(await screen.findByText('No activity matches these filters.')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Activity, newest first' })).not.toBeInTheDocument()
  expect(new URLSearchParams(audit.queries.at(-1))).toEqual(new URLSearchParams('actor_kind=agent&group=sharing'))

  await userEvent.selectOptions(by, 'Humans')
  await userEvent.selectOptions(changes, 'Items')
  await rows()
  expect(new URLSearchParams(audit.queries.at(-1))).toEqual(new URLSearchParams('actor_kind=user&group=items'))
})

test('"Load more" asks for the next page with the cursor of the last one', async () => {
  const audit = recordedQueries((query) => {
    if (query.get('cursor') === null) {
      return page([COMPLETED, EDITED], 'cursor-1')
    }
    return query.get('cursor') === 'cursor-1' ? page([ADDED], 'cursor-2') : page([CREATED])
  })
  mockApi(routes(BACKLOG, WEBSITE, audit.route))
  renderApp(`${LIST_PAGE}?tab=activity`)

  expect(await rows()).toHaveLength(2)
  await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
  await expect.poll(async () => (await rows()).length).toBe(3)
  await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
  await expect.poll(async () => sentences(await rows())).toEqual([
    'Claude completed "Write more tests"',
    'Ada Lovelace edited "Write more tests"',
    'Claude added "Write tests"',
    'Ada Lovelace created the list "Backlog"',
  ])
  expect(audit.queries).toEqual(['', 'cursor=cursor-1', 'cursor=cursor-2'])
  // The last page has no cursor: nothing more to load.
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

test('an empty log and a failing one', async () => {
  const api = routes(BACKLOG, WEBSITE, page([]))
  mockApi(api)
  const { unmount } = renderApp(`${LIST_PAGE}?tab=activity`)
  expect(await screen.findByText('Nothing has happened here yet.')).toBeInTheDocument()
  unmount()

  api[LIST_AUDIT] = apiError(403, 'forbidden', 'You may not do this')
  renderApp(`${LIST_PAGE}?tab=activity`)
  expect(await screen.findByRole('alert')).toHaveTextContent('You may not do this')
})

test('someone who is not an admin of the list has no tabs, also with the address of the tab', async () => {
  const asEditor = todoList(WEBSITE, BACKLOG.id, 'Backlog', { role: 'editor', actions: ['read', 'change_items', 'edit_list'] })
  const fetchMock = mockApi(routes(asEditor))
  renderApp(`${LIST_PAGE}?tab=activity`)

  expect(await screen.findByText('This list has no items yet.')).toBeInTheDocument()
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([request]) => request.url.includes('/audit'))).toBe(false)
})

test('the Activity tab of a project names the lists and has the project with the lists', async () => {
  const projectCreated = auditEvent(BACKLOG, 'project.created', { name: 'Website' }, { list_id: null })
  const gone = auditEvent(BACKLOG, 'item.deleted', { title: 'Old news' }, { list_id: '0190a000-0000-7000-8000-0000000000c9' })
  const audit = recordedQueries(() => page([gone, COMPLETED, CREATED, projectCreated]))
  mockApi(routes(BACKLOG, WEBSITE, audit.route))
  renderApp(PROJECT_PAGE)

  const tabs = within(await screen.findByRole('tablist', { name: 'Views of this project' }))
  expect(tabs.getByRole('tab', { name: 'Lists' })).toHaveAttribute('aria-selected', 'true')
  expect(await screen.findByRole('list', { name: 'Lists' })).toBeInTheDocument()
  await userEvent.click(tabs.getByRole('tab', { name: 'Activity' }))
  expect(screen.getByTestId('location')).toHaveTextContent(`${PROJECT_PAGE}?tab=activity`)
  expect(screen.queryByRole('list', { name: 'Lists' })).not.toBeInTheDocument()

  expect(sentences(await rows())).toEqual([
    'Ada Lovelace deleted "Old news"',
    'Claude completed "Write more tests" in the list "Backlog"',
    'Ada Lovelace created the list "Backlog"',
    'Ada Lovelace created the project "Website"',
  ])

  const changes = screen.getByRole('combobox', { name: 'Changes to' })
  await userEvent.selectOptions(changes, 'Project and lists')
  await expect.poll(() => audit.queries.at(-1)).toBe('group=lists')
})

test('a project editor has no Activity tab', async () => {
  const asEditor = project(ACME, WEBSITE.id, 'Website', { role: 'editor' })
  mockApi(routes(BACKLOG, asEditor))
  renderApp(`${PROJECT_PAGE}?tab=activity`)

  expect(await screen.findByRole('list', { name: 'Lists' })).toBeInTheDocument()
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
})
