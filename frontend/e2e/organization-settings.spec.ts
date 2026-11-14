import { expect, test } from '@playwright/test'

import { signIn, uniqueUser } from './helpers.ts'

test('rename the organization, invite someone, change their role and remove them', async ({ page, browser }) => {
  const owner = await signIn(page)
  await page.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/o\/[a-z0-9-]+\/settings$/)
  const settingsUrl = page.url()
  await expect(page.getByRole('heading', { level: 1, name: 'Organization settings' })).toBeVisible()

  // Rename: the switcher follows, the address stays.
  const newName = `Renamed ${owner.email}`
  await expect(page.getByLabel('Organization name')).toHaveValue(owner.organizationName)
  await page.getByLabel('Organization name').fill(newName)
  await page.getByRole('button', { name: 'Rename' }).click()
  await expect(page.getByRole('button', { name: `Organization: ${newName}` })).toBeVisible()
  expect(page.url()).toBe(settingsUrl)

  // The only owner cannot give the role away: the API's message is shown.
  const members = page.getByRole('table', { name: 'Members' })
  await page.getByRole('combobox', { name: `Role of ${owner.name}` }).selectOption('member')
  await expect(page.getByRole('alert')).toContainText('An organization needs at least one owner')
  await expect(page.getByRole('combobox', { name: `Role of ${owner.name}` })).toHaveValue('owner')

  // Invite an email address nobody has an account for.
  const guest = uniqueUser('Grace Hopper')
  await page.getByLabel('Email address').fill(guest.email)
  await page.getByRole('button', { name: 'Invite' }).click()
  await expect(page.getByText(`${guest.email} joins ${newName} the next time they sign in.`)).toBeVisible()
  const pending = page.getByRole('list', { name: 'Pending invitations' })
  await expect(pending.getByText(guest.email)).toBeVisible()
  await expect(members.getByText(guest.email)).toBeHidden()

  // The invited person signs in, in a browser of their own, and sees the organization.
  const guestContext = await browser.newContext()
  const guestPage = await guestContext.newPage()
  await signIn(guestPage, { user: guest })
  await guestPage.getByRole('button', { name: /^Organization: / }).click()
  await guestPage.getByRole('list', { name: 'Organizations' }).getByRole('link', { name: newName }).click()
  await expect(guestPage.getByRole('heading', { level: 1, name: newName })).toBeVisible()

  // As a plain member the settings are read-only.
  await guestPage.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Settings' }).click()
  await expect(guestPage.getByText('Only owners and admins can change these settings.')).toBeVisible()
  await expect(guestPage.getByRole('table', { name: 'Members' }).getByText(owner.email)).toBeVisible()
  await expect(guestPage.getByRole('combobox')).toHaveCount(0)
  await expect(guestPage.getByLabel('Organization name')).toHaveCount(0)
  await expect(guestPage.getByLabel('Email address')).toHaveCount(0)

  // Back at the owner: the invitation became a membership.
  await page.reload()
  await expect(members.getByText(guest.email)).toBeVisible()
  await expect(page.getByText('No pending invitations.')).toBeVisible()

  // Change their role; it is still there after a reload.
  const guestRole = page.getByRole('combobox', { name: `Role of ${guest.name}` })
  await expect(guestRole).toHaveValue('member')
  await guestRole.selectOption('admin')
  await expect(guestRole).toHaveValue('admin')
  await page.reload()
  await expect(guestRole).toHaveValue('admin')

  // The new admin now gets the forms.
  await guestPage.reload()
  await expect(guestPage.getByLabel('Organization name')).toHaveValue(newName)
  await expect(guestPage.getByLabel('Email address')).toBeVisible()

  // Remove them.
  await page.getByRole('button', { name: `Remove ${guest.name}` }).click()
  await page.getByRole('button', { name: 'Yes, remove' }).click()
  await expect(members.getByText(guest.email)).toBeHidden()
  await page.reload()
  await expect(members.getByText(owner.email)).toBeVisible()
  await expect(members.getByText(guest.email)).toBeHidden()

  // For the removed person the organization is gone.
  await guestPage.reload()
  await expect(guestPage.getByRole('heading', { level: 1, name: 'Organization not found' })).toBeVisible()
  await guestContext.close()
})

test('revoke a pending invitation, and leave an organization', async ({ page, browser }) => {
  const owner = await signIn(page)
  await page.getByRole('navigation', { name: 'Organization' }).getByRole('link', { name: 'Settings' }).click()
  const settingsPath = new URL(page.url()).pathname

  // An invitation that is revoked gives nothing at the next sign-in.
  const stranger = uniqueUser('Alan Turing')
  await page.getByLabel('Email address').fill(stranger.email)
  await page.getByRole('button', { name: 'Invite' }).click()
  await page.getByRole('button', { name: `Revoke invitation for ${stranger.email}` }).click()
  await expect(page.getByText('No pending invitations.')).toBeVisible()

  // Someone who was invited as admin leaves again.
  const guest = uniqueUser('Grace Hopper')
  await page.getByLabel('Email address').fill(guest.email)
  await page.getByLabel('Role', { exact: true }).selectOption('admin')
  await page.getByRole('button', { name: 'Invite' }).click()
  await expect(page.getByRole('list', { name: 'Pending invitations' }).getByText(guest.email)).toBeVisible()

  const guestContext = await browser.newContext()
  const guestPage = await guestContext.newPage()
  await signIn(guestPage, { user: guest, path: settingsPath })
  await expect(guestPage.getByRole('button', { name: `Organization: ${owner.organizationName}` })).toBeVisible()
  await guestPage.getByRole('button', { name: 'Leave organization' }).click()
  await guestPage.getByRole('button', { name: 'Yes, leave' }).click()
  await expect(guestPage.getByRole('button', { name: `Organization: ${guest.organizationName}` })).toBeVisible()
  await expect(guestPage.getByRole('heading', { level: 1, name: guest.organizationName })).toBeVisible()
  await guestContext.close()

  await page.reload()
  const members = page.getByRole('table', { name: 'Members' })
  await expect(members.getByText(owner.email)).toBeVisible()
  await expect(members.getByText(guest.email)).toBeHidden()
  await expect(members.getByText(stranger.email)).toBeHidden()
})
