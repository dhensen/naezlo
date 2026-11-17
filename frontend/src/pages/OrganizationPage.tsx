import { useState } from 'react'
import { Link } from 'react-router'

import { ErrorMessage } from '../components/ErrorMessage'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { useCurrentOrganization, useProjects } from '../orgs/hooks'
import { projectPath } from '../orgs/paths'

/**
 * The start page of an organization (`/o/:orgSlug`): its projects. On a phone the sidebar is
 * a drawer that starts closed, so this is where someone finds their projects after signing in.
 */
export function OrganizationPage() {
  const { organization } = useCurrentOrganization()
  const projects = useProjects(organization?.id ?? '')
  const [creating, setCreating] = useState(false)
  if (organization === null) {
    return null
  }

  return (
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-5 mx-auto p-4 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="min-w-0 text-2xl font-semibold tracking-tight wrap-anywhere sm:text-3xl">{organization.name}</h1>
        {/* Not "New project": that is the button in the sidebar. */}
        <button
          type="button"
          className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-700"
          onClick={() => setCreating(true)}
        >
          Create a project
        </button>
      </div>
      {projects.isPending && (
        <p role="status" className="text-sm text-ink-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={projects.error} />
      {projects.data?.length === 0 && (
        <p className="rounded-xl border border-dashed border-ink-300 px-4 py-8 text-center text-ink-600">
          There are no projects here yet, or none that are shared with you.
        </p>
      )}
      {projects.data && projects.data.length > 0 && (
        <ul
          aria-label="Projects of this organization"
          className="divide-y divide-ink-200 rounded-xl border border-ink-200 bg-white shadow-card"
        >
          {projects.data.map((project) => (
            <li key={project.id}>
              <Link
                to={projectPath(organization.slug, project.id)}
                className="group flex items-center gap-3 px-4 py-3.5 first:rounded-t-xl last:rounded-b-xl hover:bg-ink-50"
              >
                <span
                  aria-hidden="true"
                  className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600"
                >
                  <svg
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="size-4.5"
                  >
                    <path d="M2.5 4.5a1 1 0 0 1 1-1h3l1.5 1.5h4.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1Z" />
                  </svg>
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold wrap-anywhere text-ink-900">{project.name}</span>
                  {project.description !== null && (
                    <span className="line-clamp-2 text-sm wrap-anywhere text-ink-600">{project.description}</span>
                  )}
                </span>
                <svg
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="size-4 shrink-0 text-ink-400 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-600"
                >
                  <path d="M6 3.5 10.5 8 6 12.5" />
                </svg>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {creating && <NewProjectDialog organization={organization} onClose={() => setCreating(false)} />}
    </main>
  )
}
