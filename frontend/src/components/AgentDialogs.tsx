import { useState } from 'react'
import type { FormEvent } from 'react'

import { useCreateAgent, useUpdateAgent } from '../agents/hooks'
import type { Schemas } from '../api/client'
import type { Organization } from '../orgs/hooks'
import type { Agent } from '../sharing/hooks'
import { Dialog, DIALOG_CANCEL, DIALOG_INPUT, DIALOG_LABEL, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'

interface AgentFieldsProps {
  name: string
  description: string
  onName: (name: string) => void
  onDescription: (description: string) => void
}

function AgentFields({ name, description, onName, onDescription }: AgentFieldsProps) {
  return (
    <>
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
          onChange={(event) => onName(event.target.value)}
          className={DIALOG_INPUT}
        />
      </label>
      <label className={DIALOG_LABEL}>
        Description (optional)
        <textarea
          name="description"
          rows={2}
          maxLength={2000}
          value={description}
          onChange={(event) => onDescription(event.target.value)}
          className={DIALOG_INPUT}
        />
      </label>
    </>
  )
}

function descriptionOrNull(description: string): string | null {
  return description.trim() === '' ? null : description.trim()
}

interface NewAgentDialogProps {
  organization: Organization
  onClose: () => void
  onCreated: (agent: Agent) => void
}

/** Asks for a name and a description and registers the agent. */
export function NewAgentDialog({ organization, onClose, onCreated }: NewAgentDialogProps) {
  const create = useCreateAgent(organization.id)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate({ name, description: descriptionOrNull(description) }, { onSuccess: onCreated })
  }

  return (
    <Dialog title="New agent" onClose={onClose}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <p className="text-sm text-ink-600">
          An agent is the identity an AI tool works under. Give each tool or task its own, for example "Claude" or
          "Release bot".
        </p>
        <AgentFields name={name} description={description} onName={setName} onDescription={setDescription} />
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

interface EditAgentDialogProps {
  organization: Organization
  agent: Agent
  onClose: () => void
}

/** Rename an agent or change its description. Only what changed is sent. */
export function EditAgentDialog({ organization, agent, onClose }: EditAgentDialogProps) {
  const update = useUpdateAgent(organization.id, agent.id)
  const [name, setName] = useState(agent.name)
  const [description, setDescription] = useState(agent.description ?? '')

  function submit(event: FormEvent) {
    event.preventDefault()
    const body: Schemas['AgentPatch'] = {}
    if (name.trim() !== agent.name) {
      body.name = name
    }
    if (descriptionOrNull(description) !== agent.description) {
      body.description = descriptionOrNull(description)
    }
    if (Object.keys(body).length === 0) {
      onClose()
      return
    }
    update.mutate(body, { onSuccess: onClose })
  }

  return (
    <Dialog title="Edit agent" onClose={onClose}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <AgentFields name={name} description={description} onName={setName} onDescription={setDescription} />
        <ErrorMessage error={update.error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={DIALOG_CANCEL} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={update.isPending || name.trim() === ''} className={DIALOG_SUBMIT}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  )
}
