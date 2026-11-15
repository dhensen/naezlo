import { APP_NAME } from '../config'

// How each tool is told about a remote (streamable HTTP) MCP server. The syntax was checked
// against the tools' documentation; the sources are listed in DECISIONS.md (US-036).

export type ClientId = 'claude-code' | 'claude-desktop' | 'codex'

export interface Snippet {
  /** What the snippet is, also the accessible name of its copy button. */
  label: string
  text: string
}

export interface ClientGuide {
  id: ClientId
  label: string
  /** How to add the server: the first step. */
  intro: string
  snippets: Snippet[]
  /** How to sign in from that tool: the step after adding the server. */
  signIn: string
  note?: string
}

/**
 * The name the server gets in a tool's configuration: the product name in lower case with
 * dashes, which both `claude mcp add` and `codex mcp add` accept.
 */
export function serverName(appName: string = APP_NAME): string {
  const name = appName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return name === '' ? 'todos' : name
}

export function clientGuides(mcpUrl: string, name: string = serverName()): ClientGuide[] {
  return [
    {
      id: 'claude-code',
      label: 'Claude Code',
      intro:
        'Run this in a terminal. It adds the server for the current project; put --scope user before the name to have it in all your projects.',
      snippets: [{ label: 'Command', text: `claude mcp add --transport http ${name} ${mcpUrl}` }],
      signIn: `Start Claude Code, type /mcp, choose ${name} and follow the steps in your browser to sign in.`,
    },
    {
      id: 'claude-desktop',
      label: 'Claude desktop / claude.ai',
      intro:
        'In Claude, open Customize > Connectors, choose "+ Add" and then "Add custom connector". Enter a name and this URL, and confirm with "Continue" and "Add". On a Team or Enterprise plan an owner adds it under Organization settings > Connectors, and members then choose "Connect".',
      snippets: [{ label: 'Remote MCP server URL', text: mcpUrl }],
      signIn: 'Sign in when Claude opens the sign-in page (at once, or the first time the connector is used).',
      note: "Claude connects from Anthropic's servers, so this only works when the URL is reachable from the internet over HTTPS (not with localhost).",
    },
    {
      id: 'codex',
      label: 'Codex',
      intro: 'Run this in a terminal, or add the lines below to ~/.codex/config.toml yourself.',
      snippets: [
        { label: 'Command', text: `codex mcp add ${name} --url ${mcpUrl}` },
        { label: '~/.codex/config.toml', text: `[mcp_servers.${name}]\nurl = "${mcpUrl}"` },
      ],
      signIn: `Codex opens your browser to sign in when it adds the server. If it does not, run: codex mcp login ${name}`,
    },
  ]
}
