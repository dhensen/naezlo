import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn, uniqueUser } from './helpers.ts'

interface Me {
  user: { id: string }
  organizations: { id: string; slug: string }[]
}

async function me(page: Page): Promise<Me> {
  const response = await page.request.get('/api/me')
  expect(response.ok()).toBe(true)
  return (await response.json()) as Me
}

/** A project of the signed-in user's organization (made through the API); opens its page. */
async function openNewProject(page: Page, name: string) {
  const [organization] = (await me(page)).organizations
  const created = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name } })
  expect(created.status()).toBe(201)
  const { id } = (await created.json()) as { id: string }
  const url = `/o/${organization.slug}/p/${id}`
  await page.goto(url)
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  return { organization, projectId: id, url }
}

function listRows(page: Page) {
  return page.getByRole('list', { name: 'Lists' }).getByRole('listitem')
}

test('create a list (Human only by default), change it to Mixed, delete it', async ({ page }) => {
  await signIn(page)
  await openNewProject(page, 'Moon landing')
  await expect(page.getByText('This project has no lists yet.')).toBeVisible()

  // Create: the organization has no agent, so "Human only" is preselected.
  await page.getByRole('button', { name: 'New list' }).click()
  const create = page.getByRole('dialog', { name: 'New list' })
  await expect(create.getByRole('radio', { name: 'Human only' })).toBeChecked()
  await expect(create.getByRole('radio', { name: 'AI only' })).not.toBeChecked()
  await expect(create.getByRole('radio', { name: 'Mixed' })).not.toBeChecked()
  await create.getByLabel('Name').fill('Checklist')
  await create.getByLabel('Description').fill('Before the launch.')
  await create.getByRole('button', { name: 'Create' }).click()

  await expect(create).toBeHidden()
  const row = listRows(page).filter({ hasText: 'Checklist' })
  await expect(row).toBeVisible()
  await expect(row).toContainText('Before the launch.')
  await expect(row).toContainText('No open items')
  await expect(page.getByText('This project has no lists yet.')).toBeHidden()

  // The badge names the mode and explains it in a tooltip, on hover and on keyboard focus.
  const badge = row.getByText('Human only')
  const tooltip = row.getByRole('tooltip', { includeHidden: true })
  await expect(tooltip).toBeHidden()
  await badge.hover()
  await expect(tooltip).toBeVisible()
  await expect(tooltip).toHaveText('Only people work on this list. AI agents cannot see it.')
  await page.mouse.move(0, 0)
  await expect(tooltip).toBeHidden()
  await badge.focus()
  await expect(tooltip).toBeVisible()

  // Rename and change the mode to Mixed.
  await row.getByRole('button', { name: 'Edit Checklist' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit list' })
  await expect(edit.getByLabel('Name')).toHaveValue('Checklist')
  await expect(edit.getByRole('radio', { name: 'Human only' })).toBeChecked()
  await edit.getByLabel('Name').fill('Launch checklist')
  await edit.getByRole('radio', { name: 'Mixed' }).check()
  await edit.getByRole('button', { name: 'Save' }).click()

  await expect(edit).toBeHidden()
  const renamed = listRows(page).filter({ hasText: 'Launch checklist' })
  await expect(renamed.getByText('Mixed')).toBeVisible()
  await expect(renamed.getByText('Human only')).toBeHidden()
  await expect(renamed.getByRole('tooltip', { includeHidden: true })).toHaveText(
    'People and AI agents work on this list together.',
  )
  // It is stored: the same after a reload.
  await page.reload()
  await expect(renamed.getByText('Mixed')).toBeVisible()

  // Delete: Cancel keeps it, confirming removes it.
  await renamed.getByRole('button', { name: 'Delete Launch checklist' }).click()
  const remove = page.getByRole('dialog', { name: 'Delete Launch checklist?' })
  await remove.getByRole('button', { name: 'Cancel' }).click()
  await expect(remove).toBeHidden()
  await expect(renamed).toBeVisible()

  await renamed.getByRole('button', { name: 'Delete Launch checklist' }).click()
  await remove.getByRole('button', { name: 'Delete list' }).click()

  await expect(remove).toBeHidden()
  await expect(page.getByText('This project has no lists yet.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('This project has no lists yet.')).toBeVisible()
})

test('with an agent in the organization a new list starts as Mixed', async ({ page }) => {
  await signIn(page)
  const { organization } = await openNewProject(page, 'Robots')
  const agent = await page.request.post(`/api/orgs/${organization.id}/agents`, { data: { name: 'Claude' } })
  expect(agent.status()).toBe(201)

  // No reload: the dialog asks for the default when it opens.
  await page.getByRole('button', { name: 'New list' }).click()
  const create = page.getByRole('dialog', { name: 'New list' })
  await expect(create.getByRole('radio', { name: 'Mixed' })).toBeChecked()
  await create.getByLabel('Name').fill('Agent queue')
  await create.getByRole('radio', { name: 'AI only' }).check()
  await create.getByRole('button', { name: 'Create' }).click()

  await expect(listRows(page).filter({ hasText: 'Agent queue' }).getByText('AI only')).toBeVisible()
})

test('the list controls follow the role on the list', async ({ page, browser }) => {
  await signIn(page)
  const { organization, projectId, url } = await openNewProject(page, 'Shared plans')
  const made = await page.request.post(`/api/projects/${projectId}/lists`, { data: { name: 'Roadmap', mode: 'mixed' } })
  expect(made.status()).toBe(201)
  const { id: listId } = (await made.json()) as { id: string }

  // Grace joins the organization and is a viewer of the project.
  const grace = uniqueUser('Grace Hopper')
  const context = await browser.newContext()
  const gracePage = await context.newPage()
  await signIn(gracePage, { user: grace })
  const graceId = (await me(gracePage)).user.id
  const invited = await page.request.post(`/api/orgs/${organization.id}/invitations`, {
    data: { email: grace.email, role: 'member' },
  })
  expect(invited.ok()).toBe(true)
  const projectGrant = await page.request.put(`/api/projects/${projectId}/grants`, {
    data: { principal_kind: 'user', principal_id: graceId, role: 'viewer' },
  })
  expect(projectGrant.ok()).toBe(true)

  await gracePage.goto(url)
  const row = listRows(gracePage).filter({ hasText: 'Roadmap' })
  await expect(row).toBeVisible()
  await expect(gracePage.getByRole('button', { name: 'New list' })).toBeHidden()
  await expect(row.getByRole('button')).toHaveCount(0)

  // An editor of the list may change it, not delete it.
  const listGrant = (role: string) =>
    page.request.put(`/api/lists/${listId}/grants`, {
      data: { principal_kind: 'user', principal_id: graceId, role },
    })
  expect((await listGrant('editor')).ok()).toBe(true)
  await gracePage.reload()
  await expect(row.getByRole('button', { name: 'Edit Roadmap' })).toBeVisible()
  await expect(row.getByRole('button', { name: 'Delete Roadmap' })).toBeHidden()

  // She makes it AI only, which takes the list out of an editor's hands.
  await row.getByRole('button', { name: 'Edit Roadmap' }).click()
  const edit = gracePage.getByRole('dialog', { name: 'Edit list' })
  await edit.getByRole('radio', { name: 'AI only' }).check()
  await edit.getByRole('button', { name: 'Save' }).click()
  await expect(edit).toBeHidden()
  await expect(row.getByText('AI only')).toBeVisible()
  await expect(row.getByRole('button')).toHaveCount(0)

  // The owner still has both controls.
  await page.reload()
  const ownerRow = listRows(page).filter({ hasText: 'Roadmap' })
  await expect(ownerRow.getByRole('button', { name: 'Edit Roadmap' })).toBeVisible()
  await expect(ownerRow.getByRole('button', { name: 'Delete Roadmap' })).toBeVisible()
  await context.close()
})
