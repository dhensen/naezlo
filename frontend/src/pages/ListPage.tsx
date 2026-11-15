import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { useMe } from '../auth/hooks'
import { ActivityLog } from '../components/ActivityLog'
import { ErrorMessage } from '../components/ErrorMessage'
import { ModeBadge, ModeIcon } from '../components/ModeBadge'
import { ShareListDialog } from '../components/ShareDialogs'
import { TabPanel, Tabs } from '../components/Tabs'
import { addItem, isUnsaved, sameAssignee, useAssignees, useChangeItems, useItems } from '../items/hooks'
import type { Assignee, Item, ItemChange } from '../items/hooks'
import { listAllows, useList } from '../lists/hooks'
import { useCurrentOrganization, useProjects } from '../orgs/hooks'
import type { Organization } from '../orgs/hooks'
import { orgPath, projectPath } from '../orgs/paths'
import type { TodoList } from '../projects/hooks'

const LIST_TABS = [
  { id: 'items', label: 'Items' },
  { id: 'activity', label: 'Activity' },
] as const

/**
 * A list (`/o/:orgSlug/l/:listId`): its name, mode, project and items. Its admins also get
 * the "Activity" tab with the audit log (`?tab=activity`).
 */
export function ListPage() {
  const { organization } = useCurrentOrganization()
  const { listId } = useParams()
  if (organization === null || listId === undefined) {
    return null
  }
  // Keyed, so what is being typed or edited does not move along to another list.
  return <ListView key={listId} organization={organization} listId={listId} />
}

function ListView({ organization, listId }: { organization: Organization; listId: string }) {
  const list = useList(listId)
  const items = useItems(listId)
  const projects = useProjects(organization.id)
  const [sharing, setSharing] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()

  const notFound =
    (list.error instanceof ApiError && (list.error.status === 404 || list.error.status === 422)) ||
    // A list of another organization does not belong under this one's address.
    (list.data !== undefined && list.data.organization_id !== organization.id)
  if (notFound) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">List not found</h1>
        <p className="text-slate-600">It does not exist, or you have no access to it.</p>
        <Link to={orgPath(organization.slug)} className="text-slate-600 underline">
          Back to {organization.name}
        </Link>
      </main>
    )
  }
  if (list.data === undefined) {
    return (
      <main className="flex flex-1 flex-col gap-4 p-4 sm:p-6">
        {list.isPending && (
          <p role="status" className="text-slate-500">
            Loading…
          </p>
        )}
        <ErrorMessage error={list.error} />
      </main>
    )
  }

  const current = list.data
  const canChange = listAllows(current, 'change_items')
  // The audit log is for the list's admins; everyone else has no tabs at all.
  const canAdminister = listAllows(current, 'administer')
  const tab = canAdminister && searchParams.get('tab') === 'activity' ? 'activity' : 'items'
  const itemsView = (
    <>
      {!canChange && (
        <p role="note" className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
          {current.mode === 'ai_only'
            ? 'AI agents manage this list. You can read it, but not change its items.'
            : 'You can read this list, but not change its items.'}
        </p>
      )}
      {canChange && current.assignment_required && (
        <p role="note" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Only the assignee can complete an item in this list. Pick an item up before you start on it, so nobody else
          does the same work.
        </p>
      )}
      {items.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={items.error} />
      {items.data && <ItemsSection list={current} items={items.data} canChange={canChange} />}
    </>
  )
  // Someone with a grant on the list alone cannot open the project: no link for them.
  const projectIsVisible = projects.data?.some((project) => project.id === current.project_id) ?? false

  return (
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-5 p-4 sm:p-6">
      <header className="flex flex-col gap-1">
        <p className="text-sm text-slate-600">
          <span className="sr-only">Project: </span>
          {projectIsVisible ? (
            <Link to={projectPath(organization.slug, current.project_id)} className="underline hover:text-slate-900">
              {current.project_name}
            </Link>
          ) : (
            current.project_name
          )}
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="min-w-0 text-2xl font-semibold tracking-tight wrap-anywhere">{current.name}</h1>
          <ModeBadge mode={current.mode} />
          {current.assignment_required && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
              Assignment required
            </span>
          )}
          {listAllows(current, 'administer') && (
            <button
              type="button"
              className="ml-auto rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              onClick={() => setSharing(true)}
            >
              Share
            </button>
          )}
        </div>
        {current.description !== null && (
          <p className="break-words whitespace-pre-line text-slate-600">{current.description}</p>
        )}
      </header>
      {canAdminister ? (
        <>
          <Tabs
            label="Views of this list"
            tabs={LIST_TABS}
            selected={tab}
            onSelect={(id) => setSearchParams(id === 'items' ? {} : { tab: id }, { replace: true })}
          />
          <TabPanel tab={tab} className="flex flex-col gap-5">
            {tab === 'activity' ? <ActivityLog scope={{ kind: 'list', id: current.id }} /> : itemsView}
          </TabPanel>
        </>
      ) : (
        itemsView
      )}
      {sharing && <ShareListDialog list={current} onClose={() => setSharing(false)} />}
    </main>
  )
}

const TEXT_INPUT =
  'rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-slate-500 focus:outline-none'
// At phone width a row button is at least 36px in both directions: big enough for a thumb.
const ROW_BUTTON_SIZE = 'inline-flex min-h-9 min-w-9 items-center justify-center gap-1 sm:min-h-0 sm:min-w-0'
const SMALL_BUTTON = `${ROW_BUTTON_SIZE} rounded-md px-2 py-1 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-300 disabled:hover:bg-transparent`
const SMALL_DANGER_BUTTON = `${ROW_BUTTON_SIZE} rounded-md px-2 py-1 text-sm font-medium text-red-700 hover:bg-red-50 disabled:text-red-300`
const ITEM_LIST = 'divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white'

type Direction = 'up' | 'down'

function ItemsSection({ list, items, canChange }: { list: TodoList; items: Item[]; canChange: boolean }) {
  const me = useMe()
  const [error, setError] = useState<unknown>(null)
  const userId = me.data?.user.id ?? ''
  const change = useChangeItems(list, userId, setError)
  // Who an item can be given to; only someone who changes items needs to know.
  const assignees = useAssignees(list.id, canChange)
  const assignment: Assignment = {
    required: list.assignment_required,
    userId,
    assignees: assignees.data ?? [],
    me: assignees.data?.find((assignee) => assignee.kind === 'user' && assignee.id === userId) ?? null,
  }
  const [title, setTitle] = useState('')
  const [doneShown, setDoneShown] = useState(false)
  const addInput = useRef<HTMLInputElement>(null)
  const openList = useRef<HTMLUListElement>(null)
  const doneListId = useId()

  const open = items.filter((item) => item.status === 'open')
  const done = items.filter((item) => item.status === 'done')

  function apply(itemChange: ItemChange) {
    setError(null)
    change.mutate(itemChange)
  }

  function add(event: FormEvent) {
    event.preventDefault()
    if (title.trim() !== '') {
      apply(addItem(list.id, title))
      setTitle('')
    }
    // Also after a click on "Add": ready for the next one.
    addInput.current?.focus()
  }

  // A moved row is put back into the page, which can take the keyboard focus away from the
  // button that was pressed: give it back once the new order is shown. At the top or the
  // bottom that button is switched off, so the other one gets it.
  const moved = useRef<{ id: string; direction: Direction } | null>(null)
  useLayoutEffect(() => {
    if (moved.current === null) {
      return
    }
    const { id, direction } = moved.current
    moved.current = null
    const button = (wanted: Direction) =>
      openList.current?.querySelector<HTMLButtonElement>(`button[data-move="${id}:${wanted}"]:not(:disabled)`)
    ;(button(direction) ?? button(direction === 'up' ? 'down' : 'up'))?.focus()
  }, [items])

  /** Open items move among the open ones; the done ones in between keep their place. */
  function move(item: Item, direction: Direction) {
    const index = open.findIndex((candidate) => candidate.id === item.id)
    let beforeItemId: string | null
    if (direction === 'up') {
      beforeItemId = open[index - 1].id
    } else {
      const next = items.findIndex((candidate) => candidate.id === open[index + 1].id)
      beforeItemId = items[next + 1]?.id ?? null
    }
    moved.current = { id: item.id, direction }
    apply({ kind: 'move', item, beforeItemId })
  }

  return (
    <section aria-label="Items" className="flex flex-col gap-4">
      {canChange && (
        <form onSubmit={add} className="flex gap-2">
          <input
            ref={addInput}
            type="text"
            aria-label="Add an item"
            placeholder="Add an item…"
            maxLength={500}
            autoComplete="off"
            enterKeyHint="done"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`min-w-0 flex-1 ${TEXT_INPUT}`}
          />
          <button
            type="submit"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 sm:px-3"
          >
            Add
          </button>
        </form>
      )}
      <ErrorMessage error={error}>
        <button type="button" className="shrink-0 font-medium underline" onClick={() => setError(null)}>
          Dismiss
        </button>
      </ErrorMessage>
      {items.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-slate-600">
          This list has no items yet.
        </p>
      )}
      {items.length > 0 && open.length === 0 && <p className="text-slate-600">Everything is done.</p>}
      {open.length > 0 && (
        <ul ref={openList} aria-label="Open items" className={ITEM_LIST}>
          {open.map((item, index) => (
            <ItemRow
              key={item.id}
              item={item}
              canChange={canChange}
              assignment={assignment}
              onChange={apply}
              onMove={(direction) => move(item, direction)}
              canMoveUp={index > 0}
              canMoveDown={index < open.length - 1}
            />
          ))}
        </ul>
      )}
      {done.length > 0 && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={doneShown}
            aria-controls={doneListId}
            className="flex min-h-9 items-center gap-1.5 self-start rounded-md px-2 py-1 text-sm font-semibold text-slate-700 hover:bg-slate-100 sm:min-h-0"
            onClick={() => setDoneShown(!doneShown)}
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className={`size-3.5 transition-transform ${doneShown ? 'rotate-90' : ''}`}
            >
              <path d="M6 3.5 10.5 8 6 12.5" />
            </svg>
            Done ({done.length})
          </button>
          {doneShown && (
            <ul id={doneListId} aria-label="Done items" className={ITEM_LIST}>
              {done.map((item) => (
                <ItemRow key={item.id} item={item} canChange={canChange} assignment={assignment} onChange={apply} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

/** What the rows need to know about assigning items in this list. */
interface Assignment {
  /** Only the assignee can complete an item. */
  required: boolean
  userId: string
  /** Everyone an item can be given to; empty until it is known. */
  assignees: Assignee[]
  /** The user as an assignee; null when they cannot be one (or it is not known yet). */
  me: Assignee | null
}

interface ItemRowProps {
  item: Item
  canChange: boolean
  assignment: Assignment
  onChange: (change: ItemChange) => void
  /** Left out for a done item: only open items have an order to work through. */
  onMove?: (direction: Direction) => void
  canMoveUp?: boolean
  canMoveDown?: boolean
}

function ItemRow({
  item,
  canChange,
  assignment,
  onChange,
  onMove,
  canMoveUp = false,
  canMoveDown = false,
}: ItemRowProps) {
  const [notesShown, setNotesShown] = useState(false)
  const [confirming, setConfirming] = useState(false)
  // At phone width moving and deleting wait behind "More"; wider screens always show them.
  const [moreShown, setMoreShown] = useState(false)
  const notesId = useId()
  const moreId = useId()
  const done = item.status === 'done'
  // Not stored yet, so there is no id to send a change for: its controls wait.
  const waiting = isUnsaved(item)
  const titleStyle = done ? 'text-slate-500 line-through' : 'text-slate-900'
  const mine = item.assignee !== null && sameAssignee(item.assignee, { kind: 'user', id: assignment.userId })
  // Where assignment is required only the assignee ticks an item off; anyone reopens it.
  const canTick = canChange && (done || !assignment.required || mine)

  return (
    <li aria-busy={waiting || undefined} className="flex flex-col gap-2 px-3 py-2.5 sm:px-4">
      <div className="flex items-start gap-x-1">
        {canTick ? (
          // The label is the part that is pressed: 40px, around a much smaller box.
          <label className="-my-1.5 -ml-2 flex size-10 shrink-0 cursor-pointer items-center justify-center">
            <input
              type="checkbox"
              aria-label={`Mark ${item.title} as done`}
              checked={done}
              disabled={waiting}
              onChange={() => onChange({ kind: 'update', item, patch: { status: done ? 'open' : 'done' } })}
              className="size-5 accent-slate-900 sm:size-4"
            />
          </label>
        ) : (
          <span className="-ml-2 flex h-7 w-10 shrink-0 items-center justify-center text-slate-500">
            <span aria-hidden="true">{done ? '✓' : '○'}</span>
            <span className="sr-only">{done ? 'Done:' : 'Open:'}</span>
          </span>
        )}
        {/*
          At phone width the title has the whole line. Below it stand the assignee and
          "Notes", with the rest behind "More" on a line of its own. From `sm` everything is
          shown, to the right of the title.
        */}
        <div className="flex min-w-0 flex-1 flex-col gap-1 sm:grid sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:gap-x-0.5">
          <div className="flex min-w-0 flex-col items-start gap-1 sm:col-start-1 sm:mr-3">
            {canChange && !waiting ? (
              <EditableTitle
                item={item}
                className={titleStyle}
                onSave={(title) => onChange({ kind: 'update', item, patch: { title } })}
              />
            ) : (
              <span data-title className={`px-1 py-0.5 wrap-anywhere ${titleStyle}`}>
                {item.title}
              </span>
            )}
            {(item.created_by.kind === 'agent' || (done && item.completed_by?.kind === 'agent')) && (
              <span className="flex flex-wrap gap-1 px-1">
                {item.created_by.kind === 'agent' && <AgentMarker>Added by an agent</AgentMarker>}
                {done && item.completed_by?.kind === 'agent' && <AgentMarker>Completed by an agent</AgentMarker>}
              </span>
            )}
          </div>
          <div className="flex items-start gap-x-2 sm:contents">
            <div className="min-w-0 flex-1 sm:col-start-1 sm:row-start-2 sm:mr-3">
              {canChange && !waiting ? (
                <AssigneeControl item={item} assignment={assignment} mine={mine} onChange={onChange} />
              ) : (
                item.assignee !== null && (
                  <span className="flex min-h-9 items-center px-1 text-sm text-slate-600 sm:min-h-0 sm:text-xs">
                    Assigned to {item.assignee.name}
                    {item.assignee.kind === 'agent' && ' (agent)'}
                  </span>
                )
              )}
            </div>
            <div className="flex shrink-0 items-center gap-0.5 sm:col-start-2 sm:row-start-1">
              {(canChange || item.notes !== null) && (
                <button
                  type="button"
                  aria-label={`Notes of ${item.title}`}
                  aria-expanded={notesShown}
                  aria-controls={notesId}
                  className={`relative ${SMALL_BUTTON}`}
                  onClick={() => setNotesShown(!notesShown)}
                >
                  <RowIcon className="sm:hidden">
                    <path d="M4 2.5h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1ZM5.5 6h5M5.5 8.5h5M5.5 11h3" />
                  </RowIcon>
                  <span className="hidden sm:inline">Notes</span>
                  {item.notes !== null && (
                    <span
                      aria-hidden="true"
                      className="absolute top-1 right-1 size-2 rounded-full bg-sky-600 sm:static sm:size-1.5 sm:bg-current"
                    />
                  )}
                </button>
              )}
              {canChange && (
                <button
                  type="button"
                  aria-label={`More actions for ${item.title}`}
                  aria-expanded={moreShown}
                  aria-controls={moreId}
                  className={`sm:hidden ${SMALL_BUTTON} ${moreShown ? 'bg-slate-100 text-slate-900' : ''}`}
                  onClick={() => setMoreShown(!moreShown)}
                >
                  <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" className="size-5">
                    <circle cx="3" cy="8" r="1.4" />
                    <circle cx="8" cy="8" r="1.4" />
                    <circle cx="13" cy="8" r="1.4" />
                  </svg>
                </button>
              )}
            </div>
          </div>
          {canChange && (
            <div
              id={moreId}
              className={`${
                moreShown ? 'flex' : 'hidden'
              } items-center justify-end gap-1 sm:col-start-3 sm:row-start-1 sm:flex sm:gap-0.5`}
            >
              {confirming ? (
                <>
                  <button
                    type="button"
                    autoFocus
                    className={SMALL_DANGER_BUTTON}
                    onClick={() => onChange({ kind: 'delete', item })}
                  >
                    Yes, delete
                  </button>
                  <button type="button" className={SMALL_BUTTON} onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  {onMove && (
                    <>
                      <MoveButton item={item} direction="up" disabled={waiting || !canMoveUp} onMove={onMove} />
                      <MoveButton item={item} direction="down" disabled={waiting || !canMoveDown} onMove={onMove} />
                    </>
                  )}
                  <button
                    type="button"
                    aria-label={`Delete ${item.title}`}
                    disabled={waiting}
                    className={SMALL_DANGER_BUTTON}
                    onClick={() => setConfirming(true)}
                  >
                    Delete
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      {notesShown && (
        <div id={notesId} className="pl-9">
          {canChange && !waiting ? (
            <NotesEditor
              item={item}
              onSave={(notes) => onChange({ kind: 'update', item, patch: { notes } })}
              onClose={() => setNotesShown(false)}
            />
          ) : (
            <p className="text-sm break-words whitespace-pre-line text-slate-600">{item.notes}</p>
          )}
        </div>
      )}
    </li>
  )
}

interface AssigneeControlProps {
  item: Item
  assignment: Assignment
  mine: boolean
  onChange: (change: ItemChange) => void
}

function assigneeValue(assignee: Pick<Assignee, 'kind' | 'id'>): string {
  return `${assignee.kind}:${assignee.id}`
}

/** Who works on the item, as a select to give it to someone else, with "Pick up" for a free one. */
function AssigneeControl({ item, assignment, mine, onChange }: AssigneeControlProps) {
  const { assignees, me } = assignment
  // The current assignee is always a choice, also before the others are known.
  const current = item.assignee
  const choices =
    current === null || assignees.some((assignee) => sameAssignee(assignee, current)) ? assignees : [current, ...assignees]

  return (
    <span className="flex items-center gap-2 px-1">
      <select
        aria-label={`Assignee of ${item.title}`}
        value={current === null ? '' : assigneeValue(current)}
        onChange={(event) =>
          onChange({
            kind: 'assign',
            item,
            assignee: choices.find((assignee) => assigneeValue(assignee) === event.target.value) ?? null,
          })
        }
        className={`h-9 min-w-0 shrink truncate rounded-md border px-1.5 text-xs focus:border-slate-500 focus:outline-none sm:h-auto sm:py-0.5 ${
          mine ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-slate-300 bg-white text-slate-700'
        }`}
      >
        <option value="">Unassigned</option>
        {choices.map((assignee) => (
          <option key={assigneeValue(assignee)} value={assigneeValue(assignee)}>
            {assignee.name}
            {assignee.kind === 'agent' ? ' (agent)' : me !== null && sameAssignee(assignee, me) ? ' (you)' : ''}
          </option>
        ))}
      </select>
      {current === null && item.status === 'open' && me !== null && (
        <button
          type="button"
          aria-label={`Pick up ${item.title}`}
          className="h-9 shrink-0 rounded-md border border-slate-300 bg-white px-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 sm:h-auto sm:px-2 sm:py-0.5 sm:text-xs"
          onClick={() => onChange({ kind: 'assign', item, assignee: me })}
        >
          Pick up
        </button>
      )}
    </span>
  )
}

/** Says that an AI agent, not a person, added or completed the item. */
function AgentMarker({ children }: { children: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-1.5 py-0.5 text-xs font-medium text-violet-800">
      <ModeIcon mode="ai_only" className="size-3" />
      {children}
    </span>
  )
}

/** A 16px line icon for a row button. */
function RowIcon({ className = '', children }: { className?: string; children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`size-5 shrink-0 ${className}`}
    >
      {children}
    </svg>
  )
}

interface MoveButtonProps {
  item: Item
  direction: Direction
  disabled: boolean
  onMove: (direction: Direction) => void
}

function MoveButton({ item, direction, disabled, onMove }: MoveButtonProps) {
  return (
    <button
      type="button"
      aria-label={`Move ${item.title} ${direction}`}
      data-move={`${item.id}:${direction}`}
      disabled={disabled}
      className={SMALL_BUTTON}
      onClick={() => onMove(direction)}
    >
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className="size-4"
      >
        {direction === 'up' ? <path d="M8 13V3.5M3.5 7.5 8 3l4.5 4.5" /> : <path d="M8 3v9.5M3.5 8.5 8 13l4.5-4.5" />}
      </svg>
      <span className="sm:hidden">{direction === 'up' ? 'Up' : 'Down'}</span>
    </button>
  )
}

interface EditableTitleProps {
  item: Item
  className: string
  onSave: (title: string) => void
}

/**
 * The title as a button that turns into a text field. Enter or leaving the field saves,
 * Escape keeps the old title; an empty title is not saved.
 */
function EditableTitle({ item, className, onSave }: EditableTitleProps) {
  const [draft, setDraft] = useState<string | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const cancelled = useRef(false)
  // Finished with the keyboard: the focus goes back to the title instead of getting lost.
  const refocus = useRef(false)

  useEffect(() => {
    if (draft === null && refocus.current) {
      refocus.current = false
      button.current?.focus()
    }
  }, [draft])

  if (draft === null) {
    return (
      <button
        ref={button}
        type="button"
        aria-label={`Edit title of ${item.title}`}
        title="Edit title"
        data-title
        className={`rounded-md px-1 py-0.5 text-left wrap-anywhere hover:bg-slate-100 ${className}`}
        onClick={() => setDraft(item.title)}
      >
        {item.title}
      </button>
    )
  }

  function finish() {
    const title = (draft ?? '').trim()
    if (!cancelled.current && title !== '' && title !== item.title) {
      onSave(title)
    }
    cancelled.current = false
    setDraft(null)
  }

  return (
    <input
      type="text"
      aria-label="Title"
      autoFocus
      maxLength={500}
      autoComplete="off"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === 'Escape') {
          // Handled here: the key must not reach the button that gets the focus next.
          event.preventDefault()
          cancelled.current = event.key === 'Escape'
          refocus.current = true
          event.currentTarget.blur()
        }
      }}
      className="w-full rounded-md border border-slate-300 bg-white px-1 py-0.5 text-slate-900 focus:border-slate-500 focus:outline-none"
    />
  )
}

interface NotesEditorProps {
  item: Item
  onSave: (notes: string | null) => void
  onClose: () => void
}

/** The notes of an item in a text area; saving empty notes removes them. */
function NotesEditor({ item, onSave, onClose }: NotesEditorProps) {
  const [draft, setDraft] = useState<string | null>(null)
  const saved = item.notes ?? ''
  const changed = draft !== null && draft.trim() !== saved

  function save(event: FormEvent) {
    event.preventDefault()
    if (changed) {
      const notes = draft.trim()
      onSave(notes === '' ? null : notes)
    }
    setDraft(null)
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-2">
      <textarea
        aria-label={`Notes of ${item.title}`}
        rows={3}
        maxLength={10000}
        placeholder="Add notes…"
        value={draft ?? saved}
        onChange={(event) => setDraft(event.target.value)}
        className={`text-sm ${TEXT_INPUT}`}
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!changed}
          className="min-h-9 rounded-md bg-slate-900 px-2.5 py-1 text-sm font-medium text-white hover:bg-slate-700 disabled:bg-slate-300 sm:min-h-0"
        >
          Save notes
        </button>
        <button type="button" className={SMALL_BUTTON} onClick={onClose}>
          Close
        </button>
      </div>
    </form>
  )
}
