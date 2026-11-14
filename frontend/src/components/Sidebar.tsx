import { NavLink } from 'react-router'

import type { Organization } from '../orgs/hooks'
import { useProjects } from '../orgs/hooks'
import { orgPath } from '../orgs/paths'
import { ErrorMessage } from './ErrorMessage'

interface SidebarProps {
  organization: Organization
  /** Whether it is shown at phone width, where it is a drawer; wider screens always show it. */
  open: boolean
  onNavigate: () => void
}

/** The projects of the current organization that the user can see, and the link to its settings. */
export function Sidebar({ organization, open, onNavigate }: SidebarProps) {
  const projects = useProjects(organization.id)

  return (
    <aside
      id="sidebar"
      className={`${
        open ? 'absolute inset-y-0 left-0 z-10 flex shadow-lg' : 'hidden'
      } w-64 max-w-[85vw] shrink-0 flex-col border-r border-slate-200 bg-white md:static md:flex md:shadow-none`}
    >
      <nav aria-label="Projects" className="flex flex-col gap-1 p-3">
        <h2 className="px-2 py-1 text-xs font-medium tracking-wide text-slate-500 uppercase">Projects</h2>
        {projects.isPending && (
          <p role="status" className="px-2 py-1 text-sm text-slate-500">
            Loading…
          </p>
        )}
        <ErrorMessage error={projects.error} />
        {projects.data?.length === 0 && (
          <p className="px-2 py-1 text-sm text-slate-500">No projects yet.</p>
        )}
        {projects.data && projects.data.length > 0 && (
          <ul>
            {projects.data.map((project) => (
              <li key={project.id}>
                <NavLink
                  to={orgPath(organization.slug, `/projects/${project.id}`)}
                  className={({ isActive }) =>
                    `block truncate rounded-md px-2 py-1.5 text-sm hover:bg-slate-100 ${
                      isActive ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-700'
                    }`
                  }
                  onClick={onNavigate}
                >
                  {project.name}
                </NavLink>
              </li>
            ))}
          </ul>
        )}
      </nav>
      <nav aria-label="Organization" className="mt-auto flex flex-col border-t border-slate-200 p-3">
        <NavLink
          to={orgPath(organization.slug, '/settings')}
          className={({ isActive }) =>
            `block rounded-md px-2 py-1.5 text-sm hover:bg-slate-100 ${
              isActive ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-700'
            }`
          }
          onClick={onNavigate}
        >
          Settings
        </NavLink>
      </nav>
    </aside>
  )
}
