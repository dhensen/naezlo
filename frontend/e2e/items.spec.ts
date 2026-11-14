import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn } from './helpers.ts'

interface Me {
  organizations: { id: string; slug: string }[]
}

/** A project with one list in the signed-in user's organization, made through the API. */
async function newList(page: Page, mode: 'human_only' | 'ai_only' | 'mixed' = 'human_only') {
  const me = (await (await page.request.get('/api/me')).json()) as Me
  const [organization] = me.organizations
  const project = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name: 'Household' } })
  expect(project.status()).toBe(201)
  const { id: projectId } = (await project.json()) as { id: string }
  const list = await page.request.post(`/api/projects/${projectId}/lists`, { data: { name: 'Groceries', mode } })
  expect(list.status()).toBe(201)
  const { id: listId } = (await list.json()) as { id: string }
  return {
    listId,
    projectUrl: `/o/${organization.slug}/p/${projectId}`,
    listUrl: `/o/${organization.slug}/l/${listId}`,
  }
}

/** The titles of the open items, top to bottom. */
function openTitles(page: Page) {
  return page.getByRole('list', { name: 'Open items' }).getByRole('button', { name: /^Edit title of / })
}

/** Do something and wait until the server has answered the change it causes. */
async function saved(page: Page, method: 'POST' | 'PATCH' | 'DELETE', action: () => Promise<void>) {
  const answered = page.waitForResponse(
    (response) => response.request().method() === method && /\/api\/(items|lists)\//.test(response.url()),
  )
  await action()
  expect((await answered).ok()).toBe(true)
}

test('add, edit, complete, reopen, reorder and delete items; the order survives a reload', async ({ page }) => {
  await signIn(page)
  const { projectUrl, listUrl } = await newList(page)

  // From the project page to the list and its (empty) page.
  await page.goto(projectUrl)
  await page.getByRole('link', { name: 'Groceries' }).click()
  await expect(page).toHaveURL(listUrl)
  await expect(page.getByRole('heading', { level: 1, name: 'Groceries' })).toBeVisible()
  const main = page.getByRole('main')
  await expect(main.getByText('Human only')).toBeVisible()
  await expect(main.getByRole('link', { name: 'Household' })).toHaveAttribute('href', projectUrl)
  await expect(page.getByText('This list has no items yet.')).toBeVisible()

  // Add three items with Enter; the field keeps the focus in between.
  const input = page.getByRole('textbox', { name: 'Add an item' })
  await input.click()
  for (const title of ['Buy milk', 'Bake bread', 'Boil eggs']) {
    await page.keyboard.type(title)
    await page.keyboard.press('Enter')
    await expect(input).toBeFocused()
    await expect(input).toHaveValue('')
  }
  await expect(openTitles(page)).toHaveText(['Buy milk', 'Bake bread', 'Boil eggs'])
  // All three are stored once the last one's controls work.
  await expect(page.getByRole('checkbox', { name: 'Mark Boil eggs as done' })).toBeEnabled()

  // Edit a title in place and give the item notes.
  await page.getByRole('button', { name: 'Edit title of Buy milk' }).click()
  const title = page.getByRole('textbox', { name: 'Title' })
  await expect(title).toBeFocused()
  await title.fill('Buy oat milk')
  await saved(page, 'PATCH', () => title.press('Enter'))
  await expect(openTitles(page)).toHaveText(['Buy oat milk', 'Bake bread', 'Boil eggs'])
  await expect(page.getByRole('button', { name: 'Edit title of Buy oat milk' })).toBeFocused()

  await page.getByRole('button', { name: 'Notes of Buy oat milk' }).click()
  await page.getByRole('textbox', { name: 'Notes of Buy oat milk' }).fill('Two cartons.')
  await saved(page, 'PATCH', () => page.getByRole('button', { name: 'Save notes' }).click())
  await page.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByRole('textbox', { name: 'Notes of Buy oat milk' })).toBeHidden()

  // Reorder with the keyboard: the eggs go to the top, the focus stays on a move button.
  const eggsUp = page.getByRole('button', { name: 'Move Boil eggs up' })
  await eggsUp.focus()
  await saved(page, 'POST', () => page.keyboard.press('Enter'))
  await expect(openTitles(page)).toHaveText(['Buy oat milk', 'Boil eggs', 'Bake bread'])
  await expect(eggsUp).toBeFocused()
  await saved(page, 'POST', () => page.keyboard.press('Enter'))
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Buy oat milk', 'Bake bread'])
  await expect(eggsUp).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Move Boil eggs down' })).toBeFocused()
  // And one down with the mouse.
  await saved(page, 'POST', () => page.getByRole('button', { name: 'Move Buy oat milk down' }).click())
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Bake bread', 'Buy oat milk'])

  // The order, the title and the notes are stored.
  await page.reload()
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Bake bread', 'Buy oat milk'])
  await page.getByRole('button', { name: 'Notes of Buy oat milk' }).click()
  await expect(page.getByRole('textbox', { name: 'Notes of Buy oat milk' })).toHaveValue('Two cartons.')

  // Complete: the item moves to the folded "Done" section, struck through.
  await saved(page, 'PATCH', () => page.getByRole('checkbox', { name: 'Mark Bake bread as done' }).click())
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Buy oat milk'])
  const doneToggle = page.getByRole('button', { name: 'Done (1)' })
  await expect(page.getByRole('list', { name: 'Done items' })).toBeHidden()
  await doneToggle.click()
  const done = page.getByRole('list', { name: 'Done items' })
  const doneTitle = done.getByRole('button', { name: 'Edit title of Bake bread' })
  await expect(doneTitle).toHaveCSS('text-decoration-line', 'line-through')
  await expect(done.getByRole('checkbox', { name: 'Mark Bake bread as done' })).toBeChecked()
  await page.reload()
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Buy oat milk'])
  await page.getByRole('button', { name: 'Done (1)' }).click()

  // Reopen: back between the others, where it was.
  await saved(page, 'PATCH', () => page.getByRole('checkbox', { name: 'Mark Bake bread as done' }).click())
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Bake bread', 'Buy oat milk'])
  await expect(page.getByRole('button', { name: /^Done \(/ })).toBeHidden()

  // Delete asks in the row first.
  await page.getByRole('button', { name: 'Delete Boil eggs' }).click()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(openTitles(page)).toHaveText(['Boil eggs', 'Bake bread', 'Buy oat milk'])
  await page.getByRole('button', { name: 'Delete Boil eggs' }).click()
  await saved(page, 'DELETE', () => page.getByRole('button', { name: 'Yes, delete' }).click())
  await expect(openTitles(page)).toHaveText(['Bake bread', 'Buy oat milk'])

  await page.reload()
  await expect(openTitles(page)).toHaveText(['Bake bread', 'Buy oat milk'])
  // The project page counts the open items.
  await page.getByRole('main').getByRole('link', { name: 'Household' }).click()
  await expect(page.getByRole('list', { name: 'Lists' }).getByRole('listitem')).toContainText('2 open items')
})

test('a change that the server rejects is undone and explained', async ({ page }) => {
  await signIn(page)
  const { listId, listUrl } = await newList(page)
  const made = await page.request.post(`/api/lists/${listId}/items`, { data: { title: 'Buy milk' } })
  expect(made.status()).toBe(201)
  await page.goto(listUrl)
  await expect(openTitles(page)).toHaveText(['Buy milk'])

  // The list becomes AI-only behind the page's back: people may not change its items now.
  const patched = await page.request.patch(`/api/lists/${listId}`, { data: { mode: 'ai_only' } })
  expect(patched.ok()).toBe(true)

  await page.getByRole('checkbox', { name: 'Mark Buy milk as done' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('alert')).not.toBeEmpty()
  await expect(openTitles(page)).toHaveText(['Buy milk'])
  await expect(page.getByRole('checkbox', { name: 'Mark Buy milk as done' })).not.toBeChecked()

  // After a reload the page knows: read-only, with the notice.
  await page.reload()
  await expect(page.getByRole('note')).toHaveText('AI agents manage this list. You can read it, but not change its items.')
  await expect(page.getByRole('list', { name: 'Open items' })).toContainText('Buy milk')
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Add an item' })).toBeHidden()
  await expect(page.getByRole('button', { name: /^(Move|Delete|Edit title)/ })).toHaveCount(0)
})
