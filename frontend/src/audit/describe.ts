import { modeInfo } from '../lists/modes'
import type { ListMode } from '../lists/modes'
import type { ListRole } from '../sharing/hooks'
import { ROLE_LABELS } from '../sharing/roles'
import type { AuditEvent } from './hooks'

// Turns an audit event into words. What an event carries in `details` is decided by the
// services that record it (DECISIONS.md, "Audit event recording"); everything is read
// defensively, because `details` is free-form JSON and old events stay as they were written.

/** Where the log is shown. In a project's log an event says which list it is about. */
export interface DescribeContext {
  scope: 'project' | 'list'
  /** The names of the project's lists by id; a deleted list is not in it. */
  listNames?: ReadonlyMap<string, string>
}

/** One changed field of an update, ready to show. */
export interface FieldChange {
  field: string
  label: string
  old: string
  new: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' && value !== '' ? value : fallback
}

function quoted(value: unknown, fallback: string): string {
  return typeof value === 'string' && value !== '' ? `"${value}"` : fallback
}

function roleLabel(value: unknown): string {
  return typeof value === 'string' && value in ROLE_LABELS ? ROLE_LABELS[value as ListRole] : text(value, 'unknown')
}

/** The list an event of a project's log is about, as the end of a sentence. */
function listOf(event: AuditEvent, context: DescribeContext, preposition: string): string {
  if (context.scope === 'list') {
    return preposition === 'in' ? '' : ` ${preposition} this list`
  }
  const name = event.list_id === null ? undefined : context.listNames?.get(event.list_id)
  if (name !== undefined) {
    return ` ${preposition} the list "${name}"`
  }
  return preposition === 'in' ? '' : ` ${preposition} a list`
}

function isActor(event: AuditEvent, principal: Record<string, unknown>): boolean {
  return principal.kind === event.actor.kind && principal.id === event.actor.id
}

/** `picked up "X"` for the actor's own assignment, `assigned "X" to Grace` for someone else's. */
function assignmentSentence(event: AuditEvent, item: string): string {
  const key = event.action === 'item.assigned' ? 'assignee' : 'previous_assignee'
  const principal = isRecord(event.details[key]) ? event.details[key] : {}
  const name = text(principal.name, principal.kind === 'agent' ? 'an agent' : 'someone')
  if (event.action === 'item.assigned') {
    return isActor(event, principal) ? `picked up ${item}` : `assigned ${item} to ${name}`
  }
  return isActor(event, principal) ? `released ${item}` : `unassigned ${item} from ${name}`
}

function grantSentence(event: AuditEvent, where: string): string {
  const principal = isRecord(event.details.principal) ? event.details.principal : {}
  const name = text(principal.name, principal.kind === 'agent' ? 'an agent' : 'someone')
  const role = event.details.role
  if (event.action.endsWith('.revoked')) {
    return `removed the role ${roleLabel(role)} of ${name} ${where}`
  }
  const { old, new: next } = isRecord(role) ? role : { old: null, new: undefined }
  if (old !== null && old !== undefined) {
    return `changed the role of ${name} ${where}`
  }
  return next === 'none' ? `gave ${name} no access ${where}` : `gave ${name} the role ${roleLabel(next)} ${where}`
}

/**
 * What the actor did, to follow their name: `completed "Write tests"`. An action this
 * version does not know is named as it is stored.
 */
export function describeEvent(event: AuditEvent, context: DescribeContext): string {
  const { details } = event
  const item = `${quoted(details.title, 'an item')}${listOf(event, context, 'in')}`
  const project = `the project ${quoted(details.name, '')}`.trimEnd()
  const list = `the list ${quoted(details.name, '')}`.trimEnd()
  switch (event.action) {
    case 'project.created':
      return `created ${project}`
    case 'project.updated':
      return `changed ${project}`
    case 'project.deleted':
      return `deleted ${project}`
    case 'list.created':
      return `created ${list}`
    case 'list.updated':
      return `changed ${list}`
    case 'list.deleted':
      return `deleted ${list}`
    case 'item.created':
      return `added ${item}`
    case 'item.updated':
      return `edited ${item}`
    case 'item.completed':
      return `completed ${item}`
    case 'item.reopened':
      return `reopened ${item}`
    case 'item.moved':
      return `moved ${item}`
    case 'item.deleted':
      return `deleted ${item}`
    case 'item.assigned':
    case 'item.unassigned':
      return assignmentSentence(event, item)
    case 'project_grant.set':
    case 'project_grant.revoked':
      return grantSentence(event, 'on the project')
    case 'list_grant.set':
    case 'list_grant.revoked':
      return grantSentence(event, listOf(event, context, 'on').trimStart())
    default:
      return `did something else (${event.action})`
  }
}

const FIELD_LABELS: Record<string, string> = {
  name: 'Name',
  description: 'Description',
  mode: 'Mode',
  assignment_required: 'Assignment required',
  title: 'Title',
  notes: 'Notes',
  position: 'Position',
  role: 'Role',
}

function shown(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return 'nothing'
  }
  if (field === 'mode' && typeof value === 'string') {
    return modeInfo(value as ListMode).label
  }
  if (field === 'role') {
    return roleLabel(value)
  }
  if (typeof value === 'boolean') {
    return value ? 'on' : 'off'
  }
  if (typeof value === 'string') {
    return `"${value}"`
  }
  return typeof value === 'number' ? String(value) : JSON.stringify(value)
}

/**
 * The fields an event changed, with the value before and after: the `changes` of an update
 * or a move, and the role of a grant that was changed (not of a new one).
 */
export function eventChanges(event: AuditEvent): FieldChange[] {
  const changes: Record<string, unknown> = isRecord(event.details.changes) ? { ...event.details.changes } : {}
  const role = event.details.role
  if (event.action.endsWith('_grant.set') && isRecord(role) && role.old !== null && role.old !== undefined) {
    changes.role = role
  }
  return Object.entries(changes).flatMap(([field, change]) =>
    isRecord(change)
      ? [
          {
            field,
            label: FIELD_LABELS[field] ?? field,
            old: shown(field, change.old),
            new: shown(field, change.new),
          },
        ]
      : [],
  )
}
