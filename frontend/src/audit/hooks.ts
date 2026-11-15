import { useInfiniteQuery } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'

export type AuditEvent = Schemas['AuditEventOut']
export type AuditPage = Schemas['AuditPageOut']
export type ActionGroup = Schemas['ActionGroup']

/** Whose log: a project's (with its lists and their items) or one list's. */
export interface ActivityScope {
  kind: 'project' | 'list'
  id: string
}

/** What to leave out of the log; null leaves nothing out. */
export interface ActivityFilters {
  actorKind: Schemas['PrincipalKind'] | null
  group: ActionGroup | null
}

export function activityKey(scope: ActivityScope, filters: ActivityFilters) {
  return [scope.kind === 'project' ? 'projects' : 'lists', scope.id, 'audit', filters] as const
}

/**
 * The audit log of a project or a list, newest first, one page at a time: `fetchNextPage`
 * asks for the older events with the cursor of the last page. Admins only (403 otherwise).
 * It is asked again whenever it is shown, so it has what just happened on the page.
 */
export function useActivity(scope: ActivityScope, filters: ActivityFilters) {
  return useInfiniteQuery({
    queryKey: activityKey(scope, filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }): Promise<AuditPage> => {
      const query = {
        cursor: pageParam ?? undefined,
        actor_kind: filters.actorKind ?? undefined,
        group: filters.group ?? undefined,
      }
      return scope.kind === 'project'
        ? unwrap(api.GET('/api/projects/{project_id}/audit', { params: { path: { project_id: scope.id }, query } }))
        : unwrap(api.GET('/api/lists/{list_id}/audit', { params: { path: { list_id: scope.id }, query } }))
    },
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 0,
  })
}
