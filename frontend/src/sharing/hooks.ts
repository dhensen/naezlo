import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient, QueryKey } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Me, Schemas } from '../api/client'
import { applyToCache, ME_KEY } from '../api/queryClient'
import { listKey } from '../lists/hooks'
import { projectsKey } from '../orgs/hooks'
import type { Project } from '../orgs/hooks'
import { projectKey, projectListsKey } from '../projects/hooks'
import type { TodoList } from '../projects/hooks'

export type Agent = Schemas['AgentOut']
export type ProjectGrant = Schemas['GrantOut']
export type ListGrant = Schemas['ListGrantOut']
export type PrincipalKind = Schemas['PrincipalKind']
export type ListRole = Schemas['ListRole']

/** Who a grant is for: a member or an agent of the organization. */
export interface PrincipalRef {
  principal_kind: PrincipalKind
  principal_id: string
}

/** A grant, as far as revoking it needs to know. */
export interface GrantRef extends PrincipalRef {
  id: string
}

export function agentsKey(organizationId: string) {
  return ['orgs', organizationId, 'agents'] as const
}

/** The agents of an organization; every member may read them. */
export function useAgents(organizationId: string) {
  return useQuery({
    queryKey: agentsKey(organizationId),
    queryFn: () => unwrap(api.GET('/api/orgs/{org_id}/agents', { params: { path: { org_id: organizationId } } })),
  })
}

export function projectGrantsKey(projectId: string) {
  return ['projects', projectId, 'grants'] as const
}

export function listGrantsKey(listId: string) {
  return ['lists', listId, 'grants'] as const
}

export function inheritedGrantsKey(listId: string) {
  return ['lists', listId, 'grants', 'inherited'] as const
}

/** The grants on a project, oldest first. Project admins only. */
export function useProjectGrants(projectId: string) {
  return useQuery({
    queryKey: projectGrantsKey(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/projects/{project_id}/grants', { params: { path: { project_id: projectId } } })),
  })
}

/** The grants on a list itself, oldest first. List admins only. */
export function useListGrants(listId: string) {
  return useQuery({
    queryKey: listGrantsKey(listId),
    queryFn: () => unwrap(api.GET('/api/lists/{list_id}/grants', { params: { path: { list_id: listId } } })),
  })
}

/** The grants on the list's project: what applies to everyone without a grant on the list. */
export function useInheritedGrants(listId: string) {
  return useQuery({
    queryKey: inheritedGrantsKey(listId),
    queryFn: () =>
      unwrap(api.GET('/api/lists/{list_id}/grants/inherited', { params: { path: { list_id: listId } } })),
  })
}

function isMe(queryClient: QueryClient, grant: PrincipalRef): boolean {
  return grant.principal_kind === 'user' && queryClient.getQueryData<Me | null>(ME_KEY)?.user.id === grant.principal_id
}

/** Ask again for what the user's own role decides; a fetch from before the change is dropped. */
async function reload(queryClient: QueryClient, keys: QueryKey[]): Promise<void> {
  await Promise.all(
    keys.map(async (queryKey) => {
      await queryClient.cancelQueries({ queryKey, exact: true })
      await queryClient.invalidateQueries({ queryKey, exact: true })
    }),
  )
}

function withGrant<Grant extends { id: string }>(grants: Grant[], saved: Grant): Grant[] {
  return grants.some((grant) => grant.id === saved.id)
    ? grants.map((grant) => (grant.id === saved.id ? saved : grant))
    : [...grants, saved]
}

/** What follows the user's own role on a project: the page, its lists and the sidebar. */
function ownProjectKeys(project: Project): QueryKey[] {
  return [projectKey(project.id), projectListsKey(project.id), projectsKey(project.organization_id)]
}

/** Give a principal a role on a project, or change the one they have. */
export function useSetProjectGrant(project: Project) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['GrantIn']) =>
      unwrap(api.PUT('/api/projects/{project_id}/grants', { params: { path: { project_id: project.id } }, body })),
    onSuccess: async (saved) => {
      await applyToCache<ProjectGrant[]>(queryClient, projectGrantsKey(project.id), (grants) =>
        withGrant(grants, saved),
      )
      if (isMe(queryClient, saved)) {
        await reload(queryClient, ownProjectKeys(project))
      }
    },
  })
}

/** Take a grant on a project away. */
export function useRevokeProjectGrant(project: Project) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (grant: GrantRef) =>
      unwrap(
        api.DELETE('/api/projects/{project_id}/grants/{grant_id}', {
          params: { path: { project_id: project.id, grant_id: grant.id } },
        }),
      ),
    onSuccess: async (_nothing, revoked) => {
      await applyToCache<ProjectGrant[]>(queryClient, projectGrantsKey(project.id), (grants) =>
        grants.filter((grant) => grant.id !== revoked.id),
      )
      if (isMe(queryClient, revoked)) {
        await reload(queryClient, ownProjectKeys(project))
      }
    },
  })
}

/** What follows the user's own role on a list: its page and the project's index. */
function ownListKeys(list: TodoList): QueryKey[] {
  return [listKey(list.id), projectListsKey(list.project_id)]
}

/** Give a principal a role of their own on a list (`none` hides it), or change it. */
export function useSetListGrant(list: TodoList) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ListGrantIn']) =>
      unwrap(api.PUT('/api/lists/{list_id}/grants', { params: { path: { list_id: list.id } }, body })),
    onSuccess: async (saved) => {
      await applyToCache<ListGrant[]>(queryClient, listGrantsKey(list.id), (grants) => withGrant(grants, saved))
      if (isMe(queryClient, saved)) {
        await reload(queryClient, ownListKeys(list))
      }
    },
  })
}

/** Take a grant on a list away; the role on the project applies again. */
export function useRevokeListGrant(list: TodoList) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (grant: GrantRef) =>
      unwrap(
        api.DELETE('/api/lists/{list_id}/grants/{grant_id}', {
          params: { path: { list_id: list.id, grant_id: grant.id } },
        }),
      ),
    onSuccess: async (_nothing, revoked) => {
      await applyToCache<ListGrant[]>(queryClient, listGrantsKey(list.id), (grants) =>
        grants.filter((grant) => grant.id !== revoked.id),
      )
      if (isMe(queryClient, revoked)) {
        await reload(queryClient, ownListKeys(list))
      }
    },
  })
}
