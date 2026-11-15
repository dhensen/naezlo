import { useState } from 'react'
import type { FormEvent } from 'react'

import { useMembers } from '../orgs/hooks'
import type { Project } from '../orgs/hooks'
import type { ProjectRole, TodoList } from '../projects/hooks'
import {
  useAgents,
  useInheritedGrants,
  useListGrants,
  useProjectGrants,
  useRevokeListGrant,
  useRevokeProjectGrant,
  useSetListGrant,
  useSetProjectGrant,
} from '../sharing/hooks'
import type { GrantRef, ListRole, PrincipalKind, PrincipalRef, ProjectGrant } from '../sharing/hooks'
import { ROLE_LABELS } from '../sharing/roles'
import { Dialog, DIALOG_CANCEL, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'

const PROJECT_ROLES: readonly ProjectRole[] = ['viewer', 'editor', 'admin']
const LIST_ROLES: readonly ListRole[] = ['viewer', 'editor', 'admin', 'none']

const SELECT =
  'rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-500 focus:outline-none'
const ROW_BUTTON = 'rounded-md px-2 py-1 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900'
const ROW_DANGER_BUTTON = 'rounded-md px-2 py-1 text-sm font-medium text-red-700 hover:bg-red-50'
const NOTE = 'rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700'
const ROWS = 'divide-y divide-slate-200 rounded-lg border border-slate-200'
const SECTION_HEADING = 'text-sm font-semibold text-slate-900'

/** Says whether a principal is a person or an AI agent. */
function KindMarker({ kind }: { kind: PrincipalKind }) {
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
        kind === 'agent' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700'
      }`}
    >
      {kind === 'agent' ? 'Agent' : 'Person'}
    </span>
  )
}

/** The shape the project and the list grants share. */
interface Grant<Role extends ListRole> extends GrantRef {
  name: string
  email: string | null
  role: Role
}

function Principal({ grant }: { grant: Grant<ListRole> }) {
  return (
    // Wide enough to push the controls to a line of their own in a narrow dialog.
    <div className="flex min-w-0 flex-1 basis-48 flex-col">
      <span className="flex min-w-0 items-center gap-2">
        <span className="font-medium break-words text-slate-900">{grant.name}</span>
        <KindMarker kind={grant.principal_kind} />
      </span>
      {grant.email !== null && <span className="text-xs break-all text-slate-600">{grant.email}</span>}
    </div>
  )
}

interface Mutation<Variables> {
  mutate: (variables: Variables, options?: { onSuccess?: () => void; onSettled?: () => void }) => void
  reset: () => void
  isPending: boolean
  error: unknown
}

interface GrantsProps<Role extends ListRole> {
  /** The name of the list of grants, also its heading. */
  heading: string
  /** What to say when there is no grant. */
  empty: string
  organizationId: string
  roles: readonly Role[]
  grants: { data: Grant<Role>[] | undefined; isPending: boolean; error: unknown }
  setGrant: Mutation<PrincipalRef & { role: Role }>
  revoke: Mutation<GrantRef>
}

/** The grants with a role to change and a way to revoke, and the picker that adds one. */
function Grants<Role extends ListRole>({
  heading,
  empty,
  organizationId,
  roles,
  grants,
  setGrant,
  revoke,
}: GrantsProps<Role>) {
  const [confirming, setConfirming] = useState<string | null>(null)
  const busy = setGrant.isPending || revoke.isPending

  function changeRole(grant: Grant<Role>, role: Role) {
    revoke.reset()
    setGrant.mutate({ principal_kind: grant.principal_kind, principal_id: grant.principal_id, role })
  }

  function revokeGrant(grant: Grant<Role>) {
    setGrant.reset()
    revoke.mutate(grant, { onSettled: () => setConfirming(null) })
  }

  return (
    <section className="flex flex-col gap-2">
      <h3 className={SECTION_HEADING}>{heading}</h3>
      {grants.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={grants.error} />
      <ErrorMessage error={setGrant.error ?? revoke.error} />
      {grants.data?.length === 0 && <p className="text-sm text-slate-600">{empty}</p>}
      {grants.data && grants.data.length > 0 && (
        <ul aria-label={heading} className={ROWS}>
          {grants.data.map((grant) => (
            <li key={grant.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <Principal grant={grant} />
              {confirming === grant.id ? (
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    disabled={busy}
                    className={ROW_DANGER_BUTTON}
                    onClick={() => revokeGrant(grant)}
                  >
                    Yes, remove
                  </button>
                  <button type="button" className={ROW_BUTTON} onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex shrink-0 items-center gap-1">
                  <select
                    aria-label={`Role of ${grant.name}`}
                    value={grant.role}
                    disabled={busy}
                    onChange={(event) => changeRole(grant, event.target.value as Role)}
                    className={SELECT}
                  >
                    {roles.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABELS[role]}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`Remove ${grant.name}`}
                    className={ROW_DANGER_BUTTON}
                    onClick={() => setConfirming(grant.id)}
                  >
                    Remove
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {grants.data && (
        <AddGrant organizationId={organizationId} roles={roles} taken={grants.data} busy={busy} setGrant={setGrant} />
      )}
    </section>
  )
}

interface AddGrantProps<Role extends ListRole> {
  organizationId: string
  roles: readonly Role[]
  /** The principals that have a grant already: they are not offered again. */
  taken: PrincipalRef[]
  busy: boolean
  setGrant: Mutation<PrincipalRef & { role: Role }>
}

/** The picker: a member or an agent of the organization, and the role they get. */
function AddGrant<Role extends ListRole>({ organizationId, roles, taken, busy, setGrant }: AddGrantProps<Role>) {
  const members = useMembers(organizationId)
  const agents = useAgents(organizationId)
  // `user:<id>` or `agent:<id>`; empty until someone is picked.
  const [picked, setPicked] = useState('')
  const [role, setRole] = useState<Role>(roles[0])

  const free = (kind: PrincipalKind, id: string) =>
    !taken.some((grant) => grant.principal_kind === kind && grant.principal_id === id)
  const people = (members.data ?? []).filter((member) => free('user', member.user_id))
  const freeAgents = (agents.data ?? []).filter((agent) => free('agent', agent.id))
  const loaded = members.data !== undefined && agents.data !== undefined

  function submit(event: FormEvent) {
    event.preventDefault()
    const [kind, id] = picked.split(':')
    if (id === undefined || (kind !== 'user' && kind !== 'agent')) {
      return
    }
    setGrant.mutate({ principal_kind: kind, principal_id: id, role }, { onSuccess: () => setPicked('') })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <ErrorMessage error={members.error ?? agents.error} />
      {loaded && people.length === 0 && freeAgents.length === 0 ? (
        <p className="text-sm text-slate-600">Every member and agent of the organization is listed here.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Person or agent"
            required
            value={picked}
            onChange={(event) => setPicked(event.target.value)}
            className={`${SELECT} min-w-0 flex-1`}
          >
            <option value="">{loaded ? 'Choose a person or an agent…' : 'Loading…'}</option>
            {people.length > 0 && (
              <optgroup label="People">
                {people.map((member) => (
                  <option key={member.user_id} value={`user:${member.user_id}`}>
                    {member.name} ({member.email})
                  </option>
                ))}
              </optgroup>
            )}
            {freeAgents.length > 0 && (
              <optgroup label="Agents">
                {freeAgents.map((agent) => (
                  <option key={agent.id} value={`agent:${agent.id}`}>
                    {agent.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <select
            aria-label="Role"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            className={SELECT}
          >
            {roles.map((candidate) => (
              <option key={candidate} value={candidate}>
                {ROLE_LABELS[candidate]}
              </option>
            ))}
          </select>
          <button type="submit" disabled={busy || picked === ''} className={DIALOG_SUBMIT}>
            Add
          </button>
        </div>
      )}
    </form>
  )
}

const OWNERS_NOTE = 'Owners and admins of the organization always have full access.'

function Done({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex justify-end">
      <button type="button" className={DIALOG_CANCEL} onClick={onClose}>
        Done
      </button>
    </div>
  )
}

/** Who a project is shared with: the grants, their roles, and a picker to add one. */
export function ShareProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const grants = useProjectGrants(project.id)
  const setGrant = useSetProjectGrant(project)
  const revoke = useRevokeProjectGrant(project)

  return (
    <Dialog title={`Share ${project.name}`} wide onClose={onClose}>
      <div className="mt-4 flex flex-col gap-4">
        <p className="text-sm text-slate-600">
          A role on the project counts for all its lists, unless a list gives someone a role of their own.{' '}
          {OWNERS_NOTE}
        </p>
        <Grants
          heading="People and agents with access"
          empty="Nobody has a role on this project yet."
          organizationId={project.organization_id}
          roles={PROJECT_ROLES}
          grants={grants}
          setGrant={setGrant}
          revoke={revoke}
        />
        <Done onClose={onClose} />
      </div>
    </Dialog>
  )
}

/**
 * Who a list is shared with: the grants on the list itself (which replace the role on the
 * project, `No access` hides the list) and, apart from them, what comes from the project.
 */
export function ShareListDialog({ list, onClose }: { list: TodoList; onClose: () => void }) {
  const grants = useListGrants(list.id)
  const inherited = useInheritedGrants(list.id)
  const setGrant = useSetListGrant(list)
  const revoke = useRevokeListGrant(list)

  const replaced = (grant: ProjectGrant) =>
    grants.data?.some(
      (own) => own.principal_kind === grant.principal_kind && own.principal_id === grant.principal_id,
    ) ?? false

  return (
    <Dialog title={`Share ${list.name}`} wide onClose={onClose}>
      <div className="mt-4 flex flex-col gap-4">
        {list.mode === 'human_only' && (
          <p role="note" className={NOTE}>
            This list is human only: AI agents cannot access it, whatever role they are given here or on the
            project.
          </p>
        )}
        <Grants
          heading="Access to this list only"
          empty="Nobody has a role of their own on this list."
          organizationId={list.organization_id}
          roles={LIST_ROLES}
          grants={grants}
          setGrant={setGrant}
          revoke={revoke}
        />
        <p className="text-sm text-slate-600">
          A role given here replaces the role from the project on this list. “No access” hides the list from
          someone.
        </p>
        <section className="flex flex-col gap-2">
          <h3 className={SECTION_HEADING}>Access from the project {list.project_name}</h3>
          {inherited.isPending && (
            <p role="status" className="text-sm text-slate-500">
              Loading…
            </p>
          )}
          <ErrorMessage error={inherited.error} />
          {inherited.data?.length === 0 && (
            <p className="text-sm text-slate-600">Nobody has a role on the project.</p>
          )}
          {inherited.data && inherited.data.length > 0 && (
            <ul aria-label="Access from the project" className={ROWS}>
              {inherited.data.map((grant) => (
                <li key={grant.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                  <Principal grant={grant} />
                  {replaced(grant) ? (
                    <span className="text-sm text-slate-500">
                      <s>{ROLE_LABELS[grant.role]}</s> (replaced on this list)
                    </span>
                  ) : (
                    <span className="text-sm text-slate-700">{ROLE_LABELS[grant.role]}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="text-sm text-slate-600">{OWNERS_NOTE}</p>
        </section>
        <Done onClose={onClose} />
      </div>
    </Dialog>
  )
}
