import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import { serverName } from '../agents/connect'
import type { Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, BETA, CLAUDE_AGENT, config, json, MCP_URL, mockApi } from '../test/api'
import { renderApp } from '../test/render'

type Agent = Schemas['AgentOut']
type Routes = Parameters<typeof mockApi>[0]

const SERVER = serverName()
const AGENTS = `/api/orgs/${ACME.id}/agents`
const CODEX: Agent = {
  ...CLAUDE_AGENT,
  id: '0190a000-0000-7000-8000-0000000000f2',
  name: 'Codex',
  description: 'Works on the backlog.',
  project_count: 1,
  list_count: 2,
}

function routes(agents: Agent[], extra: Routes = {}): Routes {
  return {
    'GET /api/me': json(ADA_IN_ORGS),
    'GET /api/config': config(),
    [`GET /api/orgs/${ACME.id}/projects`]: json([]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET ${AGENTS}`]: json(agents),
    [`GET /api/orgs/${BETA.id}/agents`]: json([CODEX]),
    ...extra,
  }
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

test('lists the agents with their description and what they can access', async () => {
  mockApi(routes([CLAUDE_AGENT, CODEX, { ...CODEX, id: 'f3', name: 'Scout', description: null, list_count: 1 }]))
  renderApp('/o/acme/agents')

  const list = await screen.findByRole('list', { name: 'Agents' })
  const [claude, codex, scout] = within(list).getAllByRole('listitem')
  expect(within(claude).getByRole('heading', { name: 'Claude' })).toBeInTheDocument()
  expect(claude).toHaveTextContent('Nothing shared with it yet')
  expect(codex).toHaveTextContent('Works on the backlog.')
  expect(codex).toHaveTextContent('1 project, 2 lists')
  expect(scout).toHaveTextContent('1 project, 1 list')
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

test('the sidebar links to the agents page', async () => {
  mockApi(routes([]))
  const user = userEvent.setup()
  renderApp('/o/acme')

  await user.click(await screen.findByRole('link', { name: 'Agents' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Agents' })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('/o/acme/agents')
  expect(await screen.findByText(/No agents yet/)).toBeInTheDocument()
})

test('a member sees the agents without any controls', async () => {
  mockApi(routes([]))
  renderApp('/o/beta-works/agents')

  expect(await screen.findByRole('heading', { name: 'Codex' })).toBeInTheDocument()
  expect(screen.getByText(/Only owners and admins can add, change and connect agents/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'New agent' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Connect|Edit|Delete/ })).not.toBeInTheDocument()
})

test('creating the first agent opens the connect panel and notes the new default mode', async () => {
  const create = recorded(() => json(CLAUDE_AGENT, 201))
  mockApi(routes([], { [`POST ${AGENTS}`]: create.route }))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'New agent' }))
  const form = screen.getByRole('dialog', { name: 'New agent' })
  await user.type(within(form).getByLabelText('Name'), 'Claude')
  await user.type(within(form).getByLabelText('Description (optional)'), '  ')
  await user.click(within(form).getByRole('button', { name: 'Create' }))

  const panel = await screen.findByRole('dialog', { name: 'Connect Claude' })
  expect(create.bodies).toEqual([{ name: 'Claude', description: null }])
  expect(within(panel).getByRole('note')).toHaveTextContent('new lists default to Mixed')
  expect(await within(panel).findByLabelText('MCP server URL')).toHaveTextContent(MCP_URL)
  expect(screen.queryByRole('dialog', { name: 'New agent' })).not.toBeInTheDocument()

  // The note stays on the page, and the agent is in the list.
  await user.click(within(panel).getByRole('button', { name: 'Done' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('new lists default to Mixed')
  expect(within(screen.getByRole('list', { name: 'Agents' })).getByRole('heading', { name: 'Claude' })).toBeInTheDocument()
})

test('a second agent gets the connect panel without the note', async () => {
  mockApi(routes([CLAUDE_AGENT], { [`POST ${AGENTS}`]: json(CODEX, 201) }))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'New agent' }))
  await user.type(screen.getByLabelText('Name'), 'Codex')
  await user.click(screen.getByRole('button', { name: 'Create' }))

  await screen.findByRole('dialog', { name: 'Connect Codex' })
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

test('a taken name is shown in the form', async () => {
  mockApi(
    routes([CLAUDE_AGENT], {
      [`POST ${AGENTS}`]: apiError(409, 'agent_name_taken', 'This organization already has an agent "Claude"'),
    }),
  )
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'New agent' }))
  await user.type(screen.getByLabelText('Name'), 'Claude')
  await user.click(screen.getByRole('button', { name: 'Create' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('This organization already has an agent "Claude"')
  expect(screen.getByRole('dialog', { name: 'New agent' })).toBeInTheDocument()
})

test('the connect panel has the command or settings for each tool, and the steps after it', async () => {
  mockApi(routes([CLAUDE_AGENT]))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'Connect Claude' }))
  const panel = screen.getByRole('dialog', { name: 'Connect Claude' })
  expect(await within(panel).findByLabelText('MCP server URL')).toHaveTextContent(MCP_URL)
  expect(within(panel).queryByRole('note')).not.toBeInTheDocument()
  const names = within(panel)
    .getAllByRole('tab')
    .map((tab) => tab.textContent)
  expect(names).toEqual(['Claude Code', 'Claude desktop / claude.ai', 'Codex'])

  // Claude Code is shown first.
  expect(within(panel).getByRole('tab', { name: 'Claude Code' })).toHaveAttribute('aria-selected', 'true')
  const tabPanel = within(panel).getByRole('tabpanel')
  expect(within(tabPanel).getByLabelText('Command')).toHaveTextContent(
    `claude mcp add --transport http ${SERVER} ${MCP_URL}`,
  )
  expect(tabPanel).toHaveTextContent('type /mcp')
  expect(tabPanel).toHaveTextContent('On the consent screen, pick the agent Claude')
  expect(tabPanel).toHaveTextContent('Share a project or a list with Claude')

  await user.click(within(panel).getByRole('tab', { name: 'Claude desktop / claude.ai' }))
  expect(within(tabPanel).getByLabelText('Remote MCP server URL')).toHaveTextContent(MCP_URL)
  expect(tabPanel).toHaveTextContent('Add custom connector')
  expect(tabPanel).toHaveTextContent('On the consent screen, pick the agent Claude')

  // The arrow keys move between the tabs.
  await user.keyboard('{ArrowRight}')
  expect(within(panel).getByRole('tab', { name: 'Codex' })).toHaveFocus()
  expect(within(tabPanel).getByLabelText('Command')).toHaveTextContent(`codex mcp add ${SERVER} --url ${MCP_URL}`)
  const toml = within(tabPanel).getByLabelText('~/.codex/config.toml')
  expect(toml.textContent).toBe(`[mcp_servers.${SERVER}]\nurl = "${MCP_URL}"`)
  expect(tabPanel).toHaveTextContent(`codex mcp login ${SERVER}`)
  expect(tabPanel).toHaveTextContent('Share a project or a list with Claude')
})

test('the copy button puts the URL on the clipboard', async () => {
  mockApi(routes([CLAUDE_AGENT]))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'Connect Claude' }))
  const copy = await screen.findByRole('button', { name: 'Copy MCP server URL' })
  await user.click(copy)

  await waitFor(() => expect(copy).toHaveTextContent('Copied'))
  expect(await navigator.clipboard.readText()).toBe(MCP_URL)
})

test('edit sends only what changed', async () => {
  const update = recorded((body: Partial<Agent>) => json({ ...CODEX, ...body }))
  mockApi(routes([CLAUDE_AGENT, CODEX], { [`PATCH ${AGENTS}/${CODEX.id}`]: update.route }))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'Edit Codex' }))
  const dialog = screen.getByRole('dialog', { name: 'Edit agent' })
  expect(within(dialog).getByLabelText('Description (optional)')).toHaveValue('Works on the backlog.')
  await user.clear(within(dialog).getByLabelText('Name'))
  await user.type(within(dialog).getByLabelText('Name'), 'Codex CLI')
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('heading', { name: 'Codex CLI' })).toBeInTheDocument()
  expect(update.bodies).toEqual([{ name: 'Codex CLI' }])
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  // Removing the description sends null.
  await user.click(screen.getByRole('button', { name: 'Edit Codex CLI' }))
  await user.clear(screen.getByLabelText('Description (optional)'))
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(update.bodies).toHaveLength(2))
  expect(update.bodies[1]).toEqual({ description: null })
})

test('delete asks in the row first', async () => {
  const remove = recorded(() => new Response(null, { status: 204 }))
  mockApi(routes([CLAUDE_AGENT, CODEX], { [`DELETE ${AGENTS}/${CODEX.id}`]: remove.route }))
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'Delete Codex' }))
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(remove.bodies).toHaveLength(0)
  expect(screen.getByRole('heading', { name: 'Codex' })).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Delete Codex' }))
  await user.click(screen.getByRole('button', { name: 'Yes, delete' }))

  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Codex' })).not.toBeInTheDocument())
  expect(remove.bodies).toHaveLength(1)
  expect(screen.getByRole('heading', { name: 'Claude' })).toBeInTheDocument()
})

test('a failed delete shows the error and keeps the agent', async () => {
  mockApi(
    routes([CLAUDE_AGENT], {
      [`DELETE ${AGENTS}/${CLAUDE_AGENT.id}`]: apiError(403, 'forbidden', 'Only owners and admins can do this'),
    }),
  )
  const user = userEvent.setup()
  renderApp('/o/acme/agents')

  await user.click(await screen.findByRole('button', { name: 'Delete Claude' }))
  await user.click(screen.getByRole('button', { name: 'Yes, delete' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Only owners and admins can do this')
  expect(screen.getByRole('heading', { name: 'Claude' })).toBeInTheDocument()
})

test('the server name is the product name in a form the tools accept', () => {
  expect(serverName('My Todo App!')).toBe('my-todo-app')
  expect(serverName('···')).toBe('todos')
  expect(SERVER).toMatch(/^[a-z0-9-]+$/)
})
