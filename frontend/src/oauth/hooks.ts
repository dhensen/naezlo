import { useMutation, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'

export type AuthorizationRequest = Schemas['AuthorizationRequestOut']
export type ConsentAgent = Schemas['ConsentAgentOut']

/** What the user answers on the consent page: allow the client to act as an agent, or deny. */
export type ConsentAnswer = { allow: true; agentId: string } | { allow: false }

/**
 * A pending authorization request of an MCP client, with the agents the user may pick.
 * It is a 404 once it expired or was answered.
 */
export function useAuthorizationRequest(requestId: string) {
  return useQuery({
    queryKey: ['oauth', 'requests', requestId],
    queryFn: () =>
      unwrap(api.GET('/api/oauth/requests/{request_id}', { params: { path: { request_id: requestId } } })),
  })
}

/** Answer the request. The result holds the URL that brings the browser back to the client. */
export function useAnswerAuthorizationRequest(requestId: string) {
  const params = { path: { request_id: requestId } }
  return useMutation({
    mutationFn: (answer: ConsentAnswer) =>
      answer.allow
        ? unwrap(api.POST('/api/oauth/requests/{request_id}/approve', { params, body: { agent_id: answer.agentId } }))
        : unwrap(api.POST('/api/oauth/requests/{request_id}/deny', { params })),
  })
}
