import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { useAppConfig, useDevLogin, useMe } from '../auth/hooks'
import { leaveTo, safeNextPath } from '../auth/next'
import { isBackendPath } from '../backendPaths'
import { ErrorMessage } from '../components/ErrorMessage'
import { APP_NAME } from '../config'

// What the backend's Google routes report as /login?error=<code>.
const LOGIN_ERRORS: Record<string, string> = {
  google_unavailable: 'Google could not be reached. Try again in a moment.',
  google_login_failed: 'Signing in with Google did not work. Try again.',
  email_not_verified: 'Your Google account has no verified email address.',
  google_account_conflict:
    'This email address is already linked to a different Google account.',
}

const INPUT =
  'rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-slate-500 focus:outline-none'
const BUTTON =
  'rounded-md bg-slate-900 px-4 py-2 text-center font-medium text-white hover:bg-slate-700 disabled:opacity-60'

function DevLoginForm() {
  const devLogin = useDevLogin()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    devLogin.mutate({ email, name })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 text-left" aria-label="Development sign-in">
      <p className="text-sm text-slate-500">
        Development sign-in: no password, any email address.
      </p>
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
        Email
        <input
          type="email"
          name="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={INPUT}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
        Name
        <input
          type="text"
          name="name"
          required
          maxLength={200}
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={INPUT}
        />
      </label>
      <ErrorMessage error={devLogin.error} />
      <button type="submit" disabled={devLogin.isPending} className={BUTTON}>
        Sign in
      </button>
    </form>
  )
}

export function LoginPage() {
  const me = useMe()
  const config = useAppConfig()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNextPath(params.get('next'))
  const errorCode = params.get('error')
  const signedIn = me.data != null

  // Also the way out after a sign-in on this page: the dev-login stores the user for `useMe`.
  useEffect(() => {
    if (!signedIn) {
      return
    }
    if (next !== null && isBackendPath(next)) {
      // Such as /authorize?... of an MCP client: the backend continues from there.
      leaveTo(next)
    } else {
      void navigate(next ?? '/', { replace: true })
    }
  }, [signedIn, next, navigate])

  const googleUrl =
    '/api/auth/google/login' + (next === null ? '' : `?next=${encodeURIComponent(next)}`)

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-slate-50 px-4 text-slate-900 sm:px-6">
      <div className="flex w-full max-w-sm flex-col gap-5 rounded-lg border border-slate-200 bg-white p-6 text-center shadow-sm">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in to {APP_NAME}</h1>
          <p className="text-sm text-slate-600">Todo lists that people and AI agents share.</p>
        </div>
        {errorCode !== null && (
          <ErrorMessage error={LOGIN_ERRORS[errorCode] ?? 'Signing in did not work. Try again.'} />
        )}
        <ErrorMessage error={me.error ?? config.error} />
        {config.isPending && (
          <p role="status" className="text-slate-500">
            Loading…
          </p>
        )}
        {config.data?.google_login_enabled && (
          // A link, not a fetch: the browser itself has to go to Google and come back.
          <a href={googleUrl} className={BUTTON}>
            Sign in with Google
          </a>
        )}
        {config.data?.dev_login_enabled && <DevLoginForm />}
        {config.data && !config.data.google_login_enabled && !config.data.dev_login_enabled && (
          <p className="text-sm text-slate-600">
            Signing in is not set up on this server yet. Ask its administrator.
          </p>
        )}
      </div>
    </main>
  )
}
