import { useState } from 'react'
import { Navigate } from 'react-router'

import { useMe } from '../auth/hooks'
import { Logo } from '../components/Logo'
import { NewOrganizationDialog } from '../components/NewOrganizationDialog'
import { lastOrganizationSlug, orgPath } from '../orgs/paths'

/** `/`: on to the organization used last, or the first one. Someone without any gets a start. */
export function HomePage() {
  const me = useMe()
  const [creating, setCreating] = useState(false)
  const organizations = me.data?.organizations ?? []

  const first = organizations[0]
  if (first !== undefined) {
    const last = lastOrganizationSlug()
    const organization = organizations.find((candidate) => candidate.slug === last) ?? first
    return <Navigate to={orgPath(organization.slug)} replace />
  }

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <h1>
        <Logo className="h-12" />
      </h1>
      <p className="text-slate-600">You are not a member of an organization yet.</p>
      <button
        type="button"
        className="rounded-md bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-700"
        onClick={() => setCreating(true)}
      >
        New organization
      </button>
      {creating && <NewOrganizationDialog onClose={() => setCreating(false)} />}
    </main>
  )
}
