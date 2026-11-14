import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn } from './helpers.ts'

interface Organization {
  id: string
  name: string
  slug: string
}

/** The signed-in user's organizations, from the API (the page's session cookie is used). */
async function organizations(page: Page): Promise<Organization[]> {
  const response = await page.request.get('/api/me')
  expect(response.ok()).toBe(true)
  const me = (await response.json()) as { organizations: Organization[] }
  return me.organizations
}

async function switchTo(page: Page, from: string, to: string): Promise<void> {
  await page.getByRole('button', { name: `Organization: ${from}` }).click()
  await page.getByRole('list', { name: 'Organizations' }).getByRole('link', { name: to }).click()
  await expect(page.getByRole('button', { name: `Organization: ${to}` })).toBeVisible()
}

test('create a second organization and switch between the two', async ({ page }) => {
  const user = await signIn(page)
  const [first] = await organizations(page)
  await expect(page).toHaveURL(`/o/${first.slug}`)

  const sidebar = page.getByRole('navigation', { name: 'Projects' })
  await expect(sidebar.getByText('No projects yet.')).toBeVisible()

  // A project in the first organization, to tell the two sidebars apart.
  const created = await page.request.post(`/api/orgs/${first.id}/projects`, { data: { name: 'Moon landing' } })
  expect(created.status()).toBe(201)
  await page.reload()
  await expect(sidebar.getByRole('link', { name: 'Moon landing' })).toBeVisible()

  // Create the second organization through the switcher: the app switches to it.
  const secondName = `Second ${user.email}`
  await page.getByRole('button', { name: `Organization: ${user.organizationName}` }).click()
  await page.getByRole('button', { name: 'New organization' }).click()
  const dialog = page.getByRole('dialog', { name: 'New organization' })
  await dialog.getByLabel('Name').fill(secondName)
  await dialog.getByRole('button', { name: 'Create' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: `Organization: ${secondName}` })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: secondName })).toBeVisible()
  const second = (await organizations(page)).find((organization) => organization.name === secondName)
  expect(second).toBeDefined()
  await expect(page).toHaveURL(`/o/${second!.slug}`)
  await expect(sidebar.getByText('No projects yet.')).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Moon landing' })).toBeHidden()

  // Back to the first one, and to the second again.
  await switchTo(page, secondName, user.organizationName)
  await expect(page).toHaveURL(`/o/${first.slug}`)
  await expect(sidebar.getByRole('link', { name: 'Moon landing' })).toBeVisible()

  await switchTo(page, user.organizationName, secondName)
  await expect(page).toHaveURL(`/o/${second!.slug}`)
  await expect(sidebar.getByText('No projects yet.')).toBeVisible()

  // The start page leads to the organization that was used last, also after a reload.
  await page.goto('/')
  await expect(page).toHaveURL(`/o/${second!.slug}`)
  await expect(page.getByRole('heading', { level: 1, name: secondName })).toBeVisible()
})

test('at phone width the sidebar is a drawer behind the menu button', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 })
  const user = await signIn(page)
  const [organization] = await organizations(page)
  const created = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name: 'Pocket project' } })
  expect(created.status()).toBe(201)
  await page.reload()

  const sidebar = page.getByRole('navigation', { name: 'Projects' })
  await expect(page.getByRole('heading', { level: 1, name: user.organizationName })).toBeVisible()
  await expect(sidebar).toBeHidden()
  // Nothing sticks out of the screen.
  // (As a string: the specs are type-checked without the DOM library.)
  expect(await page.evaluate<number>('document.documentElement.scrollWidth')).toBeLessThanOrEqual(390)

  await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(sidebar.getByRole('link', { name: 'Pocket project' })).toBeVisible()

  // Choosing a project closes the drawer.
  await sidebar.getByRole('link', { name: 'Pocket project' }).click()
  await expect(sidebar).toBeHidden()
  await expect(page).toHaveURL(new RegExp(`/o/${organization.slug}/p/[0-9a-f-]+$`))

  // On a wide screen the sidebar is always there, without the menu button.
  await page.setViewportSize({ width: 1280, height: 800 })
  await expect(sidebar).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeHidden()
})
