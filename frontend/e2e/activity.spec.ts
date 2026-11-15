import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn } from './helpers.ts'

interface Me {
  organizations: { id: string; slug: string }[]
}

/** A project with one list in the signed-in user's organization, made through the API. */
async function newList(page: Page) {
  const me = (await (await page.request.get('/api/me')).json()) as Me
  const [organization] = me.organizations
  const project = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name: 'Household' } })
  expect(project.status()).toBe(201)
  const { id: projectId } = (await project.json()) as { id: string }
  const list = await page.request.post(`/api/projects/${projectId}/lists`, { data: { name: 'Groceries' } })
  expect(list.status()).toBe(201)
  const { id: listId } = (await list.json()) as { id: string }
  return {
    projectUrl: `/o/${organization.slug}/p/${projectId}`,
    listUrl: `/o/${organization.slug}/l/${listId}`,
  }
}

/** Do something and wait until the server has answered the change it causes. */
async function saved(page: Page, method: 'POST' | 'PATCH' | 'DELETE', action: () => Promise<void>) {
  const answered = page.waitForResponse(
    (response) => response.request().method() === method && /\/api\/(items|lists)\//.test(response.url()),
  )
  await action()
  expect((await answered).ok()).toBe(true)
}

function activity(page: Page) {
  return page.getByRole('list', { name: 'Activity, newest first' }).getByRole('listitem')
}

test('item changes show up in the Activity tab of the list and of the project, newest first', async ({ page }) => {
  const user = await signIn(page)
  const { projectUrl, listUrl } = await newList(page)
  await page.goto(listUrl)

  // Add two items, rename one and complete the other.
  const input = page.getByRole('textbox', { name: 'Add an item' })
  for (const title of ['Buy milk', 'Bake bread']) {
    await input.fill(title)
    await saved(page, 'POST', () => input.press('Enter'))
  }
  await page.getByRole('button', { name: 'Edit title of Buy milk' }).click()
  const title = page.getByRole('textbox', { name: 'Title' })
  await title.fill('Buy oat milk')
  await saved(page, 'PATCH', () => title.press('Enter'))
  await saved(page, 'PATCH', () => page.getByRole('checkbox', { name: 'Mark Bake bread as done' }).click())

  // The list's log: the newest change on top, the creation of the list at the bottom.
  await page.getByRole('tab', { name: 'Activity' }).click()
  await expect(page).toHaveURL(`${listUrl}?tab=activity`)
  await expect(page.getByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('textbox', { name: 'Add an item' })).toBeHidden()
  await expect(activity(page)).toContainText([
    `${user.name} completed "Bake bread"`,
    `${user.name} edited "Buy oat milk"`,
    `${user.name} added "Bake bread"`,
    `${user.name} added "Buy milk"`,
    `${user.name} created the list "Groceries"`,
  ])
  await expect(activity(page)).toHaveCount(5)
  // A person did all of it, and the update says what changed.
  await expect(activity(page).first().getByText('Person:')).toBeAttached()
  await expect(activity(page).first().locator('time')).not.toBeEmpty()
  const edited = activity(page).nth(1)
  await expect(edited.getByRole('term')).toHaveText('Title:')
  await expect(edited.getByRole('definition')).toContainText('"Buy milk"')
  await expect(edited.getByRole('definition')).toContainText('"Buy oat milk"')

  // Filters: only the item changes, only the list's own, and nothing by agents.
  const changes = page.getByRole('combobox', { name: 'Changes to' })
  await changes.selectOption('Items')
  await expect(activity(page)).toHaveCount(4)
  await changes.selectOption('Lists')
  await expect(activity(page)).toHaveText([new RegExp(`${user.name} created the list "Groceries"`)])
  await changes.selectOption('Sharing')
  await expect(page.getByText('No activity matches these filters.')).toBeVisible()
  await changes.selectOption('All changes')
  await expect(activity(page)).toHaveCount(5)

  const by = page.getByRole('combobox', { name: 'By' })
  await by.selectOption('Agents')
  await expect(page.getByText('No activity matches these filters.')).toBeVisible()
  await expect(activity(page)).toHaveCount(0)
  await by.selectOption('Humans')
  await expect(activity(page)).toHaveCount(5)

  // The tab is part of the address: a reload stays on it.
  await page.reload()
  await expect(activity(page)).toHaveCount(5)
  await page.getByRole('tab', { name: 'Items' }).click()
  await expect(page).toHaveURL(listUrl)
  await expect(page.getByRole('textbox', { name: 'Add an item' })).toBeVisible()

  // The project's log has the same events, with the list they are in, and the project's own.
  await page.goto(projectUrl)
  await page.getByRole('tab', { name: 'Activity' }).click()
  await expect(activity(page)).toContainText([
    `${user.name} completed "Bake bread" in the list "Groceries"`,
    `${user.name} edited "Buy oat milk" in the list "Groceries"`,
    `${user.name} added "Bake bread" in the list "Groceries"`,
    `${user.name} added "Buy milk" in the list "Groceries"`,
    `${user.name} created the list "Groceries"`,
    `${user.name} created the project "Household"`,
  ])
  await page.getByRole('combobox', { name: 'By' }).selectOption('Agents')
  await expect(page.getByText('No activity matches these filters.')).toBeVisible()
})

test('"Load more" brings the older events', async ({ page }) => {
  const user = await signIn(page)
  const { listUrl } = await newList(page)
  const listId = listUrl.split('/').at(-1)
  // 54 item events and the creation of the list: more than one page of 50.
  for (let number = 1; number <= 54; number += 1) {
    const made = await page.request.post(`/api/lists/${listId}/items`, { data: { title: `Item ${number}` } })
    expect(made.status()).toBe(201)
  }

  await page.goto(`${listUrl}?tab=activity`)
  await expect(activity(page)).toHaveCount(50)
  await expect(activity(page).first()).toContainText(`${user.name} added "Item 54"`)
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(activity(page)).toHaveCount(55)
  await expect(activity(page).last()).toContainText(`${user.name} created the list "Groceries"`)
  await expect(page.getByRole('button', { name: 'Load more' })).toBeHidden()
})
