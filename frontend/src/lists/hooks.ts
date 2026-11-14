import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'
import { applyToCache } from '../api/queryClient'
import { projectListsKey } from '../projects/hooks'
import type { TodoList } from '../projects/hooks'

export type ListAction = Schemas['ListAction']

/**
 * Whether the user may do this with the list. The API decides (the role and the list mode
 * together) and says so in `actions`; the UI only shows or hides a control with it.
 */
export function listAllows(list: TodoList, action: ListAction): boolean {
  return list.actions.includes(action)
}

/** Create a list at the end of a project; the project page gets it at once. */
export function useCreateList(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ListIn']) =>
      unwrap(api.POST('/api/projects/{project_id}/lists', { params: { path: { project_id: projectId } }, body })),
    onSuccess: (created) =>
      applyToCache<TodoList[]>(queryClient, projectListsKey(projectId), (lists) => [...lists, created]),
  })
}

/** Change the name, the description or the mode of a list; the project page follows. */
export function useUpdateList(list: TodoList) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ListPatch']) =>
      unwrap(api.PATCH('/api/lists/{list_id}', { params: { path: { list_id: list.id } }, body })),
    onSuccess: (updated) =>
      applyToCache<TodoList[]>(queryClient, projectListsKey(updated.project_id), (lists) =>
        lists.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
      ),
  })
}

/** Delete a list with its items; the project page loses it at once. */
export function useDeleteList(list: TodoList) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/lists/{list_id}', { params: { path: { list_id: list.id } } })),
    onSuccess: () =>
      applyToCache<TodoList[]>(queryClient, projectListsKey(list.project_id), (lists) =>
        lists.filter((candidate) => candidate.id !== list.id),
      ),
  })
}
