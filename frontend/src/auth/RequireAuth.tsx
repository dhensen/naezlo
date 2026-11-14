import { Navigate, Outlet, useLocation } from 'react-router'

import { ErrorMessage } from '../components/ErrorMessage'
import { useMe } from './hooks'
import { loginPath } from './next'

/**
 * The guard around every page except the login page: its child routes render only for a
 * signed-in user. Anyone else goes to /login?next=<where they were>.
 */
export function RequireAuth() {
  const me = useMe()
  const location = useLocation()

  if (me.isPending) {
    return (
      <p role="status" className="p-6 text-center text-slate-500">
        Loading…
      </p>
    )
  }
  if (me.isError) {
    return (
      <div className="mx-auto max-w-md p-6">
        <ErrorMessage error={me.error}>
          <button type="button" className="font-medium underline" onClick={() => void me.refetch()}>
            Try again
          </button>
        </ErrorMessage>
      </div>
    )
  }
  if (me.data === null) {
    const here = location.pathname + location.search + location.hash
    return <Navigate to={loginPath(here)} replace />
  }
  return <Outlet />
}
