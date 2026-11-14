import { randomUUID } from 'node:crypto'

import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

export interface TestUser {
  email: string
  name: string
  /** The name of the organization every new user gets on their first sign-in. */
  organizationName: string
}

/** A user nobody else has: tests run in parallel on one database and must not share data. */
export function uniqueUser(name = 'Ada Lovelace'): TestUser {
  return {
    email: `e2e-${randomUUID()}@example.com`,
    name,
    organizationName: `${name}'s organization`,
  }
}

/**
 * Sign in through the dev-login form as a new user (or as `user`, to sign in again) and wait
 * until the app is shown. Opens `path` first, so the test ends up on that page.
 */
export async function signIn(
  page: Page,
  { user = uniqueUser(), path = '/' }: { user?: TestUser; path?: string } = {},
): Promise<TestUser> {
  await page.goto(path)
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Name').fill(user.name)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: `Account: ${user.name}` })).toBeVisible()
  return user
}

/** Sign out through the user menu; the app then shows the login page. */
export async function signOut(page: Page, user: TestUser): Promise<void> {
  await page.getByRole('button', { name: `Account: ${user.name}` }).click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL('/login')
}
