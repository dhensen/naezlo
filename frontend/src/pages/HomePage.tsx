import { APP_NAME } from '../config'

// Placeholder until the app shell (US-030) replaces it.
export function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center text-slate-900">
      <h1 className="text-4xl font-semibold tracking-tight">{APP_NAME}</h1>
      <p className="text-slate-600">Todo lists that people and AI agents share.</p>
    </main>
  )
}
