import { expect, test } from '@playwright/test'

import { signIn } from './helpers.ts'

test('create an agent, see how to connect it, and delete it', async ({ page }) => {
  await signIn(page)
  const { mcp_url: mcpUrl } = (await (await page.request.get('/api/config')).json()) as { mcp_url: string }
  expect(mcpUrl).toMatch(/^http.+\/mcp$/)

  await page.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Agents' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Agents' })).toBeVisible()
  await expect(page.getByText('No agents yet.')).toBeVisible()

  // Creating the first agent opens the connect panel.
  await page.getByRole('button', { name: 'New agent' }).click()
  const form = page.getByRole('dialog', { name: 'New agent' })
  await form.getByLabel('Name').fill('Claude')
  await form.getByLabel('Description (optional)').fill('Keeps the backlog tidy.')
  await form.getByRole('button', { name: 'Create' }).click()

  const panel = page.getByRole('dialog', { name: 'Connect Claude' })
  await expect(panel.getByLabel('MCP server URL', { exact: true })).toHaveText(mcpUrl)
  await expect(panel.getByRole('button', { name: 'Copy MCP server URL' })).toBeVisible()
  await expect(panel.getByRole('note')).toContainText('new lists default to Mixed')
  await expect(panel.getByRole('tab')).toHaveText(['Claude Code', 'Claude desktop / claude.ai', 'Codex'])
  const tabPanel = panel.getByRole('tabpanel')
  await expect(tabPanel.getByLabel('Command', { exact: true })).toContainText('claude mcp add --transport http ')
  await expect(tabPanel.getByLabel('Command', { exact: true })).toContainText(mcpUrl)
  await expect(tabPanel).toContainText('pick the agent Claude')
  await panel.getByRole('tab', { name: 'Claude desktop / claude.ai' }).click()
  await expect(tabPanel.getByLabel('Remote MCP server URL', { exact: true })).toHaveText(mcpUrl)
  await panel.getByRole('tab', { name: 'Codex' }).click()
  await expect(tabPanel.getByLabel('Command', { exact: true })).toContainText(`--url ${mcpUrl}`)
  await expect(tabPanel.getByLabel('~/.codex/config.toml', { exact: true })).toContainText(`url = "${mcpUrl}"`)
  await panel.getByRole('button', { name: 'Done' }).click()
  await expect(panel).toBeHidden()

  // The agent is listed, and the note about the default mode stays.
  const agents = page.getByRole('list', { name: 'Agents' })
  const row = agents.getByRole('listitem').filter({ hasText: 'Claude' })
  await expect(row).toContainText('Keeps the backlog tidy.')
  await expect(row).toContainText('Nothing shared with it yet')
  await expect(page.getByRole('note')).toContainText('new lists default to Mixed')

  // A new list is now Mixed by default, and sharing it with the agent shows in its row.
  await page.getByRole('button', { name: 'New project' }).click()
  const projectForm = page.getByRole('dialog', { name: 'New project' })
  await projectForm.getByLabel('Name').fill('Website')
  await projectForm.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Website' })).toBeVisible()
  await page.getByRole('button', { name: 'New list' }).click()
  const listForm = page.getByRole('dialog', { name: 'New list' })
  await expect(listForm.getByRole('radio', { name: 'Mixed' })).toBeChecked()
  await listForm.getByLabel('Name').fill('Backlog')
  await listForm.getByRole('button', { name: 'Create' }).click()
  await expect(listForm).toBeHidden()
  await page.getByRole('button', { name: 'Share' }).click()
  const share = page.getByRole('dialog', { name: 'Share Website' })
  await share.getByRole('combobox', { name: 'Person or agent' }).selectOption({ label: 'Claude' })
  await share.getByRole('button', { name: 'Add' }).click()
  await expect(share.getByRole('combobox', { name: 'Role of Claude' })).toBeVisible()
  await share.getByRole('button', { name: 'Done' }).click()
  await expect(share).toBeHidden()

  await page.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Agents' }).click()
  await expect(row).toContainText('1 project, 1 list')

  // The panel opens again from the row; the agent can be renamed and deleted.
  await row.getByRole('button', { name: 'Connect Claude' }).click()
  await expect(panel.getByLabel('MCP server URL', { exact: true })).toHaveText(mcpUrl)
  await expect(panel.getByRole('note')).toBeHidden()
  await panel.getByRole('button', { name: 'Done' }).click()

  await row.getByRole('button', { name: 'Edit Claude' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit agent' })
  await edit.getByLabel('Name').fill('Claude Code')
  await edit.getByRole('button', { name: 'Save' }).click()
  await expect(agents.getByRole('heading', { name: 'Claude Code' })).toBeVisible()

  await agents.getByRole('button', { name: 'Delete Claude Code' }).click()
  await agents.getByRole('button', { name: 'Yes, delete' }).click()
  await expect(page.getByText('No agents yet.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('No agents yet.')).toBeVisible()
})
