import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useCreateOrganization } from '../orgs/hooks'
import { orgPath } from '../orgs/paths'
import { Dialog, DIALOG_CANCEL, DIALOG_INPUT, DIALOG_LABEL, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'

/** Asks for a name, creates the organization and switches to it. */
export function NewOrganizationDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateOrganization()
  const navigate = useNavigate()
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
    <Dialog title="New organization" onClose={onClose}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <label className={DIALOG_LABEL}>
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
            className={DIALOG_INPUT}
          />
        </label>
        <ErrorMessage error={create.error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={DIALOG_CANCEL} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={create.isPending} className={DIALOG_SUBMIT}>
            Create
          </button>
        </div>
      </form>
    </Dialog>
  )
}
