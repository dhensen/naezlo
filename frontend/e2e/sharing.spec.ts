import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { signIn, uniqueUser } from './helpers.ts'

interface Me {
  organizations: { id: string; slug: string }[]
}

/** A project with two lists in the signed-in user's organization, made through the API. */
async function newProject(page: Page) {
  const me = (await (await page.request.get('/api/me')).json()) as Me
  const [organization] = me.organizations
  const project = await page.request.post(`/api/orgs/${organization.id}/projects`, { data: { name: 'Household' } })
  expect(project.status()).toBe(201)
  const { id: projectId } = (await project.json()) as { id: string }
  const listIds: string[] = []
  for (const name of ['Groceries', 'Chores']) {
    const list = await page.request.post(`/api/projects/${projectId}/lists`, { data: { name } })
    expect(list.status()).toBe(201)
    listIds.push(((await list.json()) as { id: string }).id)
  }
  return {
    organizationId: organization.id,
    projectUrl: `/o/${organization.slug}/p/${projectId}`,
    groceriesUrl: `/o/${organization.slug}/l/${listIds[0]}`,
    choresUrl: `/o/${organization.slug}/l/${listIds[1]}`,
  }
}

test('share a project as viewer, then raise the person to editor on one list', async ({ page, browser }) => {
  const owner = await signIn(page)
  const { organizationId, projectUrl, groceriesUrl, choresUrl } = await newProject(page)

  // A second person with an account, in a browser of their own, joins the organization.
  const guest = uniqueUser('Grace Hopper')
  const guestContext = await browser.newContext()
  const guestPage = await guestContext.newPage()
  await signIn(guestPage, { user: guest })
  const invited = await page.request.post(`/api/orgs/${organizationId}/invitations`, { data: { email: guest.email } })
  expect(invited.ok()).toBe(true)

  // A member without a grant does not see the project.
  await guestPage.goto(projectUrl)
  await expect(guestPage.getByRole('heading', { level: 1, name: 'Project not found' })).toBeVisible()

  // The owner shares the project with them as a viewer.
  await page.goto(projectUrl)
  await page.getByRole('button', { name: 'Share' }).click()
  const projectDialog = page.getByRole('dialog', { name: 'Share Household' })
  const projectGrants = projectDialog.getByRole('list', { name: 'People and agents with access' })
  await expect(projectGrants.getByRole('listitem')).toHaveCount(1)
  await expect(projectGrants.getByRole('listitem').filter({ hasText: owner.name })).toContainText('Person')
  await expect(projectDialog.getByRole('combobox', { name: `Role of ${owner.name}` })).toHaveValue('admin')
  await projectDialog
    .getByRole('combobox', { name: 'Person or agent' })
    .selectOption({ label: `${guest.name} (${guest.email})` })
  await projectDialog.getByRole('combobox', { name: 'Role', exact: true }).selectOption('viewer')
  await projectDialog.getByRole('button', { name: 'Add' }).click()
  await expect(projectDialog.getByRole('combobox', { name: `Role of ${guest.name}` })).toHaveValue('viewer')
  await projectDialog.getByRole('button', { name: 'Done' }).click()
  await expect(projectDialog).toBeHidden()

  // The grant is still there after a reload.
  await page.reload()
  await page.getByRole('button', { name: 'Share' }).click()
  await expect(projectDialog.getByRole('combobox', { name: `Role of ${guest.name}` })).toHaveValue('viewer')
  await page.keyboard.press('Escape')

  // The second person now sees the project, read-only.
  await guestPage.reload()
  await expect(guestPage.getByRole('heading', { level: 1, name: 'Household' })).toBeVisible()
  await expect(guestPage.getByRole('link', { name: 'Groceries' })).toBeVisible()
  await expect(guestPage.getByRole('button', { name: 'Share' })).toHaveCount(0)
  await expect(guestPage.getByRole('button', { name: 'New list' })).toHaveCount(0)
  await expect(guestPage.getByRole('button', { name: /^Edit/ })).toHaveCount(0)
  await guestPage.getByRole('link', { name: 'Groceries' }).click()
  await expect(guestPage).toHaveURL(groceriesUrl)
  await expect(guestPage.getByText('You can read this list, but not change its items.')).toBeVisible()
  await expect(guestPage.getByRole('textbox', { name: 'Add an item' })).toHaveCount(0)
  await expect(guestPage.getByRole('button', { name: 'Share' })).toHaveCount(0)

  // The owner raises them to editor on that one list.
  await page.goto(groceriesUrl)
  await page.getByRole('button', { name: 'Share' }).click()
  const listDialog = page.getByRole('dialog', { name: 'Share Groceries' })
  await expect(listDialog.getByRole('note')).toContainText('AI agents cannot access it')
  await expect(listDialog.getByText('Nobody has a role of their own on this list.')).toBeVisible()
  const inherited = listDialog.getByRole('list', { name: 'Access from the project' })
  await expect(inherited.getByRole('listitem').filter({ hasText: guest.name })).toContainText('Viewer')
  await listDialog
    .getByRole('combobox', { name: 'Person or agent' })
    .selectOption({ label: `${guest.name} (${guest.email})` })
  await expect(listDialog.getByRole('combobox', { name: 'Role', exact: true }).getByRole('option')).toHaveText([
    'Viewer',
    'Editor',
    'Admin',
    'No access',
  ])
  await listDialog.getByRole('combobox', { name: 'Role', exact: true }).selectOption('editor')
  await listDialog.getByRole('button', { name: 'Add' }).click()
  const ownGrants = listDialog.getByRole('list', { name: 'Access to this list only' })
  await expect(ownGrants.getByRole('combobox', { name: `Role of ${guest.name}` })).toHaveValue('editor')
  await expect(inherited.getByRole('listitem').filter({ hasText: guest.name })).toContainText(
    'Viewer (replaced on this list)',
  )

  // They can add an item there now, and still not on the other list.
  await guestPage.reload()
  const input = guestPage.getByRole('textbox', { name: 'Add an item' })
  await input.fill('Buy milk')
  const added = guestPage.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/items'),
  )
  await input.press('Enter')
  expect((await added).status()).toBe(201)
  await expect(guestPage.getByRole('list', { name: 'Open items' }).getByText('Buy milk')).toBeVisible()
  await guestPage.goto(choresUrl)
  await expect(guestPage.getByText('You can read this list, but not change its items.')).toBeVisible()

  // The owner sees the item the other person added.
  await page.reload()
  await expect(page.getByRole('list', { name: 'Open items' }).getByText('Buy milk')).toBeVisible()

  // Take the list grant away again: the project role (viewer) is back.
  await page.getByRole('button', { name: 'Share' }).click()
  await listDialog.getByRole('button', { name: `Remove ${guest.name}` }).click()
  await listDialog.getByRole('button', { name: 'Yes, remove' }).click()
  await expect(listDialog.getByText('Nobody has a role of their own on this list.')).toBeVisible()
  await guestPage.goto(groceriesUrl)
  await expect(guestPage.getByText('You can read this list, but not change its items.')).toBeVisible()
  await expect(guestPage.getByText('Buy milk')).toBeVisible()
  await guestContext.close()
})
