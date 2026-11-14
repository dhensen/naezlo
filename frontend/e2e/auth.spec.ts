import { expect, test } from '@playwright/test'

import { signIn, signOut } from './helpers.ts'

test('sign in, see the default organization, stay signed in after a reload, sign out', async ({
  page,
}) => {
  // Nobody is signed in: the guard sends the visitor to the login page.
  await page.goto('/')
  await expect(page).toHaveURL('/login')

  // The start page leads on to the user's default organization.
  const user = await signIn(page)
  await expect(page).toHaveURL(/\/o\/ada-lovelace[0-9-]*$/)
  await expect(page.getByRole('heading', { level: 1, name: user.organizationName })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('button', { name: `Account: ${user.name}` })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: user.organizationName })).toBeVisible()

  await signOut(page, user)
  await expect(page.getByLabel('Email')).toBeVisible()

  // The session is gone, not only hidden: the app asks to sign in again.
  await page.goto('/')
  await expect(page).toHaveURL('/login')
})
