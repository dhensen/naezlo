import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn } from './helpers.ts'

interface Me {
  organizations: { id: string; slug: string }[]
}

/** A mixed list with two items and an agent that may change them, made through the API. */
async function sharedList(page: Page) {
  const me = (await (await page.request.get('/api/me')).json()) as Me
  const [organization] = me.organizations
  const created = async (url: string, data: object) => {
    const response = await page.request.post(url, { data })
    expect(response.status()).toBe(201)
    return ((await response.json()) as { id: string }).id
  }
  const agentId = await created(`/api/orgs/${organization.id}/agents`, { name: 'Robo' })
  const projectId = await created(`/api/orgs/${organization.id}/projects`, { name: 'Household' })
  const listId = await created(`/api/projects/${projectId}/lists`, { name: 'Groceries', mode: 'mixed' })
  const grant = await page.request.put(`/api/lists/${listId}/grants`, {
    data: { principal_kind: 'agent', principal_id: agentId, role: 'editor' },
  })
  expect(grant.ok()).toBe(true)
  const milkId = await created(`/api/lists/${listId}/items`, { title: 'Buy milk' })
  const breadId = await created(`/api/lists/${listId}/items`, { title: 'Bake bread' })
  return {
    breadId,
    milkId,
    projectUrl: `/o/${organization.slug}/p/${projectId}`,
    listUrl: `/o/${organization.slug}/l/${listId}`,
  }
}

/** Do something and wait until the server has answered the change it causes. */
async function saved(page: Page, method: 'PUT' | 'PATCH' | 'DELETE', action: () => Promise<unknown>) {
  const answered = page.waitForResponse(
    (response) => response.request().method() === method && /\/api\/(items|lists)\//.test(response.url()),
  )
  await action()
  expect((await answered).ok()).toBe(true)
}

test('items are picked up and given to an agent; where assignment is required only the assignee completes', async ({
  page,
}) => {
  const user = await signIn(page)
  const { breadId, projectUrl, listUrl } = await sharedList(page)

  // Without the setting an item is assigned freely and anyone can tick it off.
  await page.goto(listUrl)
  const milk = page.getByRole('combobox', { name: 'Assignee of Buy milk' })
  const bread = page.getByRole('combobox', { name: 'Assignee of Bake bread' })
  await expect(milk).toHaveValue('')
  await expect(milk.getByRole('option')).toHaveText(['Unassigned', `${user.name} (you)`, 'Robo (agent)'])
  await expect(page.getByRole('checkbox', { name: 'Mark Bake bread as done' })).toBeVisible()
  await saved(page, 'PUT', () => bread.selectOption({ label: 'Robo (agent)' }))
  await expect(bread.locator('option:checked')).toHaveText('Robo (agent)')

  // Switch the setting on in the list's dialog on the project page.
  await page.goto(projectUrl)
  await page.getByRole('button', { name: 'Edit Groceries' }).click()
  const dialog = page.getByRole('dialog', { name: 'Edit list' })
  await dialog.getByRole('checkbox', { name: 'Assignment required' }).check()
  await saved(page, 'PATCH', () => dialog.getByRole('button', { name: 'Save' }).click())
  await expect(dialog).toBeHidden()

  // Now nothing can be ticked off until it is picked up; the agent's item stays the agent's.
  await page.goto(listUrl)
  await expect(page.getByRole('main').getByText('Assignment required')).toBeVisible()
  await expect(page.getByRole('note')).toContainText('Only the assignee can complete an item in this list.')
  await expect(bread.locator('option:checked')).toHaveText('Robo (agent)')
  await expect(page.getByRole('checkbox', { name: 'Mark Buy milk as done' })).toBeHidden()
  await expect(page.getByRole('checkbox', { name: 'Mark Bake bread as done' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'Pick up Bake bread' })).toBeHidden()
  // The server refuses too, whatever the page shows.
  const refused = await page.request.patch(`/api/items/${breadId}`, { data: { status: 'done' } })
  expect(refused.status()).toBe(409)
  expect(((await refused.json()) as { code: string }).code).toBe('item_assigned_to_other')

  await saved(page, 'PUT', () => page.getByRole('button', { name: 'Pick up Buy milk' }).click())
  await expect(milk.locator('option:checked')).toHaveText(`${user.name} (you)`)
  await expect(page.getByRole('button', { name: 'Pick up Buy milk' })).toBeHidden()
  await saved(page, 'PATCH', () => page.getByRole('checkbox', { name: 'Mark Buy milk as done' }).click())
  await expect(page.getByRole('button', { name: 'Done (1)' })).toBeVisible()

  // Taking the agent's item over is a deliberate step: assign it to yourself first.
  await saved(page, 'PUT', () => bread.selectOption({ label: `${user.name} (you)` }))
  await expect(page.getByRole('checkbox', { name: 'Mark Bake bread as done' })).toBeVisible()
  await saved(page, 'DELETE', () => bread.selectOption({ label: 'Unassigned' }))
  await expect(page.getByRole('button', { name: 'Pick up Bake bread' })).toBeVisible()

  // It is all stored, and the activity log tells it.
  await page.reload()
  await expect(bread).toHaveValue('')
  await page.getByRole('tab', { name: 'Activity' }).click()
  const log = page.getByRole('main')
  await expect(log.getByText('picked up "Buy milk"')).toBeVisible()
  await expect(log.getByText('assigned "Bake bread" to Robo')).toBeVisible()
  await expect(log.getByText('released "Bake bread"')).toBeVisible()
  await expect(log.getByText('Assignment required:')).toBeVisible()
})
