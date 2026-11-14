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
