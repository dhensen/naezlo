import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router'

import { useMe } from '../auth/hooks'
import type { Organization } from '../orgs/hooks'
import { orgPath } from '../orgs/paths'
import { NewOrganizationDialog } from './NewOrganizationDialog'
import { useDismiss } from './useDismiss'

/** The current organization in the top bar; opens to the user's organizations and "New organization". */
export function OrganizationSwitcher({ current }: { current: Organization | null }) {
  const me = useMe()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  useDismiss(
    menu,
    open,
    useCallback(() => setOpen(false), []),
  )

  const organizations = me.data?.organizations ?? []
  const label = current?.name ?? 'Choose organization'

  return (
    <>
      <div ref={menu} className="relative min-w-0">
        <button
          type="button"
          aria-haspopup="true"
          aria-expanded={open}
          aria-label={`Organization: ${label}`}
          className="flex max-w-full items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm font-semibold text-ink-800 hover:border-ink-300 hover:bg-ink-50"
          onClick={() => setOpen((value) => !value)}
        >
          <span className="truncate">{label}</span>
          <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4 shrink-0 fill-ink-500">
            <path d="M5.5 7.5 10 12l4.5-4.5 1 1L10 14 4.5 8.5z" />
          </svg>
        </button>
        {open && (
          <div className="absolute left-0 z-20 mt-1 flex w-64 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-xl border border-ink-200 bg-white py-1 shadow-float">
            <p className="px-3 pt-2 pb-1 text-xs font-semibold text-ink-500">
              Organizations
            </p>
            <ul aria-label="Organizations">
              {organizations.map((organization) => {
                const isCurrent = organization.id === current?.id
                return (
                  <li key={organization.id}>
                    <Link
                      to={orgPath(organization.slug)}
                      aria-current={isCurrent ? 'true' : undefined}
                      className={`flex items-center justify-between gap-2 px-3 py-1.5 text-sm hover:bg-ink-100 ${
                        isCurrent ? 'font-semibold text-ink-900' : 'text-ink-700'
                      }`}
                      onClick={() => setOpen(false)}
                    >
                      <span className="truncate">{organization.name}</span>
                      {isCurrent && (
                        <span aria-hidden="true" className="text-mint-600">
                          ✓
                        </span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
            <button
              type="button"
              className="mt-1 border-t border-ink-200 px-3 py-2 text-left text-sm font-medium text-ink-700 hover:bg-ink-100"
              onClick={() => {
                setOpen(false)
                setCreating(true)
              }}
            >
              New organization
            </button>
          </div>
        )}
      </div>
      {creating && <NewOrganizationDialog onClose={() => setCreating(false)} />}
    </>
  )
}
