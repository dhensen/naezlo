import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import type { Organization } from '../orgs/hooks'
import { projectPath } from '../orgs/paths'
import { useCreateProject } from '../projects/hooks'
import { Dialog, DIALOG_CANCEL, DIALOG_INPUT, DIALOG_LABEL, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'

interface NewProjectDialogProps {
  organization: Organization
  onClose: () => void
}

/** Asks for a name and a description, creates the project and opens it. */
export function NewProjectDialog({ organization, onClose }: NewProjectDialogProps) {
  const create = useCreateProject(organization.id)
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { name, description: description.trim() === '' ? null : description },
      {
        onSuccess: (project) => {
          onClose()
          void navigate(projectPath(organization.slug, project.id))
        },
      },
    )
  }

  return (
    <Dialog title="New project" onClose={onClose}>
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
        <label className={DIALOG_LABEL}>
          Description (optional)
          <textarea
            name="description"
            rows={3}
            maxLength={2000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className={DIALOG_INPUT}
          />
        </label>
        <ErrorMessage error={create.error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={DIALOG_CANCEL} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={create.isPending || name.trim() === ''} className={DIALOG_SUBMIT}>
            Create
          </button>
        </div>
      </form>
    </Dialog>
  )
}
