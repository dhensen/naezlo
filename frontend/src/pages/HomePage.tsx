import { useMe } from '../auth/hooks'
import { APP_NAME } from '../config'

// Placeholder until the app shell (US-030) replaces it.
export function HomePage() {
  const me = useMe()
  // The default organization comes first (the oldest membership).
  const organization = me.data?.organizations[0]

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-4xl font-semibold tracking-tight">{APP_NAME}</h1>
      <p className="text-slate-600">Todo lists that people and AI agents share.</p>
      {organization && (
        <p className="text-slate-600">
          Organization: <span className="font-medium text-slate-900">{organization.name}</span>
        </p>
      )}
    </main>
  )
}
