import { useEffect, useState } from 'react'
import { Link, Outlet } from 'react-router'

import { APP_NAME } from '../config'
import { useCurrentOrganization } from '../orgs/hooks'
import { rememberOrganization } from '../orgs/paths'
import { OrganizationSwitcher } from './OrganizationSwitcher'
import { Sidebar } from './Sidebar'
import { UserMenu } from './UserMenu'

/**
 * The frame of every signed-in page: a top bar with the organization switcher and the user
 * menu, and for a page of an organization (`/o/:orgSlug/...`) a sidebar with its projects.
 * Below the `md` width the sidebar is a drawer behind the menu button; it hangs under the
 * top bar (`h-14` there, `top-14` here and in the sidebar) and stays put while it is open.
 */
export function AppLayout() {
  const { slug, organization } = useCurrentOrganization()
  const [navOpen, setNavOpen] = useState(false)
  const currentSlug = organization?.slug

  useEffect(() => {
    if (currentSlug !== undefined) {
      rememberOrganization(currentSlug)
    }
  }, [currentSlug])

  // Behind the open drawer the page stays where it is (the drawer only exists below `md`).
  useEffect(() => {
    document.body.classList.toggle('max-md:overflow-hidden', navOpen)
    return () => document.body.classList.remove('max-md:overflow-hidden')
  }, [navOpen])

  return (
    <div className="flex min-h-dvh flex-col bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-2 sm:px-3">
        {organization && (
          <button
            type="button"
            aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
            aria-expanded={navOpen}
            aria-controls="sidebar"
            className="flex size-10 shrink-0 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 md:hidden"
            onClick={() => setNavOpen((value) => !value)}
          >
            <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5 fill-current">
              <path d="M3 5h14v1.5H3zm0 4.25h14v1.5H3zm0 4.25h14V15H3z" />
            </svg>
          </button>
        )}
        <Link to="/" className="hidden text-lg font-semibold tracking-tight sm:block">
          {APP_NAME}
        </Link>
        <OrganizationSwitcher current={organization} />
        <div className="ml-auto shrink-0">
          <UserMenu />
        </div>
      </header>
      <div className="relative flex flex-1">
        {organization && (
          <>
            <Sidebar organization={organization} open={navOpen} onNavigate={() => setNavOpen(false)} />
            {navOpen && (
              <button
                type="button"
                aria-label="Close navigation"
                tabIndex={-1}
                className="fixed inset-0 top-14 z-10 bg-slate-900/30 md:hidden"
                onClick={() => setNavOpen(false)}
              />
            )}
          </>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          {slug !== undefined && organization === null ? (
            <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">Organization not found</h1>
              <p className="text-slate-600">It does not exist, or you are not a member of it.</p>
              <Link to="/" className="text-slate-600 underline">
                Back to the start
              </Link>
            </main>
          ) : (
            <Outlet />
          )}
        </div>
      </div>
    </div>
  )
}
