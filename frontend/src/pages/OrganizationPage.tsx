import { useCurrentOrganization } from '../orgs/hooks'

/** The start page of an organization (`/o/:orgSlug`). */
export function OrganizationPage() {
  const { organization } = useCurrentOrganization()
  if (organization === null) {
    return null
  }

  return (
    <main className="flex flex-1 flex-col gap-2 p-4 sm:p-6">
      <h1 className="text-2xl font-semibold tracking-tight">{organization.name}</h1>
      <p className="text-slate-600">Choose a project from the list of projects.</p>
    </main>
  )
}
