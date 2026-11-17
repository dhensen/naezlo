import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <Link to="/" className="text-ink-600 underline">
        Back to the start
      </Link>
    </main>
  )
}
