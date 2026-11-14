import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { useMe, useSignOut } from '../auth/hooks'
import { ErrorMessage } from './ErrorMessage'
import { useDismiss } from './useDismiss'

/** The signed-in user's name in the header; opens to their email and "Sign out". */
export function UserMenu() {
  const me = useMe()
  const signOut = useSignOut()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  useDismiss(
    menu,
    open,
    useCallback(() => setOpen(false), []),
  )

  const user = me.data?.user
  if (!user) {
    return null
  }

  return (
    <div ref={menu} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`Account: ${user.name}`}
        className="flex items-center gap-2 rounded-md px-2 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100"
        onClick={() => setOpen((value) => !value)}
      >
        <span
          aria-hidden="true"
          className="flex size-7 items-center justify-center rounded-full bg-slate-800 text-xs text-white"
        >
          {user.name.charAt(0).toUpperCase()}
        </span>
        <span className="hidden max-w-40 truncate sm:inline">{user.name}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 flex w-64 flex-col gap-3 rounded-md border border-slate-200 bg-white p-3 shadow-lg">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">{user.name}</p>
            <p className="truncate text-sm text-slate-500">{user.email}</p>
          </div>
          <ErrorMessage error={signOut.error} />
          <button
            type="button"
            disabled={signOut.isPending}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            onClick={() =>
              signOut.mutate(undefined, {
                // Not /login?next=<here>: someone who signs out is not on their way anywhere.
                onSuccess: () => void navigate('/login', { replace: true }),
              })
            }
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
