import { expect, test } from 'vitest'

import { ACME, ADA, auditEvent, project, todoList } from '../test/api'
import { describeEvent, eventChanges } from './describe'

const WEBSITE = project(ACME, 'p1', 'Website')
const BACKLOG = todoList(WEBSITE, 'l1', 'Backlog')
const IN_LIST = { scope: 'list' } as const
const IN_PROJECT = { scope: 'project', listNames: new Map([[BACKLOG.id, BACKLOG.name]]) } as const
const GRACE = { kind: 'user', id: 'u2', name: 'Grace Hopper' }
// The actor of the `auditEvent` fixture.
const ADA_ACTOR = { kind: 'user', id: ADA.user.id, name: ADA.user.name }

test.each([
  ['project.created', { name: 'Website' }, 'created the project "Website"'],
  ['project.updated', { name: 'Website', changes: {} }, 'changed the project "Website"'],
  ['project.deleted', { name: 'Website' }, 'deleted the project "Website"'],
  ['list.created', { name: 'Backlog', mode: 'mixed' }, 'created the list "Backlog"'],
  ['list.updated', { name: 'Backlog', changes: {} }, 'changed the list "Backlog"'],
  ['list.deleted', { name: 'Backlog' }, 'deleted the list "Backlog"'],
  ['item.created', { title: 'Buy milk' }, 'added "Buy milk"'],
  ['item.updated', { title: 'Buy milk', changes: {} }, 'edited "Buy milk"'],
  ['item.completed', { title: 'Buy milk' }, 'completed "Buy milk"'],
  ['item.reopened', { title: 'Buy milk' }, 'reopened "Buy milk"'],
  ['item.moved', { title: 'Buy milk', changes: {} }, 'moved "Buy milk"'],
  ['item.deleted', { title: 'Buy milk' }, 'deleted "Buy milk"'],
  ['item.assigned', { title: 'Buy milk', assignee: GRACE, previous_assignee: null }, 'assigned "Buy milk" to Grace Hopper'],
  ['item.assigned', { title: 'Buy milk', assignee: ADA_ACTOR, previous_assignee: GRACE }, 'picked up "Buy milk"'],
  ['item.unassigned', { title: 'Buy milk', previous_assignee: GRACE }, 'unassigned "Buy milk" from Grace Hopper'],
  ['item.unassigned', { title: 'Buy milk', previous_assignee: ADA_ACTOR }, 'released "Buy milk"'],
  ['project_grant.set', { principal: GRACE, role: { old: null, new: 'editor' } }, 'gave Grace Hopper the role Editor on the project'],
  ['project_grant.set', { principal: GRACE, role: { old: 'viewer', new: 'editor' } }, 'changed the role of Grace Hopper on the project'],
  ['project_grant.revoked', { principal: GRACE, role: 'editor' }, 'removed the role Editor of Grace Hopper on the project'],
  ['list_grant.set', { principal: GRACE, role: { old: null, new: 'viewer' } }, 'gave Grace Hopper the role Viewer on this list'],
  ['list_grant.set', { principal: GRACE, role: { old: null, new: 'none' } }, 'gave Grace Hopper no access on this list'],
  ['list_grant.revoked', { principal: GRACE, role: 'none' }, 'removed the role No access of Grace Hopper on this list'],
  ['token.issued', {}, 'did something else (token.issued)'],
])('%s in a list log: %s', (action, details, sentence) => {
  expect(describeEvent(auditEvent(BACKLOG, action, details), IN_LIST)).toBe(sentence)
})

test('a project log names the list of an item or a list grant, when the list still exists', () => {
  const added = auditEvent(BACKLOG, 'item.created', { title: 'Buy milk' })
  expect(describeEvent(added, IN_PROJECT)).toBe('added "Buy milk" in the list "Backlog"')
  expect(describeEvent({ ...added, list_id: 'gone' }, IN_PROJECT)).toBe('added "Buy milk"')

  const granted = auditEvent(BACKLOG, 'list_grant.set', { principal: GRACE, role: { old: null, new: 'admin' } })
  expect(describeEvent(granted, IN_PROJECT)).toBe('gave Grace Hopper the role Admin on the list "Backlog"')
  expect(describeEvent({ ...granted, list_id: 'gone' }, IN_PROJECT)).toBe('gave Grace Hopper the role Admin on a list')
  // The list's own events carry its name already.
  expect(describeEvent(auditEvent(BACKLOG, 'list.created', { name: 'Backlog' }), IN_PROJECT)).toBe(
    'created the list "Backlog"',
  )
})

test('details that are missing or odd still give a sentence', () => {
  expect(describeEvent(auditEvent(BACKLOG, 'item.completed', {}), IN_LIST)).toBe('completed an item')
  expect(describeEvent(auditEvent(BACKLOG, 'list.deleted', { name: 7 }), IN_LIST)).toBe('deleted the list')
  expect(describeEvent(auditEvent(BACKLOG, 'list_grant.set', { principal: { kind: 'agent' } }), IN_LIST)).toBe(
    'gave an agent the role unknown on this list',
  )
  expect(eventChanges(auditEvent(BACKLOG, 'item.updated', { changes: 'no' }))).toEqual([])
})

test('changes: the fields of an update with the old and the new value', () => {
  const edited = auditEvent(BACKLOG, 'item.updated', {
    title: 'Buy oat milk',
    changes: { title: { old: 'Buy milk', new: 'Buy oat milk' }, notes: { old: null, new: 'Two cartons.' } },
  })
  expect(eventChanges(edited)).toEqual([
    { field: 'title', label: 'Title', old: '"Buy milk"', new: '"Buy oat milk"' },
    { field: 'notes', label: 'Notes', old: 'nothing', new: '"Two cartons."' },
  ])

  const list = auditEvent(BACKLOG, 'list.updated', { name: 'Backlog', changes: { mode: { old: 'human_only', new: 'mixed' } } })
  expect(eventChanges(list)).toEqual([{ field: 'mode', label: 'Mode', old: 'Human only', new: 'Mixed' }])

  const moved = auditEvent(BACKLOG, 'item.moved', { title: 'Buy milk', changes: { position: { old: 3, new: 1 } } })
  expect(eventChanges(moved)).toEqual([{ field: 'position', label: 'Position', old: '3', new: '1' }])

  // A changed grant shows both roles; a new one says its role in the sentence.
  const changed = auditEvent(BACKLOG, 'list_grant.set', { principal: GRACE, role: { old: 'viewer', new: 'none' } })
  expect(eventChanges(changed)).toEqual([{ field: 'role', label: 'Role', old: 'Viewer', new: 'No access' }])
  const fresh = auditEvent(BACKLOG, 'list_grant.set', { principal: GRACE, role: { old: null, new: 'viewer' } })
  expect(eventChanges(fresh)).toEqual([])
  expect(eventChanges(auditEvent(BACKLOG, 'item.completed', { title: 'Buy milk' }))).toEqual([])
})
