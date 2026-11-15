import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn } from './helpers.ts'

// A small phone, held upright, with a finger instead of a mouse.
test.use({ viewport: { width: 375, height: 667 }, hasTouch: true })

interface Me {
  organizations: { id: string; slug: string }[]
}

const LONG_WORD = 'Supercalifragilisticexpialidocious-and-then-some-more-without-any-space'

/** A project with a list of items that is longer than the screen, made through the API. */
async function longList(page: Page) {
  const me = (await (await page.request.get('/api/me')).json()) as Me
  const [organization] = me.organizations
  const created = async (url: string, data: object) => {
    const response = await page.request.post(url, { data })
    expect(response.status()).toBe(201)
    return ((await response.json()) as { id: string }).id
  }
  const projectId = await created(`/api/orgs/${organization.id}/projects`, { name: 'Household' })
  const listId = await created(`/api/projects/${projectId}/lists`, { name: 'Groceries' })
  for (const title of ['Buy milk', LONG_WORD, ...Array.from({ length: 12 }, (_, index) => `Chore ${index + 1}`)]) {
    await created(`/api/lists/${listId}/items`, { title })
  }
  return { slug: organization.slug, listId }
}

/** Nothing is wider than the screen: the page does not scroll sideways. */
async function expectNoSidewaysScroll(page: Page) {
  // As text: the specs are type-checked without the DOM library.
  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBe(0)
}

test('on a phone the projects are on the start page and a list is worked through with a thumb', async ({ page }) => {
  await signIn(page)
  await longList(page)
  await page.reload()

  // The sidebar is closed: the start page itself leads to the project and its list.
  await expect(page.getByRole('navigation', { name: 'Projects' })).toBeHidden()
  await page.getByRole('list', { name: 'Projects of this organization' }).getByRole('link', { name: 'Household' }).tap()
  await page.getByRole('link', { name: 'Groceries' }).tap()
  await expect(page.getByRole('heading', { level: 1, name: 'Groceries' })).toBeVisible()

  // A title without a space wraps instead of widening the page.
  const items = page.getByRole('list', { name: 'Open items' })
  await expect(items.getByRole('button', { name: `Edit title of ${LONG_WORD}` })).toBeVisible()
  await expectNoSidewaysScroll(page)

  // Fields are 16px, or Safari zooms in when one gets the focus.
  for (const field of [page.getByLabel('Add an item'), page.getByRole('combobox', { name: 'Assignee of Buy milk' })]) {
    await expect(field).toHaveCSS('font-size', '16px')
  }

  // What is pressed is big enough for a thumb.
  for (const target of [
    page.getByRole('checkbox', { name: 'Mark Buy milk as done' }).locator('xpath=..'),
    page.getByRole('button', { name: 'Notes of Buy milk' }),
    page.getByRole('button', { name: 'More actions for Buy milk' }),
    page.getByRole('button', { name: 'Open navigation' }),
  ]) {
    const box = await target.boundingBox()
    expect(box?.width).toBeGreaterThanOrEqual(36)
    expect(box?.height).toBeGreaterThanOrEqual(36)
  }

  // Moving and deleting wait behind "More".
  await expect(page.getByRole('button', { name: 'Delete Buy milk' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'Move Buy milk down' })).toBeHidden()
  await page.getByRole('button', { name: 'More actions for Buy milk' }).tap()
  await page.getByRole('button', { name: 'Move Buy milk down' }).tap()
  await expect(items.getByRole('listitem').nth(1)).toContainText('Buy milk')
  await page.getByRole('button', { name: 'Delete Buy milk' }).tap()
  await page.getByRole('button', { name: 'Yes, delete' }).tap()
  await expect(items.getByText('Buy milk')).toBeHidden()

  await page.getByRole('checkbox', { name: 'Mark Chore 1 as done' }).tap()
  await expect(page.getByRole('button', { name: 'Done (1)' })).toBeVisible()
})

test('on a phone the navigation drawer opens where the page is scrolled to', async ({ page }) => {
  await signIn(page)
  const { slug, listId } = await longList(page)
  await page.goto(`/o/${slug}/l/${listId}`)
  await expect(page.getByRole('button', { name: 'Done' })).toBeHidden()
  await page.getByText('Chore 12').scrollIntoViewIfNeeded()
  expect(await page.evaluate<number>('window.scrollY')).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Open navigation' }).tap()
  const sidebar = page.getByRole('navigation', { name: 'Projects' })
  await expect(sidebar.getByRole('link', { name: 'Household' })).toBeInViewport()
  await expect(page.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Settings' })).toBeInViewport()
  await expectNoSidewaysScroll(page)

  await sidebar.getByRole('link', { name: 'Household' }).tap()
  await expect(page.getByRole('heading', { level: 1, name: 'Household' })).toBeVisible()
  await expect(sidebar).toBeHidden()
})

test('on a phone the settings and a dialog fit the screen', async ({ page }) => {
  await signIn(page)
  const { slug } = await longList(page)

  await page.goto(`/o/${slug}/settings`)
  await expect(page.getByRole('button', { name: 'Leave organization' })).toBeInViewport()
  await expectNoSidewaysScroll(page)

  await page.goto(`/o/${slug}`)
  await page.getByRole('button', { name: 'Create a project' }).tap()
  const dialog = page.getByRole('dialog', { name: 'New project' })
  await expect(dialog.getByLabel('Name')).toBeInViewport()
  await expect(dialog.getByRole('button', { name: 'Create' })).toBeInViewport()
  await expectNoSidewaysScroll(page)
})
