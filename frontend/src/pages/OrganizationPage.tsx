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
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="min-w-0 text-2xl font-semibold tracking-tight wrap-anywhere">{organization.name}</h1>
        {/* Not "New project": that is the button in the sidebar. */}
        <button
          type="button"
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
          onClick={() => setCreating(true)}
        >
          Create a project
        </button>
      </div>
      {projects.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={projects.error} />
      {projects.data?.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-slate-600">
          There are no projects here yet, or none that are shared with you.
        </p>
      )}
      {projects.data && projects.data.length > 0 && (
        <ul
          aria-label="Projects of this organization"
          className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white"
        >
          {projects.data.map((project) => (
            <li key={project.id}>
              <Link
                to={projectPath(organization.slug, project.id)}
                className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-medium wrap-anywhere text-slate-900">{project.name}</span>
                  {project.description !== null && (
                    <span className="line-clamp-2 text-sm wrap-anywhere text-slate-600">{project.description}</span>
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
                  className="size-4 shrink-0 text-slate-400"
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
