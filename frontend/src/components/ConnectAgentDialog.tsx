import { useId, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

import { clientGuides } from '../agents/connect'
import type { ClientId } from '../agents/connect'
import { useAppConfig } from '../auth/hooks'
import type { Agent } from '../sharing/hooks'
import { CopyButton } from './CopyButton'
import { Dialog, DIALOG_SUBMIT } from './Dialog'
import { ErrorMessage } from './ErrorMessage'

/** What the page says once an organization has its first agent. */
export const FIRST_AGENT_NOTE =
  'This organization now has an agent, so new lists default to Mixed: people and agents work on them together. Existing lists keep their mode.'

interface ConnectAgentDialogProps {
  agent: Agent
  /** The agent was just created as the first one of its organization. */
  first?: boolean
  onClose: () => void
}

function Code({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ink-500">{label}</span>
      {/* One dark field with the copy button in it; a long command wraps instead of running out. */}
      <div className="flex items-start gap-2 rounded-lg bg-ink-900 py-1.5 pr-1.5 pl-3">
        <pre
          aria-label={label}
          tabIndex={0}
          className="min-w-0 flex-1 py-1 text-xs leading-5 wrap-anywhere whitespace-pre-wrap text-ink-100"
        >
          <code>{text}</code>
        </pre>
        <CopyButton text={text} label={label} embedded />
      </div>
    </div>
  )
}

/**
 * How to connect an AI tool as this agent: the MCP server URL, and per tool the command or
 * the settings to add it, followed by the steps that are the same everywhere.
 */
export function ConnectAgentDialog({ agent, first = false, onClose }: ConnectAgentDialogProps) {
  const config = useAppConfig()
  const id = useId()
  const [selected, setSelected] = useState<ClientId>('claude-code')
  const tabs = useRef(new Map<ClientId, HTMLButtonElement>())
  const mcpUrl = config.data?.mcp_url
  const guides = mcpUrl === undefined ? [] : clientGuides(mcpUrl)
  const guide = guides.find((candidate) => candidate.id === selected)

  function onTabKey(event: KeyboardEvent) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) {
      return
    }
    event.preventDefault()
    const index = guides.findIndex((candidate) => candidate.id === selected)
    const next = guides[(index + step + guides.length) % guides.length]
    setSelected(next.id)
    tabs.current.get(next.id)?.focus()
  }

  return (
    <Dialog title={`Connect ${agent.name}`} wide onClose={onClose}>
      <div className="mt-3 flex flex-col gap-4 text-sm text-ink-700">
        {first && (
          <p role="note" className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-brand-900">
            {FIRST_AGENT_NOTE}
          </p>
        )}
        <p>
          An AI tool connects to the MCP server below and then acts as <strong>{agent.name}</strong>: it sees and
          changes only what is shared with this agent.
        </p>
        {config.isPending && <p role="status">Loading…</p>}
        <ErrorMessage error={config.error} />
        {mcpUrl !== undefined && guide && (
          <>
            <Code label="MCP server URL" text={mcpUrl} />
            <div>
              <div role="tablist" aria-label="AI tool" className="flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-ink-200)] [scrollbar-width:none]">
                {guides.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    role="tab"
                    id={`${id}-tab-${candidate.id}`}
                    aria-selected={candidate.id === selected}
                    aria-controls={`${id}-panel`}
                    tabIndex={candidate.id === selected ? 0 : -1}
                    ref={(element) => {
                      if (element) {
                        tabs.current.set(candidate.id, element)
                      } else {
                        tabs.current.delete(candidate.id)
                      }
                    }}
                    className={`shrink-0 rounded-t-md border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap sm:py-1.5 ${
                      candidate.id === selected
                        ? 'border-brand-600 text-brand-700'
                        : 'border-transparent text-ink-500 hover:text-ink-800'
                    }`}
                    onClick={() => setSelected(candidate.id)}
                    onKeyDown={onTabKey}
                  >
                    {candidate.label}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${guide.id}`} className="pt-3">
                <ol className="flex list-decimal flex-col gap-3 pl-5 marker:font-medium marker:text-ink-500">
                  <li>
                    <div className="flex flex-col gap-2">
                      <p>{guide.intro}</p>
                      {guide.snippets.map((snippet) => (
                        <Code key={snippet.label} label={snippet.label} text={snippet.text} />
                      ))}
                      {guide.note && <p className="text-ink-500">{guide.note}</p>}
                    </div>
                  </li>
                  <li>{guide.signIn}</li>
                  <li>
                    On the consent screen, pick the agent <strong>{agent.name}</strong> and approve. Only owners and
                    admins of the organization can do that.
                  </li>
                  <li>
                    Share a project or a list with <strong>{agent.name}</strong> (the "Share" button on a project or
                    a list). The agent only sees lists in the Mixed or AI-only mode.
                  </li>
                </ol>
              </div>
            </div>
          </>
        )}
        <div className="flex justify-end">
          <button type="button" className={DIALOG_SUBMIT} onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Dialog>
  )
}
