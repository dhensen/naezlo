import { useState } from 'react'

import { describeEvent, eventChanges } from '../audit/describe'
import type { DescribeContext } from '../audit/describe'
import { useActivity } from '../audit/hooks'
import type { ActionGroup, ActivityFilters, ActivityScope, AuditEvent } from '../audit/hooks'
import { ErrorMessage } from './ErrorMessage'
import { ModeIcon } from './ModeBadge'

const SELECT =
  'rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-500 focus:outline-none'

const ACTORS = [
  { value: '', label: 'Everyone' },
  { value: 'user', label: 'Humans' },
  { value: 'agent', label: 'Agents' },
] as const

type ActorChoice = (typeof ACTORS)[number]['value']

const TIME = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

interface ActivityLogProps {
  scope: ActivityScope
  /** For a project's log: the names of its lists, to say which list an event is about. */
  listNames?: ReadonlyMap<string, string>
}

/**
 * The audit log of a project or a list, newest first, with filters for who did it and what
 * kind of change it was. Only shown to admins: the API answers 403 to everyone else.
 */
export function ActivityLog({ scope, listNames }: ActivityLogProps) {
  const [actor, setActor] = useState<ActorChoice>('')
  const [group, setGroup] = useState<ActionGroup | ''>('')
  const filters: ActivityFilters = { actorKind: actor === '' ? null : actor, group: group === '' ? null : group }
  const activity = useActivity(scope, filters)
  const filtered = actor !== '' || group !== ''
  const events = activity.data?.pages.flatMap((page) => page.events)
  const context: DescribeContext = { scope: scope.kind, listNames }
  // In a project's log the project's own changes are with those of its lists.
  const groups: { value: ActionGroup | ''; label: string }[] = [
    { value: '', label: 'All changes' },
    { value: 'items', label: 'Items' },
    { value: 'lists', label: scope.kind === 'project' ? 'Project and lists' : 'Lists' },
    { value: 'sharing', label: 'Sharing' },
  ]

  return (
    <section aria-label="Activity" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-700">
        <span className="flex items-center gap-2">
          <label htmlFor="activity-actor">By</label>
          <select
            id="activity-actor"
            value={actor}
            onChange={(event) => setActor(event.target.value as ActorChoice)}
            className={SELECT}
          >
            {ACTORS.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        </span>
        <span className="flex items-center gap-2">
          <label htmlFor="activity-group">Changes to</label>
          <select
            id="activity-group"
            value={group}
            onChange={(event) => setGroup(event.target.value as ActionGroup | '')}
            className={SELECT}
          >
            {groups.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        </span>
      </div>
      {activity.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={activity.error} />
      {events?.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-slate-600">
          {filtered ? 'No activity matches these filters.' : 'Nothing has happened here yet.'}
        </p>
      )}
      {events && events.length > 0 && (
        <ol aria-label="Activity, newest first" className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {events.map((event) => (
            <EventRow key={event.id} event={event} context={context} />
          ))}
        </ol>
      )}
      {activity.hasNextPage && (
        <button
          type="button"
          disabled={activity.isFetchingNextPage}
          className="self-center rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400"
          onClick={() => void activity.fetchNextPage()}
        >
          {activity.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </button>
      )}
    </section>
  )
}

function EventRow({ event, context }: { event: AuditEvent; context: DescribeContext }) {
  const agent = event.actor.kind === 'agent'
  const changes = eventChanges(event)
  const time = new Date(event.created_at)

  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span
        title={agent ? 'AI agent' : 'Person'}
        data-actor-kind={event.actor.kind}
        className={`mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full ${
          agent ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700'
        }`}
      >
        <ModeIcon mode={agent ? 'ai_only' : 'human_only'} />
        <span className="sr-only">{agent ? 'AI agent:' : 'Person:'}</span>
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="break-words text-slate-900">
          <span className="font-medium">{event.actor.name}</span> {describeEvent(event, context)}
        </p>
        {changes.length > 0 && (
          <dl className="flex flex-col gap-0.5 text-sm text-slate-600">
            {changes.map((change) => (
              <div key={change.field} className="flex flex-wrap gap-x-1.5">
                <dt className="font-medium">{change.label}:</dt>
                <dd className="min-w-0 break-words whitespace-pre-line">
                  <span className="sr-only">from </span>
                  <span className="text-slate-500 line-through decoration-slate-400">{change.old}</span>
                  <span aria-hidden="true"> → </span>
                  <span className="sr-only"> to </span>
                  <span className="text-slate-900">{change.new}</span>
                </dd>
              </div>
            ))}
          </dl>
        )}
        <time dateTime={event.created_at} title={time.toLocaleString()} className="text-xs text-slate-500">
          {TIME.format(time)}
        </time>
      </div>
    </li>
  )
}
