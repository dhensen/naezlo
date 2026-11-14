import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useCreateOrganization } from '../orgs/hooks'
import { orgPath } from '../orgs/paths'
import { ErrorMessage } from './ErrorMessage'

/** Asks for a name, creates the organization and switches to it. */
export function NewOrganizationDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateOrganization()
  const navigate = useNavigate()
  const titleId = useId()
  const [name, setName] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { name },
      {
        onSuccess: (organization) => {
          onClose()
          void navigate(orgPath(organization.slug))
        },
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            onClose()
          }
        }}
      >
        <h2 id={titleId} className="text-lg font-semibold tracking-tight">
          New organization
        </h2>
        <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Name
            <input
              type="text"
              name="name"
              required
              maxLength={200}
              autoFocus
              autoComplete="off"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-slate-500 focus:outline-none"
            />
          </label>
          <ErrorMessage error={create.error} />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
