import { Link, Outlet } from 'react-router'

import { APP_NAME } from '../config'
import { UserMenu } from './UserMenu'

/** The frame of every signed-in page: a header with the user menu, the page below it. */
export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2">
        <Link to="/" className="text-lg font-semibold tracking-tight">
          {APP_NAME}
        </Link>
        <UserMenu />
      </header>
      <div className="flex flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  )
}
