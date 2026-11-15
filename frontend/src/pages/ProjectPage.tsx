import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { ActivityLog } from '../components/ActivityLog'
import { Dialog, DIALOG_CANCEL, DIALOG_DANGER, DIALOG_INPUT, DIALOG_LABEL, DIALOG_SUBMIT } from '../components/Dialog'
import { ErrorMessage } from '../components/ErrorMessage'
import { DeleteListDialog, EditListDialog, NewListDialog } from '../components/ListDialogs'
import { ModeBadge } from '../components/ModeBadge'
import { ShareProjectDialog } from '../components/ShareDialogs'
import { TabPanel, Tabs } from '../components/Tabs'
import { listAllows } from '../lists/hooks'
import { useCurrentOrganization } from '../orgs/hooks'
import type { Organization, Project } from '../orgs/hooks'
import { listPath, orgPath } from '../orgs/paths'
import { roleAtLeast, useDeleteProject, useProject, useProjectLists, useUpdateProject } from '../projects/hooks'
import type { TodoList } from '../projects/hooks'

const HEADER_BUTTON =
  'rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50'
const HEADER_DANGER_BUTTON =
  'rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50'

const PROJECT_TABS = [
  { id: 'lists', label: 'Lists' },
  { id: 'activity', label: 'Activity' },
] as const

/**
 * A project (`/o/:orgSlug/p/:projectId`): its name, description and lists. Its admins also
 * get the "Activity" tab with the audit log (`?tab=activity`).
 */
export function ProjectPage() {
  const { organization } = useCurrentOrganization()
  const { projectId } = useParams()
  if (organization === null || projectId === undefined) {
    return null
  }
  // Keyed, so an open dialog does not move along to another project.
  return <ProjectView key={projectId} organization={organization} projectId={projectId} />
}

function ProjectView({ organization, projectId }: { organization: Organization; projectId: string }) {
  const project = useProject(projectId)
  const [dialog, setDialog] = useState<'edit' | 'share' | 'delete' | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()

  const notFound =
    (project.error instanceof ApiError && (project.error.status === 404 || project.error.status === 422)) ||
    // A project of another organization does not belong under this one's address.
    (project.data !== undefined && project.data.organization_id !== organization.id)
  if (notFound) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Project not found</h1>
        <p className="text-slate-600">It does not exist, or you have no access to it.</p>
        <Link to={orgPath(organization.slug)} className="text-slate-600 underline">
          Back to {organization.name}
        </Link>
      </main>
    )
  }
  if (project.data === undefined) {
    return (
      <main className="flex flex-1 flex-col gap-4 p-4 sm:p-6">
        {project.isPending && (
          <p role="status" className="text-slate-500">
            Loading…
          </p>
        )}
        <ErrorMessage error={project.error} />
      </main>
    )
  }

  const current = project.data
  const canEdit = roleAtLeast(current.role, 'editor')
  // Sharing and deleting are for the project's admins.
  const canDelete = roleAtLeast(current.role, 'admin')
  // So is the audit log; everyone else has no tabs at all.
  const tab = canDelete && searchParams.get('tab') === 'activity' ? 'activity' : 'lists'
  const lists = <ListsSection project={current} organization={organization} />

  return (
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight break-words">{current.name}</h1>
          {current.description !== null && (
            <p className="break-words whitespace-pre-line text-slate-600">{current.description}</p>
          )}
        </div>
        {(canEdit || canDelete) && (
          <div className="flex shrink-0 gap-2">
            {canEdit && (
              <button type="button" className={HEADER_BUTTON} onClick={() => setDialog('edit')}>
                Edit
              </button>
            )}
            {canDelete && (
              <button type="button" className={HEADER_BUTTON} onClick={() => setDialog('share')}>
                Share
              </button>
            )}
            {canDelete && (
              <button type="button" className={HEADER_DANGER_BUTTON} onClick={() => setDialog('delete')}>
                Delete
              </button>
            )}
          </div>
        )}
      </header>
      {canDelete ? (
        <>
          <Tabs
            label="Views of this project"
            tabs={PROJECT_TABS}
            selected={tab}
            onSelect={(id) => setSearchParams(id === 'lists' ? {} : { tab: id }, { replace: true })}
          />
          <TabPanel tab={tab}>{tab === 'activity' ? <ProjectActivity project={current} /> : lists}</TabPanel>
        </>
      ) : (
        lists
      )}
      {dialog === 'edit' && <EditProjectDialog project={current} onClose={() => setDialog(null)} />}
      {dialog === 'share' && <ShareProjectDialog project={current} onClose={() => setDialog(null)} />}
      {dialog === 'delete' && (
        <DeleteProjectDialog project={current} organization={organization} onClose={() => setDialog(null)} />
      )}
    </main>
  )
}

/** The project's audit log; an event of a list that still exists names that list. */
function ProjectActivity({ project }: { project: Project }) {
  const lists = useProjectLists(project.id)
  const listNames = useMemo(() => new Map((lists.data ?? []).map((list) => [list.id, list.name])), [lists.data])
  return <ActivityLog scope={{ kind: 'project', id: project.id }} listNames={listNames} />
}

function openItems(count: number): string {
  if (count === 0) {
    return 'No open items'
  }
  return count === 1 ? '1 open item' : `${count} open items`
}

const ROW_BUTTON = 'min-h-9 rounded-md px-2 py-1 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900'
const ROW_DANGER_BUTTON = 'min-h-9 rounded-md px-2 py-1 text-sm font-medium text-red-700 hover:bg-red-50'

type ListDialog = { kind: 'new' } | { kind: 'edit' | 'delete'; list: TodoList }

function ListsSection({ project, organization }: { project: Project; organization: Organization }) {
  const lists = useProjectLists(project.id)
  const [dialog, setDialog] = useState<ListDialog | null>(null)
  const close = () => setDialog(null)

  return (
    <section aria-labelledby="project-lists" className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 id="project-lists" className="text-lg font-semibold tracking-tight">
          Lists
        </h2>
        {roleAtLeast(project.role, 'editor') && (
          <button type="button" className={HEADER_BUTTON} onClick={() => setDialog({ kind: 'new' })}>
            New list
          </button>
        )}
      </div>
      {lists.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={lists.error} />
      {lists.data?.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-slate-600">
          This project has no lists yet.
        </p>
      )}
      {lists.data && lists.data.length > 0 && (
        <ul
          aria-labelledby="project-lists"
          className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white"
        >
          {lists.data.map((list) => (
            <ListRow
              key={list.id}
              list={list}
              to={listPath(organization.slug, list.id)}
              onEdit={() => setDialog({ kind: 'edit', list })}
              onDelete={() => setDialog({ kind: 'delete', list })}
            />
          ))}
        </ul>
      )}
      {dialog?.kind === 'new' && <NewListDialog project={project} onClose={close} />}
      {dialog?.kind === 'edit' && <EditListDialog list={dialog.list} onClose={close} />}
      {dialog?.kind === 'delete' && <DeleteListDialog list={dialog.list} onClose={close} />}
    </section>
  )
}

interface ListRowProps {
  list: TodoList
  /** The list's own page, with its items. */
  to: string
  onEdit: () => void
  onDelete: () => void
}

function ListRow({ list, to, onEdit, onDelete }: ListRowProps) {
  // What the role on this list and its mode allow; the API works it out.
  const canEdit = listAllows(list, 'edit_list')
  const canDelete = listAllows(list, 'administer')

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
      {/* At phone width the name has the whole line; the rest follows below it. */}
      <div className="flex min-w-0 basis-full flex-col sm:flex-1 sm:basis-0">
        <Link to={to} className="py-1 font-medium wrap-anywhere text-slate-900 hover:underline sm:py-0">
          {list.name}
        </Link>
        {list.description !== null && (
          <span className="text-sm break-words whitespace-pre-line text-slate-600">{list.description}</span>
        )}
      </div>
      <ModeBadge mode={list.mode} />
      <span className="text-sm text-slate-600 tabular-nums sm:w-28 sm:text-right">{openItems(list.open_item_count)}</span>
      {(canEdit || canDelete) && (
        <div className="ml-auto flex shrink-0 gap-1 sm:ml-0">
          {canEdit && (
            <button type="button" aria-label={`Edit ${list.name}`} className={ROW_BUTTON} onClick={onEdit}>
              Edit
            </button>
          )}
          {canDelete && (
            <button type="button" aria-label={`Delete ${list.name}`} className={ROW_DANGER_BUTTON} onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      )}
    </li>
  )
}

function EditProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const update = useUpdateProject(project)
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')

  function submit(event: FormEvent) {
    event.preventDefault()
    update.mutate(
      { name, description: description.trim() === '' ? null : description },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog title="Edit project" onClose={onClose}>
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

interface DeleteProjectDialogProps {
  project: Project
  organization: Organization
  onClose: () => void
}

function DeleteProjectDialog({ project, organization, onClose }: DeleteProjectDialogProps) {
  const remove = useDeleteProject(project)
  const navigate = useNavigate()

  return (
    <Dialog title={`Delete ${project.name}?`} onClose={onClose}>
      <p className="mt-2 text-sm text-slate-600">
        The project is deleted with all its lists and items. This cannot be undone.
      </p>
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
            // The page of a deleted project is gone: leave for the organization's start.
            onClick={() => remove.mutate(undefined, { onSuccess: () => void navigate(orgPath(organization.slug)) })}
          >
            Delete project
          </button>
        </div>
      </div>
    </Dialog>
  )
}
