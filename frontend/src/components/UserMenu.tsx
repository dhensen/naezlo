import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { useMe, useSignOut } from '../auth/hooks'
import { Avatar } from './Avatar'
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
        className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm font-medium text-ink-700 hover:bg-ink-100"
        onClick={() => setOpen((value) => !value)}
      >
        <Avatar name={user.name} kind="user" className="size-7 text-xs" />
        <span className="hidden max-w-40 truncate sm:inline">{user.name}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 flex w-64 flex-col gap-3 rounded-xl border border-ink-200 bg-white p-3 shadow-float">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink-900">{user.name}</p>
            <p className="truncate text-sm text-ink-500">{user.email}</p>
          </div>
          <ErrorMessage error={signOut.error} />
          <button
            type="button"
            disabled={signOut.isPending}
            className="rounded-lg border border-ink-300 px-3 py-1.5 text-sm font-medium text-ink-700 hover:bg-ink-50 disabled:opacity-60"
            onClick={() =>
              signOut.mutate(undefined, {
                // Not /login?next=<here>: someone who signs out is not on their way anywhere.
                onSuccess: (forget) => {
                  void navigate('/login', { replace: true })
                  forget()
                },
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
