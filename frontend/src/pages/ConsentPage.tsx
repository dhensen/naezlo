import { useState } from 'react'
import type { FormEvent } from 'react'
import { useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { useMe } from '../auth/hooks'
import { leaveTo } from '../auth/next'
import { ErrorMessage } from '../components/ErrorMessage'
import { APP_NAME } from '../config'
import { useAnswerAuthorizationRequest, useAuthorizationRequest } from '../oauth/hooks'
import type { AuthorizationRequest, ConsentAgent, ConsentAnswer } from '../oauth/hooks'
import { orgPath } from '../orgs/paths'

const PRIMARY_BUTTON =
  'rounded-md bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-60'
const SECONDARY_BUTTON =
  'rounded-md border border-slate-300 px-4 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60'

const GONE =
  'This authorization request was not found. It may have expired or been answered already. ' +
  'Go back to the application and connect again.'

/** A request that is gone (or an id that never was one) gets one clear text; the rest its own. */
function requestError(error: unknown): unknown {
  return error instanceof ApiError && (error.status === 404 || error.status === 422) ? GONE : error
}

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]'])

function isLoopback(host: string): boolean {
  return LOOPBACK_HOSTS.has(host.replace(/:\d+$/, ''))
}

interface AgentGroup {
  organization: ConsentAgent['organization']
  agents: ConsentAgent[]
}

/** The agents per organization, in the order the API gives them. */
function groupByOrganization(agents: ConsentAgent[]): AgentGroup[] {
  const groups = new Map<string, AgentGroup>()
  for (const agent of agents) {
    const group = groups.get(agent.organization.id)
    if (group === undefined) {
      groups.set(agent.organization.id, { organization: agent.organization, agents: [agent] })
    } else {
      group.agents.push(agent)
    }
  }
  return [...groups.values()]
}

/**
 * The consent screen of the OAuth flow (`/oauth/consent?request=<id>`): an MCP client sent
 * the browser to /authorize, and here the user decides whether it gets access and as which
 * agent. Either answer sends the browser back to the client.
 */
export function ConsentPage() {
  const [params] = useSearchParams()
  const requestId = params.get('request')

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-6 py-10 text-slate-900">
      <div className="flex w-full max-w-md flex-col gap-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        {requestId === null || requestId === '' ? (
          <>
            <h1 className="text-2xl font-semibold tracking-tight">Connect an application</h1>
            <ErrorMessage error={GONE} />
          </>
        ) : (
          <Consent key={requestId} requestId={requestId} />
        )}
      </div>
    </main>
  )
}

function Consent({ requestId }: { requestId: string }) {
  const request = useAuthorizationRequest(requestId)
  const answer = useAnswerAuthorizationRequest(requestId)

  if (answer.isSuccess) {
    // The browser is on its way out; the request no longer exists.
    return (
      <p role="status" className="text-center text-slate-600">
        Returning to the application…
      </p>
    )
  }
  if (request.isPending) {
    return (
      <p role="status" className="text-center text-slate-500">
        Loading…
      </p>
    )
  }
  if (request.isError) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">Connect an application</h1>
        <ErrorMessage error={requestError(request.error)} />
      </>
    )
  }
  return (
    <ConsentForm
      request={request.data}
      error={answer.error}
      busy={answer.isPending}
      onAnswer={(choice) => answer.mutate(choice, { onSuccess: ({ redirect_url }) => leaveTo(redirect_url) })}
    />
  )
}

interface ConsentFormProps {
  request: AuthorizationRequest
  error: unknown
  busy: boolean
  onAnswer: (answer: ConsentAnswer) => void
}

function ConsentForm({ request, error, busy, onAnswer }: ConsentFormProps) {
  const me = useMe()
  const groups = groupByOrganization(request.agents)
  const onlyAgent = request.agents.length === 1 ? request.agents[0].id : null
  const [picked, setPicked] = useState<string | null>(onlyAgent)
  // An agent that was deleted meanwhile (the request is loaded again) is no longer a choice.
  const agentId = request.agents.some((agent) => agent.id === picked) ? picked : onlyAgent
  const clientName = request.client_name ?? 'An application'
  // Agents are managed by the owners and admins of an organization.
  const manageable = (me.data?.organizations ?? []).filter(
    (organization) => organization.role === 'owner' || organization.role === 'admin',
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    if (agentId !== null) {
      onAnswer({ allow: true, agentId })
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          <span className="break-words">{clientName}</span> wants to access {APP_NAME}
        </h1>
        <p className="text-sm text-slate-600">
          It will work as the agent you choose and reach only the projects and lists that are shared with that
          agent.
        </p>
      </div>

      <dl className="flex flex-col gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
        <div className="flex flex-wrap justify-between gap-x-3">
          <dt className="text-slate-600">Application</dt>
          <dd className="break-all font-medium">{request.client_name ?? 'Unnamed application'}</dd>
        </div>
        <div className="flex flex-wrap justify-between gap-x-3">
          <dt className="text-slate-600">After your answer you go to</dt>
          <dd className="break-all font-mono font-medium">{request.redirect_host}</dd>
        </div>
        {me.data && (
          <div className="flex flex-wrap justify-between gap-x-3">
            <dt className="text-slate-600">Signed in as</dt>
            <dd className="break-all font-medium">{me.data.user.email}</dd>
          </div>
        )}
      </dl>
      <p role="note" className="text-sm text-slate-600">
        {isLoopback(request.redirect_host)
          ? 'That address is an application on this computer. '
          : 'Check that this address belongs to the application you are connecting. '}
        The name is what the application calls itself; allow it only when you started this yourself.
      </p>

      {groups.length === 0 ? (
        <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            <strong className="font-semibold">Create an agent first.</strong> An application connects as an agent,
            and there is no agent yet that you may connect.
          </p>
          {manageable.length === 0 ? (
            <p>Only the owners and admins of an organization can create and connect agents. Ask one of them.</p>
          ) : (
            <>
              <ul className="flex flex-col gap-1">
                {manageable.map((organization) => (
                  <li key={organization.id}>
                    {/* A new tab: this page, with its request, stays open and loads the agents on return. */}
                    <a
                      href={orgPath(organization.slug, '/agents')}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium underline"
                    >
                      Agents of {organization.name}
                    </a>
                  </li>
                ))}
              </ul>
              <p>The agents page opens in a new tab. Come back here afterwards to choose the agent.</p>
            </>
          )}
        </div>
      ) : (
        <div role="group" aria-labelledby="consent-agents" className="flex flex-col gap-3">
          <h2 id="consent-agents" className="text-sm font-semibold text-slate-900">
            Connect as
          </h2>
          {groups.map(({ organization, agents }) => (
            <fieldset key={organization.id} className="flex flex-col gap-1">
              <legend className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                {organization.name}
              </legend>
              {agents.map((agent) => (
                <label
                  key={agent.id}
                  className="flex cursor-pointer items-start gap-3 rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50 has-checked:border-slate-900 has-checked:bg-slate-50"
                >
                  <input
                    type="radio"
                    name="agent"
                    value={agent.id}
                    checked={agentId === agent.id}
                    onChange={() => setPicked(agent.id)}
                    // The label holds the description too; the name is the agent's name alone.
                    aria-labelledby={`consent-agent-name-${agent.id}`}
                    aria-describedby={agent.description === null ? undefined : `consent-agent-description-${agent.id}`}
                    className="mt-1"
                  />
                  <span className="flex min-w-0 flex-col">
                    <span id={`consent-agent-name-${agent.id}`} className="font-medium break-words">
                      {agent.name}
                    </span>
                    {agent.description !== null && (
                      <span id={`consent-agent-description-${agent.id}`} className="text-sm break-words text-slate-600">
                        {agent.description}
                      </span>
                    )}
                  </span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
      )}

      <ErrorMessage error={error === null ? null : requestError(error)} />

      <div className="flex justify-end gap-3">
        <button type="button" className={SECONDARY_BUTTON} disabled={busy} onClick={() => onAnswer({ allow: false })}>
          Deny
        </button>
        {groups.length > 0 && (
          <button type="submit" className={PRIMARY_BUTTON} disabled={busy || agentId === null}>
            Allow
          </button>
        )}
      </div>
    </form>
  )
}
