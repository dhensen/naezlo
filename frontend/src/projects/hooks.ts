import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'
import { projectsKey } from '../orgs/hooks'
import type { Project } from '../orgs/hooks'

export type ProjectRole = Schemas['ProjectRole']
export type TodoList = Schemas['ListOut']

const RANK: Record<ProjectRole, number> = { viewer: 1, editor: 2, admin: 3 }

/** Whether `role` (the caller's, as the API returns it) is `minimum` or higher. */
export function roleAtLeast(role: ProjectRole, minimum: ProjectRole): boolean {
  return RANK[role] >= RANK[minimum]
}

export function projectKey(projectId: string) {
  return ['projects', projectId] as const
}

export function projectListsKey(projectId: string) {
  return ['projects', projectId, 'lists'] as const
}

/** One project, with the user's role on it. A 404 means it does not exist for the user. */
export function useProject(projectId: string) {
  return useQuery({
    queryKey: projectKey(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/projects/{project_id}', { params: { path: { project_id: projectId } } })),
  })
}

/** The lists of a project that the user can see, in their order. */
export function useProjectLists(projectId: string) {
  return useQuery({
    queryKey: projectListsKey(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/projects/{project_id}/lists', { params: { path: { project_id: projectId } } })),
  })
}

/** Create a project in an organization; the sidebar gets it at once. */
export function useCreateProject(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ProjectIn']) =>
      unwrap(api.POST('/api/orgs/{org_id}/projects', { params: { path: { org_id: organizationId } }, body })),
    onSuccess: (project) => {
      queryClient.setQueryData(projectKey(project.id), project)
      queryClient.setQueryData<Project[]>(projectsKey(organizationId), (projects) =>
        projects ? [...projects, project] : projects,
      )
    },
  })
}

/** Change the name and the description of a project; the page and the sidebar follow. */
export function useUpdateProject(project: Project) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ProjectPatch']) =>
      unwrap(api.PATCH('/api/projects/{project_id}', { params: { path: { project_id: project.id } }, body })),
    onSuccess: (updated) => {
      queryClient.setQueryData(projectKey(updated.id), updated)
      queryClient.setQueryData<Project[]>(projectsKey(updated.organization_id), (projects) =>
        projects?.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
      )
    },
  })
}

/**
 * Delete a project with its lists and items; the sidebar loses it at once. The caller
 * navigates away from the project's page in its own `onSuccess`.
 */
export function useDeleteProject(project: Project) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/projects/{project_id}', { params: { path: { project_id: project.id } } })),
    onSuccess: () => {
      queryClient.setQueryData<Project[]>(projectsKey(project.organization_id), (projects) =>
        projects?.filter((candidate) => candidate.id !== project.id),
      )
    },
  })
}
