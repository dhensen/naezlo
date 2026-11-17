import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'

import { api, unwrap } from '../api/client'
import type { Me, Schemas } from '../api/client'
import { ME_KEY } from '../api/queryClient'
import { useMe } from '../auth/hooks'

export type Organization = Schemas['MyOrganizationOut']
export type Project = Schemas['ProjectOut']

/**
 * The organization of the current route (`/o/:orgSlug/...`): `slug` is undefined outside
 * such a route, `organization` null when the user is not a member of one with that slug.
 */
export function useCurrentOrganization(): { slug: string | undefined; organization: Organization | null } {
  const { orgSlug } = useParams()
  const me = useMe()
  const organization = me.data?.organizations.find((candidate) => candidate.slug === orgSlug)
  return { slug: orgSlug, organization: organization ?? null }
}

/** Create an organization; the user's list of organizations (`useMe`) gets it at once. */
export function useCreateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['OrganizationIn']) => unwrap(api.POST('/api/orgs', { body })),
    onSuccess: (organization) => {
      queryClient.setQueryData<Me | null>(ME_KEY, (me) =>
        me ? { ...me, organizations: [...me.organizations, organization] } : me,
      )
    },
  })
}

export function projectsKey(organizationId: string) {
  return ['orgs', organizationId, 'projects'] as const
}

/** The projects of an organization that the user can see, oldest first. */
export function useProjects(organizationId: string) {
  return useQuery({
    queryKey: projectsKey(organizationId),
    queryFn: () =>
      unwrap(api.GET('/api/orgs/{org_id}/projects', { params: { path: { org_id: organizationId } } })),
  })
}

export type Member = Schemas['MemberOut']
export type Invitation = Schemas['InvitationOut']

/** Rename an organization; the switcher and every page follow through `useMe`. The slug stays. */
export function useRenameOrganization(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['OrganizationIn']) =>
      unwrap(api.PATCH('/api/orgs/{org_id}', { params: { path: { org_id: organizationId } }, body })),
    onSuccess: (organization) => {
      queryClient.setQueryData<Me | null>(ME_KEY, (me) =>
        me
          ? {
              ...me,
              organizations: me.organizations.map((candidate) =>
                candidate.id === organization.id ? organization : candidate,
              ),
            }
          : me,
      )
    },
  })
}

export function membersKey(organizationId: string) {
  return ['orgs', organizationId, 'members'] as const
}

/** Everyone in the organization; every member may read this. */
export function useMembers(organizationId: string) {
  return useQuery({
    queryKey: membersKey(organizationId),
    queryFn: () =>
      unwrap(api.GET('/api/orgs/{org_id}/members', { params: { path: { org_id: organizationId } } })),
  })
}

/** Change a member's role. A change to the user's own role also reloads `useMe`. */
export function useChangeMemberRole(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Member['role'] }) =>
      unwrap(
        api.PATCH('/api/orgs/{org_id}/members/{user_id}', {
          params: { path: { org_id: organizationId, user_id: userId } },
          body: { role },
        }),
      ),
    onSuccess: (member) => {
      queryClient.setQueryData<Member[]>(membersKey(organizationId), (members) =>
        members?.map((candidate) => (candidate.user_id === member.user_id ? member : candidate)),
      )
      if (queryClient.getQueryData<Me | null>(ME_KEY)?.user.id === member.user_id) {
        return queryClient.invalidateQueries({ queryKey: ME_KEY })
      }
    },
  })
}

/**
 * Remove a member, or leave (the user's own id). After leaving, the caller navigates away
 * and calls `forgetOrganization` in the same step, so no page of the organization is
 * rendered without it.
 */
export function useRemoveMember(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.DELETE('/api/orgs/{org_id}/members/{user_id}', {
          params: { path: { org_id: organizationId, user_id: userId } },
        }),
      ),
    onSuccess: (_nothing, userId) => {
      queryClient.setQueryData<Member[]>(membersKey(organizationId), (members) =>
        members?.filter((candidate) => candidate.user_id !== userId),
      )
    },
  })
}

/** Take an organization the user is no longer in out of `useMe`, with everything loaded for it. */
export function useForgetOrganization() {
  const queryClient = useQueryClient()
  return (organizationId: string) => {
    queryClient.setQueryData<Me | null>(ME_KEY, (me) =>
      me
        ? { ...me, organizations: me.organizations.filter((candidate) => candidate.id !== organizationId) }
        : me,
    )
    queryClient.removeQueries({ queryKey: ['orgs', organizationId] })
  }
}

export function invitationsKey(organizationId: string) {
  return ['orgs', organizationId, 'invitations'] as const
}

/** The pending invitations; only owners and admins may read them (`enabled`). */
export function useInvitations(organizationId: string, enabled: boolean) {
  return useQuery({
    queryKey: invitationsKey(organizationId),
    queryFn: () =>
      unwrap(api.GET('/api/orgs/{org_id}/invitations', { params: { path: { org_id: organizationId } } })),
    enabled,
  })
}

/** Invite an email address: someone with an account is a member at once, anyone else gets a pending invitation. */
export function useInvite(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['InvitationIn']) =>
      unwrap(api.POST('/api/orgs/{org_id}/invitations', { params: { path: { org_id: organizationId } }, body })),
    onSuccess: async (result) => {
      const queryKey = result.status === 'added' ? membersKey(organizationId) : invitationsKey(organizationId)
      // A first fetch that is still under way started before the invitation and would be
      // reused by the invalidation: cancel it, so the list is asked for again.
      await queryClient.cancelQueries({ queryKey })
      await queryClient.invalidateQueries({ queryKey })
    },
  })
}

/** Email a pending invitation again; only offered when the server sends email. */
export function useResendInvitation(organizationId: string) {
  return useMutation({
    mutationFn: (invitation: Invitation) =>
      unwrap(
        api.POST('/api/orgs/{org_id}/invitations/{invitation_id}/send', {
          params: { path: { org_id: organizationId, invitation_id: invitation.id } },
        }),
      ),
  })
}

export function useRevokeInvitation(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (invitationId: string) =>
      unwrap(
        api.DELETE('/api/orgs/{org_id}/invitations/{invitation_id}', {
          params: { path: { org_id: organizationId, invitation_id: invitationId } },
        }),
      ),
    onSuccess: (_nothing, invitationId) => {
      queryClient.setQueryData<Invitation[]>(invitationsKey(organizationId), (invitations) =>
        invitations?.filter((candidate) => candidate.id !== invitationId),
      )
    },
  })
}
