import { useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router'

import type { Organization } from '../orgs/hooks'
import { useProjects } from '../orgs/hooks'
import { orgPath, projectPath } from '../orgs/paths'
import { ErrorMessage } from './ErrorMessage'
import { NewProjectDialog } from './NewProjectDialog'

const NAV_LINK = 'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2.5 md:py-1.5 md:text-sm'
const NAV_LINK_ACTIVE = 'bg-brand-50 font-semibold text-brand-700'
const NAV_LINK_IDLE = 'font-medium text-ink-700 hover:bg-ink-100 hover:text-ink-900'

const AGENTS_ICON = (
  <>
    <rect x="3" y="6" width="10" height="7" rx="1.5" />
    <path d="M8 6V3.5" />
    <circle cx="8" cy="2.75" r="0.75" />
    <path d="M6.25 9.25v1M9.75 9.25v1" />
  </>
)

const SETTINGS_ICON = (
  <>
    <path d="M2.5 4.5h6M11.5 4.5h2M2.5 11.5h2M7.5 11.5h6" />
    <circle cx="10" cy="4.5" r="1.5" />
    <circle cx="6" cy="11.5" r="1.5" />
  </>
)

/** A 16px line icon in front of a link of the sidebar. */
function NavIcon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="size-4 shrink-0 opacity-80"
    >
      {children}
    </svg>
  )
}

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
          open ? 'fixed top-14 bottom-0 left-0 z-20 flex overflow-y-auto overscroll-contain shadow-float' : 'hidden'
        } w-72 max-w-[85vw] shrink-0 flex-col border-r border-ink-200 bg-white md:static md:z-auto md:flex md:w-64 md:overflow-visible md:shadow-none`}
      >
        <nav aria-label="Projects" className="flex flex-col gap-0.5 p-3">
          <h2 className="px-2.5 pt-1 pb-1.5 text-xs font-semibold text-ink-500">Projects</h2>
          {projects.isPending && (
            <p role="status" className="px-2 py-1 text-sm text-ink-500">
              Loading…
            </p>
          )}
          <ErrorMessage error={projects.error} />
          {projects.data?.length === 0 && (
            <p className="px-2 py-1 text-sm text-ink-500">No projects yet.</p>
          )}
          {projects.data && projects.data.length > 0 && (
            <ul className="flex flex-col gap-0.5">
              {projects.data.map((project) => (
                <li key={project.id}>
                  <NavLink
                    to={projectPath(organization.slug, project.id)}
                    className={({ isActive }) =>
                      `${NAV_LINK} ${isActive ? NAV_LINK_ACTIVE : NAV_LINK_IDLE}`
                    }
                    onClick={onNavigate}
                  >
                    <NavIcon>
                      <path d="M2.5 4.5a1 1 0 0 1 1-1h3l1.5 1.5h4.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1Z" />
                    </NavIcon>
                    <span className="truncate">{project.name}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          )}
          {/* Every member of the organization may create a project. */}
          <button
            type="button"
            className={`mt-1 text-left ${NAV_LINK} ${NAV_LINK_IDLE}`}
            onClick={() => setCreating(true)}
          >
            <NavIcon>
              <path d="M8 3.5v9M3.5 8h9" />
            </NavIcon>
            New project
          </button>
        </nav>
        <nav aria-label="Organization" className="mt-auto flex flex-col gap-0.5 border-t border-ink-200 p-3">
          {[
            { to: '/agents', label: 'Agents', icon: AGENTS_ICON },
            { to: '/settings', label: 'Settings', icon: SETTINGS_ICON },
          ].map((link) => (
            <NavLink
              key={link.to}
              to={orgPath(organization.slug, link.to)}
              className={({ isActive }) =>
                `${NAV_LINK} ${isActive ? NAV_LINK_ACTIVE : NAV_LINK_IDLE}`
              }
              onClick={onNavigate}
            >
              <NavIcon>{link.icon}</NavIcon>
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
