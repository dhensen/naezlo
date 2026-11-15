import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import type { Schemas } from '../api/client'
import { useMe } from '../auth/hooks'
import { ErrorMessage } from '../components/ErrorMessage'
import {
  useChangeMemberRole,
  useCurrentOrganization,
  useForgetOrganization,
  useInvitations,
  useInvite,
  useMembers,
  useRemoveMember,
  useRenameOrganization,
  useRevokeInvitation,
} from '../orgs/hooks'
import type { Member, Organization } from '../orgs/hooks'

type Role = Member['role']

const ROLE_LABELS: Record<Role, string> = { owner: 'Owner', admin: 'Admin', member: 'Member' }

const INPUT = 'rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-slate-500 focus:outline-none'
const PRIMARY_BUTTON =
  'rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60'
const SMALL_BUTTON =
  'rounded-md border border-slate-300 px-2.5 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60 sm:py-1'
const DANGER_BUTTON =
  'rounded-md border border-red-300 px-2.5 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60 sm:py-1'
// Below `sm` a member is a block of lines (name, email, then role and action) instead of a table row.
const MEMBER_ROW = 'flex flex-wrap items-center gap-x-3 py-2 sm:table-row'
const SECTION = 'flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4'

/** Settings of an organization (`/o/:orgSlug/settings`): name, members and invitations. */
export function OrganizationSettingsPage() {
  const { organization } = useCurrentOrganization()
  if (organization === null) {
    return null
  }
  const canManage = organization.role === 'owner' || organization.role === 'admin'

  return (
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-6 p-4 sm:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Organization settings</h1>
        {!canManage && (
          <p className="text-sm text-slate-600">Only owners and admins can change these settings.</p>
        )}
      </div>
      {/* Keyed, so the forms start empty again in another organization. */}
      <NameSection key={`name-${organization.id}`} organization={organization} canManage={canManage} />
      <MembersSection key={`members-${organization.id}`} organization={organization} canManage={canManage} />
      {canManage && <InvitationsSection key={`invitations-${organization.id}`} organization={organization} />}
    </main>
  )
}

interface SectionProps {
  organization: Organization
  canManage: boolean
}

function NameSection({ organization, canManage }: SectionProps) {
  const rename = useRenameOrganization(organization.id)
  const [name, setName] = useState(organization.name)

  function submit(event: FormEvent) {
    event.preventDefault()
    rename.mutate({ name }, { onSuccess: (renamed) => setName(renamed.name) })
  }

  return (
    <section aria-labelledby="settings-name" className={SECTION}>
      <h2 id="settings-name" className="text-lg font-semibold tracking-tight">
        Name
      </h2>
      {canManage ? (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
              Organization name
              <input
                type="text"
                required
                maxLength={200}
                autoComplete="off"
                value={name}
                onChange={(event) => {
                  setName(event.target.value)
                  rename.reset()
                }}
                className={INPUT}
              />
            </label>
            <button
              type="submit"
              disabled={rename.isPending || name.trim() === '' || name.trim() === organization.name}
              className={PRIMARY_BUTTON}
            >
              Rename
            </button>
          </div>
          {rename.isSuccess && (
            <p role="status" className="text-sm text-green-700">
              Renamed. Links to this organization stay the same.
            </p>
          )}
          <ErrorMessage error={rename.error} />
        </form>
      ) : (
        <p className="text-slate-900">{organization.name}</p>
      )}
    </section>
  )
}

/** The roles the viewer may choose for this member, or null when they may not change the role. */
function roleChoices(viewerRole: Role, member: Member): Role[] | null {
  if (viewerRole === 'owner') {
    return ['owner', 'admin', 'member']
  }
  // Anything that involves the owner role needs an owner.
  if (viewerRole === 'admin' && member.role !== 'owner') {
    return ['admin', 'member']
  }
  return null
}

function MembersSection({ organization, canManage }: SectionProps) {
  const me = useMe()
  const navigate = useNavigate()
  const members = useMembers(organization.id)
  const changeRole = useChangeMemberRole(organization.id)
  const remove = useRemoveMember(organization.id)
  const forgetOrganization = useForgetOrganization()
  const [confirming, setConfirming] = useState<string | null>(null)
  const myId = me.data?.user.id
  const busy = changeRole.isPending || remove.isPending

  function removeMember(member: Member) {
    changeRole.reset()
    remove.mutate(member.user_id, {
      onSuccess: () => {
        if (member.user_id === myId) {
          void navigate('/')
          forgetOrganization(organization.id)
        }
      },
      onSettled: () => setConfirming(null),
    })
  }

  return (
    <section aria-labelledby="settings-members" className={SECTION}>
      <h2 id="settings-members" className="text-lg font-semibold tracking-tight">
        Members
      </h2>
      {members.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={members.error} />
      <ErrorMessage error={changeRole.error ?? remove.error} />
      {members.data && (
        <div className="overflow-x-auto">
          <table aria-labelledby="settings-members" className="w-full text-left text-sm">
            <thead className="hidden text-xs tracking-wide text-slate-500 uppercase sm:table-header-group">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Name
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Email
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Role
                </th>
                <th scope="col" className="py-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="block divide-y divide-slate-100 border-t border-slate-200 sm:table-row-group">
              {members.data.map((member) => {
                const isSelf = member.user_id === myId
                const choices = roleChoices(organization.role, member)
                const mayRemove = isSelf || (canManage && choices !== null)
                const action = isSelf ? 'Leave' : 'Remove'
                return (
                  <tr key={member.user_id} className={MEMBER_ROW}>
                    <th scope="row" className="basis-full font-medium text-slate-900 sm:py-2 sm:pr-3">
                      {member.name}
                      {isSelf && <span className="font-normal text-slate-500"> (you)</span>}
                    </th>
                    <td className="basis-full break-all text-slate-700 sm:py-2 sm:pr-3">{member.email}</td>
                    <td className="pt-1 text-slate-700 sm:py-2 sm:pr-3">
                      {choices ? (
                        <select
                          aria-label={`Role of ${member.name}`}
                          value={member.role}
                          disabled={busy}
                          onChange={(event) => {
                            remove.reset()
                            changeRole.mutate({ userId: member.user_id, role: event.target.value as Role })
                          }}
                          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm sm:py-1"
                        >
                          {choices.map((role) => (
                            <option key={role} value={role}>
                              {ROLE_LABELS[role]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        ROLE_LABELS[member.role]
                      )}
                    </td>
                    <td className="ml-auto pt-1 text-right whitespace-nowrap sm:py-2">
                      {mayRemove &&
                        (confirming === member.user_id ? (
                          <span className="inline-flex items-center gap-2">
                            <button
                              type="button"
                              disabled={busy}
                              className={DANGER_BUTTON}
                              onClick={() => removeMember(member)}
                            >
                              {isSelf ? 'Yes, leave' : 'Yes, remove'}
                            </button>
                            <button type="button" className={SMALL_BUTTON} onClick={() => setConfirming(null)}>
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            aria-label={isSelf ? 'Leave organization' : `Remove ${member.name}`}
                            className={SMALL_BUTTON}
                            onClick={() => setConfirming(member.user_id)}
                          >
                            {action}
                          </button>
                        ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function InvitationsSection({ organization }: { organization: Organization }) {
  const invitations = useInvitations(organization.id, true)
  const invite = useInvite(organization.id)
  const revoke = useRevokeInvitation(organization.id)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Schemas['InvitationRole']>('member')
  const roleId = useId()

  function submit(event: FormEvent) {
    event.preventDefault()
    invite.mutate({ email, role }, { onSuccess: () => setEmail('') })
  }

  return (
    <section aria-labelledby="settings-invitations" className={SECTION}>
      <h2 id="settings-invitations" className="text-lg font-semibold tracking-tight">
        Invitations
      </h2>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <label className="flex w-full min-w-0 flex-col gap-1 text-sm font-medium text-slate-700 sm:w-auto sm:flex-1">
          Email address
          <input
            type="email"
            inputMode="email"
            autoCapitalize="none"
            required
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={INPUT}
          />
        </label>
        {/* Not wrapped in the label: the options would become part of its name. */}
        <div className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700 sm:flex-none">
          <label htmlFor={roleId}>Role</label>
          <select
            id={roleId}
            value={role}
            onChange={(event) => setRole(event.target.value as Schemas['InvitationRole'])}
            className={INPUT}
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <button type="submit" disabled={invite.isPending} className={PRIMARY_BUTTON}>
          Invite
        </button>
      </form>
      {invite.data && (
        <p role="status" className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
          {invite.data.message}
        </p>
      )}
      <ErrorMessage error={invite.error} />

      <h3 className="mt-2 text-sm font-medium text-slate-700">Pending invitations</h3>
      {invitations.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={invitations.error} />
      <ErrorMessage error={revoke.error} />
      {invitations.data?.length === 0 && <p className="text-sm text-slate-500">No pending invitations.</p>}
      {invitations.data && invitations.data.length > 0 && (
        <ul aria-label="Pending invitations" className="divide-y divide-slate-100 border-t border-slate-200 text-sm">
          {invitations.data.map((invitation) => (
            <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="min-w-0 break-all text-slate-900">
                {invitation.email}
                <span className="text-slate-500"> · {ROLE_LABELS[invitation.role]}</span>
              </span>
              <button
                type="button"
                aria-label={`Revoke invitation for ${invitation.email}`}
                disabled={revoke.isPending}
                className={SMALL_BUTTON}
                onClick={() => revoke.mutate(invitation.id)}
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
