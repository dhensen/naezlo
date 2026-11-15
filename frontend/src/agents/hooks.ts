import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'
import { applyToCache } from '../api/queryClient'
import { agentsKey } from '../sharing/hooks'
import type { Agent } from '../sharing/hooks'

/** Register an agent in an organization (owners and admins). It is added to the cached list. */
export function useCreateAgent(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['AgentIn']) =>
      unwrap(api.POST('/api/orgs/{org_id}/agents', { params: { path: { org_id: organizationId } }, body })),
    onSuccess: (agent) =>
      applyToCache<Agent[]>(queryClient, agentsKey(organizationId), (agents) => [...agents, agent]),
  })
}

/** Change the name or the description of an agent. */
export function useUpdateAgent(organizationId: string, agentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['AgentPatch']) =>
      unwrap(
        api.PATCH('/api/orgs/{org_id}/agents/{agent_id}', {
          params: { path: { org_id: organizationId, agent_id: agentId } },
          body,
        }),
      ),
    onSuccess: (agent) =>
      applyToCache<Agent[]>(queryClient, agentsKey(organizationId), (agents) =>
        agents.map((candidate) => (candidate.id === agent.id ? agent : candidate)),
      ),
  })
}

/** Delete an agent, with its grants and the tokens of the tools that were connected as it. */
export function useDeleteAgent(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) =>
      unwrap(
        api.DELETE('/api/orgs/{org_id}/agents/{agent_id}', {
          params: { path: { org_id: organizationId, agent_id: agentId } },
        }),
      ),
    onSuccess: async (_, agentId) => {
      await applyToCache<Agent[]>(queryClient, agentsKey(organizationId), (agents) =>
        agents.filter((agent) => agent.id !== agentId),
      )
      // Its grants went with it; the sharing dialogs must not show them from the cache.
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey.includes('grants') })
    },
  })
}
