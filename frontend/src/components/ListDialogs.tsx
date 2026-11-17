import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'

import type { Schemas } from '../api/client'
import { useCreateList, useDeleteList, useUpdateList } from '../lists/hooks'
import { MODES } from '../lists/modes'
import type { ListMode } from '../lists/modes'
import type { Project } from '../orgs/hooks'
import { projectKey } from '../projects/hooks'
import type { TodoList } from '../projects/hooks'
import { Dialog, DIALOG_CANCEL, DIALOG_DANGER, DIALOG_INPUT, DIALOG_LABEL, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'
import { ModeIcon } from './ModeBadge'

interface ModeChoiceProps {
  value: ListMode
  onChange: (mode: ListMode) => void
}

/** The three list modes as radio buttons, each with its icon and what it means. */
function ModeChoice({ value, onChange }: ModeChoiceProps) {
  const id = useId()

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium text-ink-700">Mode</legend>
      {MODES.map((info) => (
        // The whole row chooses the mode; the radio in it is what the keyboard uses.
        <div
          key={info.mode}
          className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-ink-200 px-3 py-2.5 hover:bg-ink-50 has-checked:border-brand-500 has-checked:bg-brand-50"
          onClick={() => onChange(info.mode)}
        >
          <input
            type="radio"
            name="mode"
            id={`${id}-${info.mode}`}
            value={info.mode}
            checked={value === info.mode}
            onChange={() => onChange(info.mode)}
            aria-describedby={`${id}-${info.mode}-explanation`}
            className="mt-1"
          />
          <div className="flex min-w-0 flex-col">
            <label
              htmlFor={`${id}-${info.mode}`}
              className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-semibold text-ink-900"
            >
              <ModeIcon mode={info.mode} className="size-4" />
              {info.label}
            </label>
            <p id={`${id}-${info.mode}-explanation`} className="text-xs text-ink-600">
              {info.explanation}
            </p>
          </div>
        </div>
      ))}
    </fieldset>
  )
}

interface ListFieldsProps {
  name: string
  description: string
  mode: ListMode
  assignmentRequired: boolean
  onName: (name: string) => void
  onDescription: (description: string) => void
  onMode: (mode: ListMode) => void
  onAssignmentRequired: (required: boolean) => void
}

function ListFields({
  name,
  description,
  mode,
  assignmentRequired,
  onName,
  onDescription,
  onMode,
  onAssignmentRequired,
}: ListFieldsProps) {
  const id = useId()

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
      <ModeChoice value={mode} onChange={onMode} />
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          id={`${id}-assignment`}
          checked={assignmentRequired}
          onChange={(event) => onAssignmentRequired(event.target.checked)}
          aria-describedby={`${id}-assignment-explanation`}
          className="mt-1"
        />
        <div className="flex min-w-0 flex-col">
          <label htmlFor={`${id}-assignment`} className="text-sm font-medium text-ink-900">
            Assignment required
          </label>
          <p id={`${id}-assignment-explanation`} className="text-xs text-ink-600">
            Only the assignee can complete an item. People and agents pick an item up before they work on it, so
            nobody does the same work twice.
          </p>
        </div>
      </div>
    </>
  )
}

function descriptionOrNull(description: string): string | null {
  return description.trim() === '' ? null : description
}

/**
 * Asks for a name, a description and a mode, and adds the list to the project. The mode
 * starts on the server's default for the organization (`project.default_list_mode`).
 */
export function NewListDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const create = useCreateList(project.id)
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  // null: not chosen by hand, so the default is shown (and follows a newer answer).
  const [chosenMode, setChosenMode] = useState<ListMode | null>(null)
  const mode = chosenMode ?? project.default_list_mode
  const [assignmentRequired, setAssignmentRequired] = useState(false)

  // The default changes when the organization gets its first agent or loses its last one,
  // which the cached project does not know: ask again whenever the dialog opens.
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: projectKey(project.id), exact: true })
  }, [queryClient, project.id])

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { name, description: descriptionOrNull(description), mode, assignment_required: assignmentRequired },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog title="New list" onClose={onClose}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <ListFields
          name={name}
          description={description}
          mode={mode}
          assignmentRequired={assignmentRequired}
          onName={setName}
          onDescription={setDescription}
          onMode={setChosenMode}
          onAssignmentRequired={setAssignmentRequired}
        />
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

/** Rename a list, change its description, its mode or whether assignment is required. Only
 * what changed is sent. */
export function EditListDialog({ list, onClose }: { list: TodoList; onClose: () => void }) {
  const update = useUpdateList(list)
  const [name, setName] = useState(list.name)
  const [description, setDescription] = useState(list.description ?? '')
  const [mode, setMode] = useState<ListMode>(list.mode)
  const [assignmentRequired, setAssignmentRequired] = useState(list.assignment_required)

  function submit(event: FormEvent) {
    event.preventDefault()
    const body: Schemas['ListPatch'] = {}
    if (name.trim() !== list.name) {
      body.name = name
    }
    if (descriptionOrNull(description.trim()) !== list.description) {
      body.description = descriptionOrNull(description)
    }
    if (mode !== list.mode) {
      body.mode = mode
    }
    if (assignmentRequired !== list.assignment_required) {
      body.assignment_required = assignmentRequired
    }
    if (Object.keys(body).length === 0) {
      onClose()
      return
    }
    update.mutate(body, { onSuccess: onClose })
  }

  return (
    <Dialog title="Edit list" onClose={onClose}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <ListFields
          name={name}
          description={description}
          mode={mode}
          assignmentRequired={assignmentRequired}
          onName={setName}
          onDescription={setDescription}
          onMode={setMode}
          onAssignmentRequired={setAssignmentRequired}
        />
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

/** Asks before a list is deleted with its items. */
export function DeleteListDialog({ list, onClose }: { list: TodoList; onClose: () => void }) {
  const remove = useDeleteList(list)

  return (
    <Dialog title={`Delete ${list.name}?`} onClose={onClose}>
      <p className="mt-2 text-sm text-ink-600">The list is deleted with all its items. This cannot be undone.</p>
      <div className="mt-4 flex flex-col gap-4">
        <ErrorMessage error={remove.error} />
        <div className="flex justify-end gap-2">
          <button type="button" autoFocus className={DIALOG_CANCEL} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            disabled={remove.isPending}
            className={DIALOG_DANGER}
            onClick={() => remove.mutate(undefined, { onSuccess: onClose })}
          >
            Delete list
          </button>
        </div>
      </div>
    </Dialog>
  )
}
