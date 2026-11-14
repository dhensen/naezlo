import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn, uniqueUser } from './helpers.ts'

interface Organization {
  id: string
  slug: string
}

interface Me {
  user: { id: string }
  organizations: Organization[]
}

async function me(page: Page): Promise<Me> {
  const response = await page.request.get('/api/me')
  expect(response.ok()).toBe(true)
  return (await response.json()) as Me
}

test('create, rename and delete a project', async ({ page }) => {
  await signIn(page)
  const [organization] = (await me(page)).organizations
  const sidebar = page.getByRole('navigation', { name: 'Projects' })
  await expect(sidebar.getByText('No projects yet.')).toBeVisible()

  // Create: the dialog closes and the new project is opened.
  await sidebar.getByRole('button', { name: 'New project' }).click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByLabel('Name').fill('Moon landing')
  await create.getByLabel('Description').fill('One small step.')
  await create.getByRole('button', { name: 'Create' }).click()

  await expect(create).toBeHidden()
  await expect(page).toHaveURL(new RegExp(`/o/${organization.slug}/p/[0-9a-f-]+$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Moon landing' })).toBeVisible()
  await expect(page.getByText('One small step.')).toBeVisible()
  await expect(page.getByText('This project has no lists yet.')).toBeVisible()
  // The sidebar has it without a reload.
  await expect(sidebar.getByRole('link', { name: 'Moon landing' })).toBeVisible()
  await expect(sidebar.getByText('No projects yet.')).toBeHidden()

  // Lists (made through the API until the list pages exist) show their mode and open items.
  const projectId = new URL(page.url()).pathname.split('/').pop()!
  const list = await page.request.post(`/api/projects/${projectId}/lists`, { data: { name: 'Checklist', mode: 'mixed' } })
  expect(list.status()).toBe(201)
  const { id: listId } = (await list.json()) as { id: string }
  for (const title of ['Build the rocket', 'Pack lunch']) {
    const item = await page.request.post(`/api/lists/${listId}/items`, { data: { title } })
    expect(item.status()).toBe(201)
  }
  await page.reload()
  const row = page.getByRole('list', { name: 'Lists' }).getByRole('listitem').filter({ hasText: 'Checklist' })
  await expect(row).toContainText('Mixed')
  await expect(row).toContainText('2 open items')

  // Rename and change the description.
  await page.getByRole('button', { name: 'Edit' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit project' })
  await expect(edit.getByLabel('Name')).toHaveValue('Moon landing')
  await edit.getByLabel('Name').fill('Mars landing')
  await edit.getByLabel('Description').fill('A giant leap.')
  await edit.getByRole('button', { name: 'Save' }).click()

  await expect(edit).toBeHidden()
  await expect(page.getByRole('heading', { level: 1, name: 'Mars landing' })).toBeVisible()
  await expect(page.getByText('A giant leap.')).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Mars landing' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Moon landing' })).toBeHidden()

  // Delete: Cancel keeps it, confirming removes it and leaves the page.
  await page.getByRole('button', { name: 'Delete' }).click()
  const remove = page.getByRole('dialog', { name: 'Delete Mars landing?' })
  await remove.getByRole('button', { name: 'Cancel' }).click()
  await expect(remove).toBeHidden()
  await expect(sidebar.getByRole('link', { name: 'Mars landing' })).toBeVisible()

  await page.getByRole('button', { name: 'Delete' }).click()
  await remove.getByRole('button', { name: 'Delete project' }).click()

  await expect(page).toHaveURL(`/o/${organization.slug}`)
  await expect(sidebar.getByText('No projects yet.')).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Mars landing' })).toBeHidden()
  // It is really gone, also after a reload.
  await page.goto(`/o/${organization.slug}/p/${projectId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Project not found' })).toBeVisible()
})

test('the controls follow the role on the project', async ({ page, browser }) => {
  await signIn(page)
  const owner = await me(page)
  const [organization] = owner.organizations
  const created = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name: 'Shared plans' } })
  expect(created.status()).toBe(201)
  const { id: projectId } = (await created.json()) as { id: string }

  // Grace joins the organization as a member and gets the viewer role on the project.
  const grace = uniqueUser('Grace Hopper')
  const context = await browser.newContext()
  const gracePage = await context.newPage()
  await signIn(gracePage, { user: grace })
  const graceId = (await me(gracePage)).user.id
  const invited = await page.request.post(`/api/orgs/${organization.id}/invitations`, {
    data: { email: grace.email, role: 'member' },
  })
  expect(invited.ok()).toBe(true)
  const grant = (role: string) =>
    page.request.put(`/api/projects/${projectId}/grants`, {
      data: { principal_kind: 'user', principal_id: graceId, role },
    })
  expect((await grant('viewer')).ok()).toBe(true)

  const projectUrl = `/o/${organization.slug}/p/${projectId}`
  await gracePage.goto(projectUrl)
  await expect(gracePage.getByRole('heading', { level: 1, name: 'Shared plans' })).toBeVisible()
  await expect(gracePage.getByRole('button', { name: 'Edit' })).toBeHidden()
  await expect(gracePage.getByRole('button', { name: 'Delete' })).toBeHidden()

  // As an editor she may rename, not delete.
  expect((await grant('editor')).ok()).toBe(true)
  await gracePage.reload()
  await expect(gracePage.getByRole('button', { name: 'Edit' })).toBeVisible()
  await expect(gracePage.getByRole('button', { name: 'Delete' })).toBeHidden()

  // The owner has both.
  await page.goto(projectUrl)
  await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible()
  await context.close()
})
