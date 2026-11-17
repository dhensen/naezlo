import { useState } from 'react'

import { useDeleteAgent } from '../agents/hooks'
import { EditAgentDialog, NewAgentDialog } from '../components/AgentDialogs'
import { ConnectAgentDialog, FIRST_AGENT_NOTE } from '../components/ConnectAgentDialog'
import { Avatar } from '../components/Avatar'
import { ErrorMessage } from '../components/ErrorMessage'
import { useCurrentOrganization } from '../orgs/hooks'
import type { Organization } from '../orgs/hooks'
import { useAgents } from '../sharing/hooks'
import type { Agent } from '../sharing/hooks'

const PRIMARY_BUTTON =
  'rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60'
const SMALL_BUTTON =
  'rounded-lg border border-ink-300 px-2.5 py-1 text-sm font-medium text-ink-700 hover:bg-ink-50 disabled:opacity-60'
const DANGER_BUTTON =
  'rounded-lg border border-ink-300 bg-white px-2.5 py-1 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50 disabled:opacity-60'

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/** "2 projects, 3 lists": what the agent can reach. */
function reach(agent: Agent): string {
  if (agent.list_count === 0) {
    return 'Nothing shared with it yet'
  }
  return `${counted(agent.project_count, 'project', 'projects')}, ${counted(agent.list_count, 'list', 'lists')}`
}

/** The agents of an organization (`/o/:orgSlug/agents`); owners and admins manage them. */
export function AgentsPage() {
  const { organization } = useCurrentOrganization()
  if (organization === null) {
    return null
  }
  // Keyed, so an open dialog or question does not move along to another organization.
  return <Agents key={organization.id} organization={organization} />
}

type Open = { kind: 'new' } | { kind: 'edit'; agent: Agent } | { kind: 'connect'; agent: Agent; first: boolean }

function Agents({ organization }: { organization: Organization }) {
  const agents = useAgents(organization.id)
  const remove = useDeleteAgent(organization.id)
  const [open, setOpen] = useState<Open | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  // Stays on the page after the connect panel of the first agent is closed.
  const [gotFirstAgent, setGotFirstAgent] = useState(false)
  const canManage = organization.role === 'owner' || organization.role === 'admin'
  const close = () => setOpen(null)

  function created(agent: Agent) {
    const first = agents.data?.length === 0
    if (first) {
      setGotFirstAgent(true)
    }
    setOpen({ kind: 'connect', agent, first })
  }

  return (
    <main className="flex w-full max-w-3xl flex-1 flex-col gap-6 mx-auto p-4 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-start justify-between gap-3 sm:flex-nowrap">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Agents</h1>
          <p className="text-sm text-ink-600">
            An agent is the identity an AI tool such as Claude or Codex works under. It sees only the projects and
            lists that are shared with it.
            {!canManage && ' Only owners and admins can add, change and connect agents.'}
          </p>
        </div>
        {canManage && (
          <button type="button" className={`shrink-0 ${PRIMARY_BUTTON}`} onClick={() => setOpen({ kind: 'new' })}>
            New agent
          </button>
        )}
      </div>
      {gotFirstAgent && (
        <p role="note" className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-900">
          {FIRST_AGENT_NOTE}
        </p>
      )}
      {agents.isPending && (
        <p role="status" className="text-sm text-ink-500">
          Loading…
        </p>
      )}
      <ErrorMessage error={agents.error} />
      <ErrorMessage error={remove.error} />
      {agents.data?.length === 0 && (
        <p className="rounded-xl border border-dashed border-ink-300 p-6 text-center text-sm text-ink-600">
          No agents yet.{canManage && ' Create one to connect Claude, Codex or another AI tool.'}
        </p>
      )}
      {agents.data && agents.data.length > 0 && (
        <ul aria-label="Agents" className="flex flex-col divide-y divide-ink-100 rounded-xl border border-ink-200 bg-white shadow-card">
          {agents.data.map((agent) => (
            <li key={agent.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 p-4">
              <Avatar name={agent.name} kind="agent" className="size-9 self-start rounded-lg" />
              <div className="flex min-w-40 flex-1 flex-col gap-0.5">
                <h2 className="font-semibold break-words text-ink-900">{agent.name}</h2>
                {agent.description !== null && (
                  <p className="text-sm break-words whitespace-pre-line text-ink-600">{agent.description}</p>
                )}
                <p className="text-sm text-ink-500">
                  <span className="sr-only">Can access: </span>
                  {reach(agent)}
                </p>
              </div>
              {canManage && (
                <div className="flex flex-wrap items-center gap-2">
                  {confirming === agent.id ? (
                    <>
                      <span className="text-sm text-ink-600">Delete it and disconnect its tools?</span>
                      <button
                        type="button"
                        disabled={remove.isPending}
                        className={DANGER_BUTTON}
                        onClick={() => remove.mutate(agent.id, { onSettled: () => setConfirming(null) })}
                      >
                        Yes, delete
                      </button>
                      <button
                        type="button"
                        disabled={remove.isPending}
                        className={SMALL_BUTTON}
                        onClick={() => setConfirming(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        aria-label={`Connect ${agent.name}`}
                        className={SMALL_BUTTON}
                        onClick={() => setOpen({ kind: 'connect', agent, first: false })}
                      >
                        Connect
                      </button>
                      <button
                        type="button"
                        aria-label={`Edit ${agent.name}`}
                        className={SMALL_BUTTON}
                        onClick={() => setOpen({ kind: 'edit', agent })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete ${agent.name}`}
                        className={DANGER_BUTTON}
                        onClick={() => {
                          remove.reset()
                          setConfirming(agent.id)
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {open?.kind === 'new' && <NewAgentDialog organization={organization} onClose={close} onCreated={created} />}
      {open?.kind === 'edit' && <EditAgentDialog organization={organization} agent={open.agent} onClose={close} />}
      {open?.kind === 'connect' && <ConnectAgentDialog agent={open.agent} first={open.first} onClose={close} />}
    </main>
  )
}
