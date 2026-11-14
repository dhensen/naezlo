// Every page of an organization lives under /o/<slug>.

/** The path of a page in the organization with this slug: `orgPath('acme', '/settings')`. */
export function orgPath(slug: string, rest = ''): string {
  return `/o/${encodeURIComponent(slug)}${rest}`
}

/** The page of a project: `/o/<slug>/p/<project id>`. */
export function projectPath(slug: string, projectId: string): string {
  return orgPath(slug, `/p/${encodeURIComponent(projectId)}`)
}

/** The page of a list with its items: `/o/<slug>/l/<list id>`. */
export function listPath(slug: string, listId: string): string {
  return orgPath(slug, `/l/${encodeURIComponent(listId)}`)
}

const LAST_ORGANIZATION_KEY = 'lastOrganization'

/** The slug of the organization this browser showed last, or null. */
export function lastOrganizationSlug(): string | null {
  try {
    return window.localStorage.getItem(LAST_ORGANIZATION_KEY)
  } catch {
    // Storage can be switched off; the first organization is used then.
    return null
  }
}

export function rememberOrganization(slug: string): void {
  try {
    window.localStorage.setItem(LAST_ORGANIZATION_KEY, slug)
  } catch {
    // Not remembered, nothing else.
  }
}
