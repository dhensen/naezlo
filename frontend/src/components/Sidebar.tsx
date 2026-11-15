import { useState } from 'react'
import { NavLink } from 'react-router'

import type { Organization } from '../orgs/hooks'
import { useProjects } from '../orgs/hooks'
import { orgPath, projectPath } from '../orgs/paths'
import { ErrorMessage } from './ErrorMessage'
import { NewProjectDialog } from './NewProjectDialog'

interface SidebarProps {
  organization: Organization
  /** Whether it is shown at phone width, where it is a drawer; wider screens always show it. */
  open: boolean
  onNavigate: () => void
}

/** The projects of the current organization that the user can see, "New project", and the links to its agents and its settings. */
export function Sidebar({ organization, open, onNavigate }: SidebarProps) {
  const projects = useProjects(organization.id)
  const [creating, setCreating] = useState(false)

  return (
    <>
      <aside
        id="sidebar"
        className={`${
          open ? 'fixed top-14 bottom-0 left-0 z-20 flex overflow-y-auto overscroll-contain shadow-lg' : 'hidden'
        } w-72 max-w-[85vw] shrink-0 flex-col border-r border-slate-200 bg-white md:static md:z-auto md:flex md:w-64 md:overflow-visible md:shadow-none`}
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
                    to={projectPath(organization.slug, project.id)}
                    className={({ isActive }) =>
                      `block truncate rounded-md px-2 py-2.5 hover:bg-slate-100 md:py-1.5 md:text-sm ${
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
          {/* Every member of the organization may create a project. */}
          <button
            type="button"
            className="mt-1 rounded-md px-2 py-2.5 text-left font-medium text-slate-700 hover:bg-slate-100 md:py-1.5 md:text-sm"
            onClick={() => setCreating(true)}
          >
            + New project
          </button>
        </nav>
        <nav aria-label="Organization" className="mt-auto flex flex-col border-t border-slate-200 p-3">
          {[
            { to: '/agents', label: 'Agents' },
            { to: '/settings', label: 'Settings' },
          ].map((link) => (
            <NavLink
              key={link.to}
              to={orgPath(organization.slug, link.to)}
              className={({ isActive }) =>
                `block rounded-md px-2 py-2.5 hover:bg-slate-100 md:py-1.5 md:text-sm ${
                  isActive ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-700'
                }`
              }
              onClick={onNavigate}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      {/* Next to the sidebar, not in it: the drawer has its own stacking order. */}
      {creating && (
        <NewProjectDialog
          organization={organization}
          onClose={() => {
            setCreating(false)
            onNavigate()
          }}
        />
      )}
    </>
  )
}
