import type { ReactNode } from 'react'

/** The text to show for anything that was thrown or given as an error. */
function errorText(error: unknown): string {
  if (typeof error === 'string') {
    return error
  }
  if (error instanceof Error && error.message !== '') {
    return error.message
  }
  return 'Something went wrong. Try again later.'
}

interface ErrorMessageProps {
  /** An `ApiError`, another `Error` or a ready text; nothing is rendered for null/undefined. */
  error: unknown
  /** Something to do about it, such as a retry button. */
  children?: ReactNode
}

/** The one place API errors (and other failures) are shown. */
export function ErrorMessage({ error, children }: ErrorMessageProps) {
  if (error === null || error === undefined) {
    return null
  }
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-left text-sm text-red-800"
    >
      <span>{errorText(error)}</span>
      {children}
    </div>
  )
}
